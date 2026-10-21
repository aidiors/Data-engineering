import argparse
import time

import psutil

from .common import dump


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", choices=["mr", "duck_csv", "duck_parquet"], required=True)
    parser.add_argument("--cap", type=int, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    # Peak from process creation, native allocations included (Windows peak working set).
    started = time.perf_counter()
    if args.cap < 0:
        parser.error("--cap must be nonnegative (0 = all)")
    if args.method == "mr":
        from .mapreduce import run

        result = run(args.cap)
    else:
        from .duck import run

        result = run(args.cap, parquet=args.method == "duck_parquet")
    result["compute_seconds"] = time.perf_counter() - started
    memory = psutil.Process().memory_info()
    result["os_peak_rss_bytes"] = getattr(memory, "peak_wset", memory.rss)
    dump(args.output, result)
    print(
        f"{args.method} cap={args.cap or 'all'} rows={result['source_rows']} frontend={result['selected_rows']} totals={result['sum_frequencies']} elapsed={result['compute_seconds']:.3f}s",
        flush=True,
    )
