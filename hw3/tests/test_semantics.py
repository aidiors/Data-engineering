"""Independent tiny oracles for combinations, selection and salary policy."""

import duckdb
import pytest

from frontend_lake.analytics import canonical_skills, salary
from frontend_lake.common import CONFIG, ROOT, selected, skills
from frontend_lake.validation import ValidationError, compare


@pytest.mark.parametrize(
    "title,role,expected",
    [
        ("Frontend developer", "Программист, разработчик", True),
        ("Senior FRONT-END разработчик", "Программист, разработчик", True),
        ("Фронтенд-разработчик", "Программист, разработчик", True),
        ("Фронтэнд разработчик", "Программист, разработчик", True),
        ("FrontEnd/FullStack Developer", "Программист, разработчик", True),
        ("Backend developer", "Программист, разработчик", False),
        ("Frontend recruiter", "Менеджер по персоналу", False),
        ("myfrontendword", "Программист, разработчик", False),
        ("React developer", "Программист, разработчик", False),
    ],
)
def test_filter_independent_sql(title, role, expected):
    row = {"name": title, "role": role}
    assert selected(row) == expected
    with duckdb.connect(config={"threads": 1}) as con:
        con.execute(
            (ROOT / "sql/source.sql")
            .read_text(encoding="utf-8")
            .split("CREATE TEMP TABLE source")[0]
        )
        assert (
            con.execute(
                "SELECT strip_whitespace(?) = ? AND regexp_matches(lower(?), ?)",
                [role, CONFIG["role"], title, CONFIG["title_regex"]],
            ).fetchone()[0]
            == expected
        )


def test_counts_sql_oracle():
    con = duckdb.connect()
    con.execute("CREATE TABLE expanded(rid INTEGER, skill VARCHAR, pos INTEGER)")
    # Two rows: dedup case variants + empty token; and one repeated pair.
    for rid, text in enumerate([" B; a;A;; c ", "a;b", ""]):
        for pos, skill in enumerate(skills(text), 1):
            con.execute("INSERT INTO expanded VALUES (?,?,?)", [rid, skill, pos])
    got = {
        (k, tuple(s)): n
        for k, s, n in con.execute((ROOT / "sql/counts.sql").read_text(encoding="utf-8")).fetchall()
    }
    expected = {
        (1, ("a",)): 2,
        (1, ("b",)): 2,
        (1, ("c",)): 1,
        (2, ("a", "b")): 2,
        (2, ("a", "c")): 1,
        (2, ("b", "c")): 1,
        (3, ("a", "b", "c")): 1,
    }
    assert got == expected
    assert skills("c; A;a;b", 2) == ["a", "b"]


def test_salary_units_and_open_ranges():
    base = {"currency": "RUR", "gross": "false", "salary_from": "100000", "salary_to": "200000"}
    assert salary(base) == 150000
    assert salary(dict(base, salary_to="")) == 100000
    assert salary(dict(base, salary_from="")) == 200000
    for changes in (
        {"currency": "USD"},
        {"gross": "true"},
        {"salary_from": "300000"},
        {"salary_from": "-1"},
        {"salary_from": "NaN"},
    ):
        assert salary(dict(base, **changes)) is None


def test_exact_verification_rejects_same_totals_different_skills():
    a = {"records": [{"k": 1, "skills": ["a"], "frequency": 2}]}
    b = {"records": [{"k": 1, "skills": ["b"], "frequency": 2}]}
    with pytest.raises(ValidationError):
        compare(a, b)


def test_streaming_mapreduce_multiline_utf8_and_chunk_boundaries(monkeypatch):
    import csv
    import io

    from botocore.response import StreamingBody

    from frontend_lake import mapreduce

    text = io.StringIO(newline="")
    writer = csv.DictWriter(
        text, fieldnames=["source", "vacancy_id", "role", "name", "key_skills", "description"]
    )
    writer.writeheader()
    for i, (name, stack) in enumerate(
        [
            ("Frontend developer", "БЭМ; Git;git;HTML"),
            ("Frontend", "git;HTML"),
            ("Backend", "python"),
            ("Фронтенд", ""),
        ]
    ):
        writer.writerow(
            {
                "source": "hh",
                "vacancy_id": str(i),
                "role": CONFIG["role"],
                "name": name,
                "key_skills": stack,
                "description": 'строка 1\nстрока 2, "кавычки"',
            }
        )
    data = text.getvalue().encode("utf-8")

    class FakeS3:
        def get_object(self, **kwargs):
            return {"Body": StreamingBody(io.BytesIO(data), len(data))}

    monkeypatch.setattr(mapreduce, "client", lambda: FakeS3())
    monkeypatch.setitem(CONFIG, "chunk_rows", 1)
    monkeypatch.setitem(CONFIG, "read_buffer_bytes", 8)
    result = mapreduce.run(0)
    assert result["source_rows"] == 4 and result["selected_rows"] == 3 and result["chunks"] == 4
    assert result["sum_frequencies"] == [5, 4, 1]
    assert result["unique_combinations"] == [3, 3, 1]


def test_salary_alias_sensitivity_does_not_count_react_twice():
    assert canonical_skills(["react", "react.js", "reactjs", "typescript"]) == [
        "react",
        "typescript",
    ]
    assert canonical_skills(["angular", "angularjs", "angular.js"]) == ["angular", "angularjs"]
