from urllib.parse import urlsplit

import duckdb

from .common import CONFIG, ROOT, validate_cap
from .storage import credentials
from .validation import require


def quote(text):
    return "'" + text.replace("'", "''") + "'"


def connection():
    con = duckdb.connect()
    con.execute(f"SET threads={int(CONFIG['duckdb_threads'])}")
    con.execute("SET memory_limit=" + quote(CONFIG["duckdb_memory_limit"]))
    con.execute("INSTALL httpfs; LOAD httpfs;")
    key, secret = credentials()
    endpoint = urlsplit(CONFIG["endpoint"])
    con.execute(f"""CREATE SECRET lake (
        TYPE s3, KEY_ID {quote(key)}, SECRET {quote(secret)}, REGION 'us-east-1',
        ENDPOINT {quote(endpoint.netloc)}, URL_STYLE 'path', USE_SSL {str(endpoint.scheme == "https").lower()}
    )""")
    return con


def source_reader(parquet=False):
    key = CONFIG["parquet_key"] if parquet else CONFIG["raw_key"]
    path = quote(f"s3://{CONFIG['bucket']}/{key}")
    if parquet:
        return f"read_parquet({path})"
    return f"read_csv({path}, header=true, all_varchar=true, delim=',', quote='\"', escape='\"', max_line_size=16777216)"


def load(con, cap=0, parquet=False):
    validate_cap(cap)
    template = (ROOT / "sql/source.sql").read_text(encoding="utf-8")
    con.execute(template.format(reader=source_reader(parquet), cap=int(cap)))


def run(cap, parquet=False):
    with connection() as con:
        load(con, cap, parquet)
        records = [
            {"k": k, "skills": s, "frequency": f}
            for k, s, f in con.execute(
                (ROOT / "sql/counts.sql").read_text(encoding="utf-8")
            ).fetchall()
        ]
        expected = con.execute("""SELECT coalesce(sum(len(skills)),0),
          coalesce(sum(len(skills)*(len(skills)-1)//2),0),
          coalesce(sum(len(skills)*(len(skills)-1)*(len(skills)-2)//6),0) FROM stacks""").fetchone()
        sums = [sum(r["frequency"] for r in records if r["k"] == k) for k in (1, 2, 3)]
        require(list(expected) == sums, "Validation failed: list(expected) == sums")
        return {
            "method": "duck_parquet" if parquet else "duck_csv",
            "cap": cap,
            "source_rows": con.execute("SELECT count(*) FROM source").fetchone()[0],
            "selected_rows": con.execute("SELECT count(*) FROM frontend").fetchone()[0],
            "sum_frequencies": sums,
            "unique_combinations": [sum(r["k"] == k for r in records) for k in (1, 2, 3)],
            "records": records,
            "selected_ids": [
                list(x)
                for x in con.execute(
                    "SELECT source,vacancy_id FROM frontend ORDER BY source,vacancy_id"
                ).fetchall()
            ],
        }


def prepare():
    import time

    from .storage import upload_file

    started = time.perf_counter()
    path = ROOT / "tmp" / "vacancies.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    with connection() as con:
        con.execute(f"""COPY (SELECT source,vacancy_id,name,role,area,key_skills,
          salary_from,salary_to,currency,gross,experience FROM {source_reader()})
          TO {quote(path.as_posix())} (FORMAT PARQUET, COMPRESSION ZSTD)""")
    result = upload_file(path, CONFIG["parquet_key"])
    result["prepare_seconds"] = time.perf_counter() - started
    return result
