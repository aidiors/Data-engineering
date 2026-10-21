"""Serial S3 benchmarks with fresh processes and full-result verification."""

import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from importlib.metadata import version

import psutil

from .common import CONFIG, ROOT, dump, write_csv
from .validation import compare, require

METHODS = ("mr", "duck_csv", "duck_parquet")


def benchmark(method, cap, repeat):
    """Measure a complete worker run and retain its output without pipe deadlocks."""
    path = ROOT / "output/runs" / f"{method}_{cap}_{repeat}.json"
    command = [
        sys.executable,
        "-m",
        "frontend_lake",
        "--method",
        method,
        "--cap",
        str(cap),
        "--output",
        str(path),
    ]
    start = time.perf_counter()
    peak = 0
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=stdout_file,
            stderr=stderr_file,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        watched = psutil.Process(process.pid)
        try:
            while process.poll() is None:
                try:
                    # Windows venv launchers can create a second Python process.
                    processes = [watched] + watched.children(recursive=True)
                    memories = [p.memory_info() for p in processes if p.is_running()]
                    peak = max(peak, sum(getattr(m, "peak_wset", m.rss) for m in memories))
                except psutil.NoSuchProcess:
                    pass
                time.sleep(0.01)
        except BaseException:
            if process.poll() is None:
                for child in watched.children(recursive=True):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                process.kill()
                process.wait()
            raise
        wall = time.perf_counter() - start
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read().decode("utf-8", errors="replace")
        stderr = stderr_file.read().decode("utf-8", errors="replace")
    dump(
        ROOT / "output/logs" / f"{method}_{cap}_{repeat}.json",
        {
            "command": [part.replace(str(ROOT), "<PROJECT>") for part in command],
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": process.returncode,
        },
    )
    require(process.returncode == 0, f"Worker {method} failed: {stderr}")
    result = json.loads(path.read_text(encoding="utf-8"))
    peak = max(peak, result["os_peak_rss_bytes"])
    metric = {
        "method": method,
        "cap": cap,
        "repeat": repeat,
        "wall_seconds": wall,
        "compute_seconds": result["compute_seconds"],
        "peak_rss_mib": peak / 1024**2,
    }
    print(f"{stdout.strip()} | wall={wall:.3f}s peak={peak / 1024**2:.1f}MiB", flush=True)
    return result, metric


def summarize(metrics):
    groups = defaultdict(list)
    for item in metrics:
        groups[item["method"], item["cap"]].append(item)
    return [
        {
            "method": method,
            "cap": cap,
            "n": len(items),
            "median_wall_seconds": statistics.median(x["wall_seconds"] for x in items),
            "min_wall_seconds": min(x["wall_seconds"] for x in items),
            "max_wall_seconds": max(x["wall_seconds"] for x in items),
            "median_peak_rss_mib": statistics.median(x["peak_rss_mib"] for x in items),
            "max_peak_rss_mib": max(x["peak_rss_mib"] for x in items),
        }
        for (method, cap), items in groups.items()
    ]


def environment_details():
    def docker(*args):
        return subprocess.check_output(["docker", *args], text=True).strip()

    return {
        "python": sys.version,
        "platform": platform.platform(),
        "logical_cpus": psutil.cpu_count(),
        "ram_gib": psutil.virtual_memory().total / 1024**3,
        "config": CONFIG,
        "versions": {p: version(p) for p in ("duckdb", "boto3", "psutil")},
        "docker_version": docker("version", "--format", "{{.Server.Version}}"),
        "rustfs_image": docker(
            "image", "inspect", "rustfs/rustfs:1.0.0", "--format", "{{json .RepoDigests}}"
        ),
        "memory_definition": "Maximum sum of per-process OS peak working sets, sampled every 10 ms. "
        "A conservative upper bound for the process tree, excluding RustFS.",
        "cache_policy": "OS and S3 caches are not flushed. Fresh client processes, rotated methods.",
    }


def main():
    from .duck import prepare

    require(CONFIG["repeats"] >= 3, "Profiling requires at least three repetitions")
    dump(ROOT / "output/environment.json", environment_details())
    dump(ROOT / "output/preparation.json", prepare())
    references, metrics, checks = {}, [], []
    for repeat in range(1, CONFIG["repeats"] + 1):
        offset = (repeat - 1) % len(METHODS)
        for cap in CONFIG["stack_sizes"]:
            for method in METHODS[offset:] + METHODS[:offset]:
                result, metric = benchmark(method, cap, repeat)
                metrics.append(metric)
                dump(ROOT / "output/benchmark_raw.json", metrics)
                references.setdefault(cap, result)
                digest = compare(references[cap], result)
                checks.append(
                    {
                        "method": method,
                        "cap": cap,
                        "repeat": repeat,
                        "equal": True,
                        "sha256_counts": digest,
                        "unique_combinations": result["unique_combinations"],
                        "sum_frequencies": result["sum_frequencies"],
                    }
                )
                dump(ROOT / "output/verification.json", checks)
                if repeat == 1:
                    label = str(cap) if cap else "all"
                    dump(ROOT / "output/counts" / f"{method}_{label}.json", result)
                    write_csv(
                        ROOT / "output/counts" / f"{method}_{label}.csv",
                        (
                            {
                                "k": r["k"],
                                "skills_json": json.dumps(r["skills"], ensure_ascii=False),
                                "frequency": r["frequency"],
                            }
                            for r in result["records"]
                        ),
                    )
    summary = summarize(metrics)
    dump(ROOT / "output/benchmark_summary.json", summary)
    write_csv(ROOT / "output/benchmark_raw.csv", metrics)
    write_csv(ROOT / "output/benchmark_summary.csv", summary)
    print(f"ALL {len(checks)} full-result comparisons passed.", flush=True)


if __name__ == "__main__":
    main()
