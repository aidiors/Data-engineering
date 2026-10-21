"""Runtime checks that remain active with Python optimization enabled."""

import hashlib
import json


class ValidationError(ValueError):
    """A computed result or stored artifact failed verification."""


def require(condition, message):
    if not condition:
        raise ValidationError(str(message))


def canonical(result):
    records = result["records"]
    counts = {(row["k"], tuple(row["skills"])): row["frequency"] for row in records}
    require(len(counts) == len(records), "Duplicate combination keys in result")
    return counts


def compare(reference, result):
    """Compare every combination and selected ID, then hash the full dictionary."""
    expected, actual = canonical(reference), canonical(result)
    require(
        expected == actual,
        f"Combination mismatch: missing={len(expected.keys() - actual.keys())}, "
        f"extra={len(actual.keys() - expected.keys())}, "
        f"changed={sum(expected[k] != actual[k] for k in expected.keys() & actual.keys())}",
    )
    for field in (
        "source_rows",
        "selected_rows",
        "sum_frequencies",
        "unique_combinations",
        "selected_ids",
    ):
        require(reference[field] == result[field], f"Mismatch in {field}")
    payload = sorted((k, list(skills), count) for (k, skills), count in expected.items())
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
