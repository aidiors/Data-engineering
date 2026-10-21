"""Salary associations and regional analysis for the Frontend segment."""

import json
import math
from collections import Counter, defaultdict
from itertools import combinations
from statistics import median

from .common import CONFIG, ROOT, TITLE, dump, write_csv
from .duck import connection, load, quote, source_reader
from .storage import upload_file
from .validation import require

ALIASES = {
    "react.js": "react",
    "reactjs": "react",
    "vue.js": "vue",
    "vuejs": "vue",
    "angular.js": "angularjs",
}


def canonical_skills(values):
    return sorted({ALIASES.get(skill, skill) for skill in values})


def salary(row):
    """Comparable net RUB estimate, or None for missing/invalid salary data."""
    if row["currency"] != "RUR" or row["gross"] != "false":
        return None
    try:
        lower = float(row["salary_from"]) if row["salary_from"] else None
        upper = float(row["salary_to"]) if row["salary_to"] else None
    except (ValueError, TypeError):
        return None
    for bound in (lower, upper):
        if bound is not None and (not math.isfinite(bound) or bound <= 0):
            return None
    if lower is not None and upper is not None:
        return (lower + upper) / 2 if lower <= upper else None
    return lower if lower is not None else upper


def salary_associations(paid, *, normalize_aliases=False, lengths=(1, 2, 3)):
    """Pure calculation, shared by raw-label and alias-sensitivity reports."""
    require(bool(paid), "No comparable net RUB salaries in the selected segment")
    groups = defaultdict(list)
    for index, row in enumerate(paid):
        stack = canonical_skills(row["skills_all"]) if normalize_aliases else row["skills_all"]
        for size in lengths:
            for combo in combinations(stack, size):
                groups[size, combo].append(index)
    all_ids = set(range(len(paid)))
    baseline = median(row["salary_value"] for row in paid)
    records = []
    for (size, combo), indices in groups.items():
        if len(indices) < CONFIG["salary_min_support"]:
            continue
        others = all_ids.difference(indices)
        if len(others) < CONFIG["salary_min_complement"]:
            continue
        present = median(paid[index]["salary_value"] for index in indices)
        absent = median(paid[index]["salary_value"] for index in others)
        records.append(
            {
                "k": size,
                "skills": " + ".join(combo),
                "support_paid": len(indices),
                "support_without": len(others),
                "median_with": present,
                "median_without": absent,
                "delta_rub": present - absent,
                "delta_pct": (present / absent - 1) * 100,
                "delta_vs_overall_rub": present - baseline,
            }
        )
    records.sort(key=lambda row: (row["k"], -row["delta_rub"], -row["support_paid"], row["skills"]))
    return records, groups


def rank_associations(records, lengths=(1, 2, 3)):
    extremes = {}
    for size in lengths:
        subset = [row for row in records if row["k"] == size]
        extremes[f"{size}_higher"] = sorted(
            [row for row in subset if row["delta_rub"] > 0],
            key=lambda row: (-row["delta_rub"], -row["support_paid"], row["skills"]),
        )[:8]
        extremes[f"{size}_lower"] = sorted(
            [row for row in subset if row["delta_rub"] < 0],
            key=lambda row: (row["delta_rub"], -row["support_paid"], row["skills"]),
        )[:8]
    return extremes


def region_tables(rows, paid):
    regions, demand = [], []
    for region in CONFIG["regions"]:
        selected_rows = [row for row in rows if row["area"] == region]
        selected_paid = [row for row in paid if row["area"] == region]
        require(bool(selected_rows), f"No Frontend vacancies in region {region}")
        total = len(selected_rows)
        regions.append(
            {
                "region": region,
                "vacancies": total,
                "share_pct": 100 * total / len(rows),
                "paid_rur_net": len(selected_paid),
                "salary_coverage_pct": 100 * len(selected_paid) / total,
                "median_rur_net": median(row["salary_value"] for row in selected_paid)
                if selected_paid
                else None,
                "mean_skills": sum(len(row["skills_all"]) for row in selected_rows) / total,
                "experience": dict(Counter(row["experience"] for row in selected_rows)),
            }
        )
        frequencies = Counter(skill for row in selected_rows for skill in row["skills_all"])
        for skill, count in sorted(frequencies.items(), key=lambda item: (-item[1], item[0]))[:15]:
            demand.append(
                {
                    "region": region,
                    "skill": skill,
                    "vacancies": count,
                    "demand_pct": 100 * count / total,
                }
            )
    return regions, demand


