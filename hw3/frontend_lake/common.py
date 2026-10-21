import csv
import json
import re
import sys
from itertools import chain
from pathlib import Path

from .validation import require

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
TITLE = re.compile(CONFIG["title_regex"])
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def selected(row):
    return row["role"].strip() == CONFIG["role"] and bool(TITLE.search(row["name"].lower()))


def skills(text, cap=0):
    validate_cap(cap)
    values = sorted({s.strip().lower() for s in text.split(";") if s.strip()})
    return values[:cap] if cap else values


def validate_cap(cap):
    require(isinstance(cap, int) and cap >= 0, "Stack size must be a nonnegative integer (0 = all)")


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path, rows, fields=None):
    iterator = iter(rows)
    first = next(iterator, None)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(first) if first is not None else [])
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        if first is not None:
            writer.writerows(chain([first], iterator))
