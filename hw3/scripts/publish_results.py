"""Copy local result artifacts to the local RustFS bucket; no GitHub publishing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frontend_lake.common import CONFIG, ROOT, dump
from frontend_lake.storage import publish_results, upload_file


def main():
    records = publish_results()
    path = ROOT / "output/publication.json"
    dump(path, {"bucket": CONFIG["bucket"], "objects": records})
    upload_file(path, "results/variant8/publication.json")


if __name__ == "__main__":
    main()
