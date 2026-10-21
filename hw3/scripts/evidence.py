"""Record real command outputs and independently verify S3 object integrity."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frontend_lake.common import CONFIG, ROOT, dump
from frontend_lake.storage import client


def main():
    from frontend_lake.validation import require

    commands = [
        [
            "docker",
            "ps",
            "--filter",
            "name=frontend-hw8-rustfs",
            "--format",
            "{{.Names}} | {{.Status}} | {{.Ports}}",
        ],
        ["docker", "logs", "--tail", "10", "frontend-hw8-rustfs"],
        ["docker", "inspect", "frontend-hw8-rustfs", "--format", "{{json .Mounts}}"],
        ["docker", "image", "inspect", "rustfs/rustfs:1.0.0", "--format", "{{json .RepoDigests}}"],
        [
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{.Name}} | {{.CPUPerc}} | {{.MemUsage}}",
            "frontend-hw8-rustfs",
        ],
        [sys.executable, "-m", "pytest", "-q"],
    ]
    logs = []
    for command in commands:
        proc = subprocess.run(
            command, cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace"
        )
        logs.append(
            "$ "
            + " ".join(command)
            + "\n"
            + proc.stdout
            + proc.stderr
            + "\nexit="
            + str(proc.returncode)
        )
        if proc.returncode:
            raise RuntimeError(logs[-1])
    c = client()
    objects = {}
    for page in c.get_paginator("list_objects_v2").paginate(Bucket=CONFIG["bucket"]):
        objects.update({r["Key"]: r["Size"] for r in page.get("Contents", [])})
    manifest = json.loads((ROOT / "output/manifest.json").read_text(encoding="utf-8"))
    require(
        objects[CONFIG["raw_key"]] == manifest["csv"]["bytes"],
        "Validation failed: objects[CONFIG['raw_key']] == manifest['csv']['bytes']",
    )
    for item in manifest["json_files"]:
        require(
            objects[item["key"]] == item["bytes"],
            "Validation failed: objects[item['key']] == item['bytes']",
        )
    response = c.get_object(Bucket=CONFIG["bucket"], Key=CONFIG["raw_key"])
    digest = hashlib.sha256()
    try:
        for chunk in response["Body"].iter_chunks(chunk_size=4 * 1024 * 1024):
            digest.update(chunk)
    finally:
        response["Body"].close()
    require(
        digest.hexdigest() == manifest["csv"]["sha256"],
        "Validation failed: digest.hexdigest() == manifest['csv']['sha256']",
    )
    samples = []
    for item in manifest["json_files"][::1999]:
        response = c.get_object(Bucket=CONFIG["bucket"], Key=item["key"])
        try:
            require(
                hashlib.sha256(response["Body"].read()).hexdigest() == item["sha256"],
                "Validation failed: hashlib.sha256(response['Body'].read()).hexdigest() == item['sha256']",
            )
        finally:
            response["Body"].close()
        samples.append(item["key"])
    evidence = {
        "csv_download_sha256": digest.hexdigest(),
        "csv_integrity_equal": True,
        "json_objects_verified_by_size": len(manifest["json_files"]),
        "json_download_sha256_samples": samples,
        "json_sample_integrity_equal": True,
        "raw_json_count": sum(k.startswith("raw/hh/") for k in objects),
        "total_objects_at_audit": len(objects),
        "object_sizes": objects,
    }
    dump(ROOT / "output/storage_evidence.json", evidence)
    logs.append(
        "S3 integrity: "
        + json.dumps(
            {k: v for k, v in evidence.items() if k != "object_sizes"}, ensure_ascii=False, indent=2
        )
    )
    logs.append("BENCHMARK COMMAND OUTPUTS")
    for path in sorted((ROOT / "output/logs").glob("*.json")):
        r = json.loads(path.read_text(encoding="utf-8"))
        logs.append(
            "$ "
            + " ".join(r["command"])
            + "\n"
            + r["stdout"]
            + r["stderr"]
            + "exit="
            + str(r["exit_code"])
        )
    (ROOT / "output/command_evidence.txt").write_text("\n\n".join(logs), encoding="utf-8")
    print("S3 audit passed: CSV SHA-256, all 10,000 JSON sizes and sampled JSON SHA-256.")


if __name__ == "__main__":
    main()
