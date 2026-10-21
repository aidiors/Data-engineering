"""Check computed results, S3 publication and the submitted PDF."""

import argparse
import hashlib
import json
import sys
from collections import Counter
from itertools import product
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frontend_lake.common import CONFIG, ROOT, dump
from frontend_lake.validation import compare, require

METHODS = ("mr", "duck_csv", "duck_parquet")


def read_json(out, name):
    return json.loads((out / name).read_text(encoding="utf-8"))


def check_calculations(out):
    attempts = read_json(out, "benchmark_raw.json")
    checks = read_json(out, "verification.json")
    expected = set(product(METHODS, CONFIG["stack_sizes"], range(1, CONFIG["repeats"] + 1)))
    for label, records in [("benchmarks", attempts), ("verification records", checks)]:
        actual = {(r["method"], r["cap"], r["repeat"]) for r in records}
        require(actual == expected and len(records) == len(expected), f"Incomplete {label}")
    require(all(record["equal"] for record in checks), "A full-result comparison failed")
    require(
        all(r["wall_seconds"] > 0 and r["peak_rss_mib"] > 0 for r in attempts),
        "Benchmark times and peak memory must be positive",
    )
    for cap in CONFIG["stack_sizes"]:
        reference = read_json(out, f"counts/mr_{cap or 'all'}.json")
        for method in METHODS[1:]:
            compare(reference, read_json(out, f"counts/{method}_{cap or 'all'}.json"))
    analytics = read_json(out, "analytics_verification.json")
    require(
        all(
            analytics[key]
            for key in ("regions_equal", "skill_demand_equal", "salary_overall_equal")
        ),
        "SQL and Python analytics did not match",
    )
    require(
        all(row["equal"] for row in analytics["salary_extremes_checked"]),
        "An independent salary comparison failed",
    )
    return len(attempts)


def check_storage(out, *, remote=False):
    storage = read_json(out, "storage_evidence.json")
    manifest = read_json(out, "manifest.json")
    require(
        storage["csv_integrity_equal"] and storage["json_sample_integrity_equal"],
        "Source-object integrity verification failed",
    )
    require(
        storage["raw_json_count"]
        == storage["json_objects_verified_by_size"]
        == manifest["json_count"],
        "The JSON archive is incomplete",
    )
    publication = read_json(out, "publication.json")
    objects = {row["key"]: row for row in publication["objects"]}
    required = {
        f"results/variant8/counts/{method}_{cap or 'all'}.json"
        for method, cap in product(METHODS, CONFIG["stack_sizes"])
    }
    pdf_key = "results/variant8/pdf/Dubovik_Nikita_variant8_hw3.pdf"
    required.add(pdf_key)
    require(required <= objects.keys(), "Some result objects have not been published to RustFS")
    require(
        hashlib.sha256((out / "pdf/Dubovik_Nikita_variant8_hw3.pdf").read_bytes()).hexdigest()
        == objects[pdf_key]["sha256"],
        "Published PDF is stale. Run scripts/publish_results.py",
    )
    if not remote:
        return
    from frontend_lake.storage import client

    s3 = client()
    remote_keys = {
        f"results/variant8/counts/mr_{cap or 'all'}.json" for cap in CONFIG["stack_sizes"]
    }
    remote_keys.add(pdf_key)
    evidence = []
    for key in sorted(remote_keys):
        response = s3.get_object(Bucket=CONFIG["bucket"], Key=key)
        digest = hashlib.sha256()
        try:
            for chunk in response["Body"].iter_chunks(chunk_size=4 * 1024 * 1024):
                digest.update(chunk)
        finally:
            response["Body"].close()
        require(digest.hexdigest() == objects[key]["sha256"], f"S3 checksum mismatch: {key}")
        evidence.append({"key": key, "sha256": digest.hexdigest(), "equal": True})
    dump(out / "result_integrity.json", evidence)
    print(f"PASS: downloaded and verified {len(evidence)} result objects from RustFS.")


def check_pdf(out):
    for name in (
        "region_summary.csv",
        "region_skills.csv",
        "salary_associations.csv",
        "command_evidence.txt",
        "screenshots/status.png",
        "screenshots/raw_csv.png",
    ):
        require((out / name).stat().st_size > 0, f"Missing artifact: {name}")
    audit = read_json(out, "audit.json")
    counts = read_json(out, "counts/mr_all.json")
    with pymupdf.open(out / "pdf/Dubovik_Nikita_variant8_hw3.pdf") as pdf:
        text = "\n".join(page.get_text() for page in pdf)
        compact = text.replace(" ", "")
        for number in [audit["frontend_rows"], *counts["sum_frequencies"]]:
            require(str(number) in compact, f"PDF does not contain control number {number}")
        require(chr(0xFFFD) not in text, "PDF contains replacement glyphs")
        forbidden_dashes = [chr(point) for point in range(0x2010, 0x2016)] + [chr(0x2212)]
        require(not any(dash in text for dash in forbidden_dashes), "Unexpected dash in PDF")
        require(chr(59) not in text, "Unexpected semicolon in PDF")
        image_count = sum(len(page.get_images()) for page in pdf)
        require(image_count == 2, f"Expected 2 useful screenshots, found {image_count}")
        require(pdf.metadata["author"] == "Дубовик Никита", "Incorrect PDF author")
        fonts = Counter(
            span["font"]
            for page in pdf
            for block in page.get_text("dict")["blocks"]
            if "lines" in block
            for line in block["lines"]
            for span in line["spans"]
        )
        require("TimesNewRomanPSMT" in fonts or "DejaVuSerif" in fonts, "Incorrect report font")
        background = pdf[0].get_pixmap(matrix=pymupdf.Matrix(0.1, 0.1), alpha=False).pixel(0, 0)
        require(
            all(
                abs(actual - expected) <= 1
                for actual, expected in zip(background, (10, 16, 29), strict=True)
            ),
            "Incorrect report background",
        )
        dump(
            out / "report_style_check.json",
            {
                "pages": len(pdf),
                "author": pdf.metadata["author"],
                "background": "#0A101D",
                "rendered_background_rgb": list(background),
                "fonts": dict(fonts),
                "long_dashes": 0,
                "semicolons": 0,
                "embedded_screenshots": image_count,
                "screenshots": ["status.png", "raw_csv.png"],
            },
        )
        return len(pdf)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--remote", action="store_true", help="Download and hash published results too"
    )
    args = parser.parse_args()
    out = ROOT / "output"
    attempts = check_calculations(out)
    check_storage(out, remote=args.remote)
    pages = check_pdf(out)
    print(
        f"PASS: {attempts} benchmarks, exact counts, SQL analytics, storage integrity, "
        f"{pages} PDF pages, two screenshots and report style."
    )


if __name__ == "__main__":
    main()
