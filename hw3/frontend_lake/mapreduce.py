"""Read an S3 object in buffered chunks, map combinations, combine, reduce.

No DuckDB, pandas, full-file download or read-all is used in this implementation.
CSV records (including quoted line breaks) are parsed before row chunking.
"""

import csv
import io
import math
from collections import Counter
from itertools import combinations, islice

from .common import CONFIG, selected, skills, validate_cap
from .storage import client
from .validation import require


def run(cap):
    validate_cap(cap)
    response = client().get_object(Bucket=CONFIG["bucket"], Key=CONFIG["raw_key"])
    totals = [Counter() for _ in range(3)]
    nrows = matches = chunks = 0
    expected = [0, 0, 0]
    selected_ids = []
    with io.TextIOWrapper(
        io.BufferedReader(response["Body"], CONFIG["read_buffer_bytes"]),
        encoding="utf-8-sig",
        newline="",
    ) as stream:
        reader = csv.DictReader(stream)
        while chunk := list(islice(reader, CONFIG["chunk_rows"])):
            chunks += 1
            nrows += len(chunk)
            local = [Counter() for _ in range(3)]
            # Own map + local combiner; baseline materializes mapper output per chunk.
            emissions = []
            for row in chunk:
                if not selected(row):
                    continue
                matches += 1
                selected_ids.append((row["source"], row["vacancy_id"]))
                stack = skills(row["key_skills"], cap)
                for k in (1, 2, 3):
                    expected[k - 1] += math.comb(len(stack), k) if len(stack) >= k else 0
                    emissions.extend((k, combo) for combo in combinations(stack, k))
            for k, combo in emissions:
                local[k - 1][combo] += 1
            for i in range(3):
                totals[i].update(local[i])  # reduce partial maps, never concatenate all input
    records = [
        {"k": k, "skills": list(combo), "frequency": count}
        for k, counter in enumerate(totals, 1)
        for combo, count in sorted(counter.items())
    ]
    sums = [sum(c.values()) for c in totals]
    require(sums == expected, "Validation failed: sums == expected")
    return {
        "method": "mr",
        "cap": cap,
        "source_rows": nrows,
        "selected_rows": matches,
        "chunks": chunks,
        "sum_frequencies": sums,
        "unique_combinations": [len(c) for c in totals],
        "records": records,
        "selected_ids": sorted(selected_ids),
    }
