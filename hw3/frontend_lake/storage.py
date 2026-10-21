import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.config import Config

from .common import CONFIG, ROOT, dump
from .validation import require


def credentials():
    values = {}
    path = ROOT / ".env"
    if path.exists():
        values.update(
            line.split("=", 1)
            for line in path.read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
    key = os.environ.get("S3_ACCESS_KEY", values.get("S3_ACCESS_KEY"))
    secret = os.environ.get("S3_SECRET_KEY", values.get("S3_SECRET_KEY"))
    require(bool(key and secret), "Missing S3 credentials. Run python scripts/init_env.py first.")
    return key, secret


def client():
    key, secret = credentials()
    return boto3.client(
        "s3",
        endpoint_url=CONFIG["endpoint"],
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        region_name="us-east-1",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            max_pool_connections=16,
            retries={"max_attempts": 3},
        ),
    )


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def upload_file(path, key):
    c = client()
    digest = sha256(path)
    c.upload_file(str(path), CONFIG["bucket"], key, ExtraArgs={"Metadata": {"sha256": digest}})
    head = c.head_object(Bucket=CONFIG["bucket"], Key=key)
    require(
        head["ContentLength"] == path.stat().st_size,
        "Validation failed: head['ContentLength'] == path.stat().st_size",
    )
    return {"key": key, "bytes": head["ContentLength"], "sha256": digest}


def setup():
    c = client()
    if CONFIG["bucket"] not in [b["Name"] for b in c.list_buckets()["Buckets"]]:
        c.create_bucket(Bucket=CONFIG["bucket"])
    raw = upload_file(ROOT / "it_vacancies_2024.csv", CONFIG["raw_key"])
    files = sorted((ROOT / "hh").glob("*.json"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(lambda p: upload_file(p, "raw/hh/" + p.name), files))
    manifest = {
        "csv": raw,
        "json_count": len(records),
        "json_bytes": sum(r["bytes"] for r in records),
        "json_files": records,
    }
    dump(ROOT / "output" / "manifest.json", manifest)
    upload_file(ROOT / "output" / "manifest.json", "manifest.json")
    print(
        json.dumps({k: v for k, v in manifest.items() if k != "json_files"}, ensure_ascii=False),
        flush=True,
    )


def publish_results():
    paths = [
        p
        for p in (ROOT / "output").rglob("*")
        if p.is_file() and "runs" not in p.parts and p.name != "publication.json"
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda p: upload_file(
                    p, "results/variant8/" + p.relative_to(ROOT / "output").as_posix()
                ),
                paths,
            )
        )
    print(f"Uploaded {len(results)} result files to s3://{CONFIG['bucket']}/results/variant8/")
    return results


if __name__ == "__main__":
    setup()
