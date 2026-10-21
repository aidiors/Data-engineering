"""Regression tests for the issues found in the pre-publication review."""

import importlib
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from frontend_lake.analytics import rank_associations, salary_associations
from frontend_lake.common import CONFIG, ROOT, skills
from frontend_lake.validation import ValidationError, canonical


def test_sql_matches_python_unicode_whitespace():
    whitespace = [chr(point) for point in range(0x3100) if chr(point).isspace()]
    with duckdb.connect(config={"threads": 1}) as con:
        con.execute("""CREATE TABLE fixture_raw (
            source VARCHAR, vacancy_id VARCHAR, name VARCHAR, role VARCHAR, area VARCHAR,
            key_skills VARCHAR, salary_from VARCHAR, salary_to VARCHAR, currency VARCHAR,
            gross VARCHAR, experience VARCHAR)""")
        for index, char in enumerate(whitespace):
            con.execute(
                "INSERT INTO fixture_raw VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    "hh",
                    str(index),
                    "Frontend",
                    char + CONFIG["role"] + char,
                    "Москва",
                    char + "Git" + char + "; HTML",
                    "",
                    "",
                    "",
                    "",
                    "",
                ],
            )
        con.execute(
            (ROOT / "sql/source.sql")
            .read_text(encoding="utf-8")
            .format(reader="fixture_raw", cap=0)
        )
        rows = con.execute("SELECT skills_all FROM frontend").fetchall()
    assert len(rows) == len(whitespace)
    assert all(stack == ["git", "html"] for (stack,) in rows)


def test_runtime_verification_survives_python_optimization():
    code = """from frontend_lake.validation import compare
compare({'records':[{'k':1,'skills':['a'],'frequency':1}]},
        {'records':[{'k':1,'skills':['wrong'],'frequency':999}]})"""
    result = subprocess.run(
        [sys.executable, "-O", "-c", code], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "Combination mismatch" in result.stderr


def test_duplicate_combination_keys_are_rejected():
    record = {"k": 1, "skills": ["a"], "frequency": 1}
    with pytest.raises(ValidationError, match="Duplicate"):
        canonical({"records": [record, record]})


@pytest.mark.parametrize("cap", [-1, -10])
def test_negative_stack_sizes_are_rejected(cap):
    with pytest.raises(ValidationError, match="nonnegative"):
        skills("a;b;c", cap)


def test_importing_cli_scripts_does_not_execute_work(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Importing a CLI script must not execute its workflow")

    monkeypatch.setattr(Path, "write_text", unexpected)
    monkeypatch.setattr(Path, "mkdir", unexpected)
    monkeypatch.setattr(subprocess, "run", unexpected)
    monkeypatch.setattr("frontend_lake.storage.client", unexpected)
    for name in ("init_env", "publish_results", "render_pdf", "evidence", "check_submission"):
        importlib.import_module("scripts." + name)


def test_salary_associations_and_aliases_use_the_same_population(monkeypatch):
    monkeypatch.setitem(CONFIG, "salary_min_support", 2)
    monkeypatch.setitem(CONFIG, "salary_min_complement", 2)
    paid = [
        {"skills_all": ["react", "react.js", "typescript"], "salary_value": 100},
        {"skills_all": ["react", "react.js", "typescript"], "salary_value": 200},
        {"skills_all": ["html"], "salary_value": 50},
        {"skills_all": ["html"], "salary_value": 60},
    ]
    raw, _ = salary_associations(paid)
    merged, _ = salary_associations(paid, normalize_aliases=True)
    triple = next(row for row in raw if row["k"] == 3)
    assert (triple["median_with"], triple["median_without"], triple["delta_rub"]) == (150, 55, 95)
    assert not any(row["k"] == 3 for row in merged)
    top = rank_associations(merged)["2_higher"][0]
    assert top["skills"] == "react + typescript"
    assert (top["median_with"], top["median_without"], top["support_paid"]) == (150, 55, 2)


def test_region_queries_accept_configured_names():
    with duckdb.connect(config={"threads": 1}) as con:
        con.execute(
            "CREATE TABLE frontend AS SELECT 'hh' AS source,'1' AS vacancy_id,'Регион A' AS area,['git'] AS skills_all"
        )
        con.execute(
            "CREATE TABLE salary_values AS SELECT 'hh' AS source,'1' AS vacancy_id,100000.0 AS salary_value"
        )
        queries = con.extract_statements((ROOT / "sql/regions.sql").read_text(encoding="utf-8"))
        assert con.execute(queries[0], [["Регион A"]]).fetchone()[:4] == (
            "Регион A",
            1,
            1,
            100000,
        )
        assert con.execute(queries[1], [["Регион A"]]).fetchall() == [("Регион A", "git", 1, 100.0)]