def verify_analytics(paid, regions, demand, extremes, groups):
    """Independent SQL checks, using the same configured regional list."""
    checks = []
    with connection() as con:
        load(con, parquet=True)
        con.execute((ROOT / "sql/salaries.sql").read_text(encoding="utf-8"))
        count, overall = con.execute(
            "SELECT count(*),median(salary_value) FROM salary_values"
        ).fetchone()
        require(
            count == len(paid) and overall == median(row["salary_value"] for row in paid),
            "SQL and Python salary populations differ",
        )
        queries = con.extract_statements((ROOT / "sql/regions.sql").read_text(encoding="utf-8"))
        sql_regions = con.execute(queries[0], [CONFIG["regions"]]).fetchall()
        require(len(sql_regions) == len(regions), "SQL and Python region sets differ")
        for region, count, paid_count, salary_median, mean_skills in sql_regions:
            row = next(row for row in regions if row["region"] == region)
            require(
                (count, paid_count, salary_median)
                == (row["vacancies"], row["paid_rur_net"], row["median_rur_net"]),
                f"Regional salary mismatch: {region}",
            )
            require(
                abs(mean_skills - row["mean_skills"]) < 1e-10,
                f"Mean skill count mismatch: {region}",
            )
        sql_demand = con.execute(queries[1], [CONFIG["regions"]]).fetchall()
        require(
            sorted(
                (row["region"], row["skill"], row["vacancies"], row["demand_pct"]) for row in demand
            )
            == sorted(sql_demand),
            "Regional skill-demand tables differ",
        )
        checked = set()
        for ranking in extremes.values():
            for row in ranking:
                combo = next(
                    combo
                    for size, combo in groups
                    if size == row["k"] and " + ".join(combo) == row["skills"]
                )
                if combo in checked:
                    continue
                checked.add(combo)
                condition = "list_has_all(skills_all, [" + ",".join(quote(s) for s in combo) + "])"
                actual = con.execute(f"""SELECT
                  count(*) FILTER (WHERE {condition}),median(salary_value) FILTER (WHERE {condition}),
                  count(*) FILTER (WHERE NOT {condition}),median(salary_value) FILTER (WHERE NOT {condition})
                  FROM salary_values""").fetchone()
                require(
                    actual
                    == (
                        row["support_paid"],
                        row["median_with"],
                        row["support_without"],
                        row["median_without"],
                    ),
                    f"Salary association mismatch: {combo}",
                )
                checks.append({"skills": list(combo), "equal": True})
    return {
        "regions_equal": True,
        "skill_demand_equal": True,
        "salary_extremes_checked": checks,
        "salary_overall_equal": True,
    }


def read_frontend():
    with connection() as con:
        load(con)
        cursor = con.execute("SELECT * FROM frontend")
        fields = [column[0] for column in cursor.description]
        rows = [dict(zip(fields, row, strict=True)) for row in cursor.fetchall()]
        source = con.execute(
            """SELECT count(*),count(DISTINCT (source,vacancy_id)),
              min(published_at),max(published_at) FROM """
            + source_reader()
        ).fetchone()
    require(bool(rows), "The Frontend filter selected no vacancies")
    return rows, {
        "source_rows": source[0],
        "source_unique_ids": source[1],
        "published_min": source[2],
        "published_max": source[3],
    }


def audit_rows(rows, paid, associations):
    closed = [row for row in paid if row["salary_from"] and row["salary_to"]]
    return {
        "frontend_rows": len(rows),
        "frontend_unique_ids": len({(r["source"], r["vacancy_id"]) for r in rows}),
        "no_skills": sum(not row["skills_all"] for row in rows),
        "currency_gross": dict(
            Counter(f"{r['currency'] or 'missing'} / {r['gross'] or 'missing'}" for r in rows)
        ),
        "paid_rur_net": len(paid),
        "salary_median": median(r["salary_value"] for r in paid),
        "closed_ranges_count": len(closed),
        "closed_ranges_median": median(r["salary_value"] for r in closed) if closed else None,
        "open_lower_only": sum(bool(r["salary_from"]) and not r["salary_to"] for r in paid),
        "open_upper_only": sum(bool(r["salary_to"]) and not r["salary_from"] for r in paid),
        "eligible_associations": dict(Counter(row["k"] for row in associations)),
        "max_skills": max(len(row["skills_all"]) for row in rows),
        "skill_count_histogram": dict(
            sorted(Counter(len(row["skills_all"]) for row in rows).items())
        ),
    }


def audit_json_archive():
    paths = sorted((ROOT / "hh").glob("*.json"))
    selected_count = 0
    for path in paths:
        row = json.loads(path.read_text(encoding="utf-8"))
        roles = [role["name"] for role in row.get("professional_roles", [])]
        selected_count += CONFIG["role"] in roles and bool(
            TITLE.search(row.get("name", "").lower())
        )
    return {"raw_json_count": len(paths), "raw_json_frontend": selected_count}


def main():
    rows, audit = read_frontend()
    selected_path = ROOT / "output/selected_frontend.csv"
    write_csv(
        selected_path,
        ({**row, "skills_all": json.dumps(row["skills_all"], ensure_ascii=False)} for row in rows),
    )
    paid = []
    for row in rows:
        estimate = salary(row)
        if estimate is not None:
            paid.append(dict(row, salary_value=estimate))
    associations, groups = salary_associations(paid)
    extremes = rank_associations(associations)
    canonical_records, _ = salary_associations(paid, normalize_aliases=True, lengths=(2, 3))
    regions, demand = region_tables(rows, paid)
    dump(
        ROOT / "output/analytics_verification.json",
        verify_analytics(paid, regions, demand, extremes, groups),
    )
    audit.update(audit_rows(rows, paid, associations))
    audit.update(audit_json_archive())
    audit["frontend_object"] = upload_file(selected_path, "prepared/frontend_variant8.csv")
    for name, value in [
        ("audit", audit),
        ("salary_extremes", extremes),
        ("regions", regions),
        ("salary_extremes_canonical", rank_associations(canonical_records, (2, 3))),
        ("skill_aliases", ALIASES),
    ]:
        dump(ROOT / f"output/{name}.json", value)
    write_csv(ROOT / "output/salary_associations.csv", associations)
    write_csv(ROOT / "output/salary_associations_canonical.csv", canonical_records)
    write_csv(
        ROOT / "output/region_summary.csv",
        ({k: v for k, v in row.items() if k != "experience"} for row in regions),
    )
    write_csv(ROOT / "output/region_skills.csv", demand)
    print(json.dumps(audit, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
