import csv
import hashlib
import json
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'hw3'))
from frontend_lake.common import selected, skills


def prepare(csv_path, output):
    source = Path(csv_path)
    with source.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    total = matches = 0
    with source.open(encoding='utf-8-sig', newline='') as stream, output.open('w', encoding='utf-8') as target:
        for row in csv.DictReader(stream):
            total += 1
            if selected(row):
                matches += 1
                target.write(json.dumps({'id': [row['source'], row['vacancy_id']],
                                         'skills': skills(row['key_skills'])}, ensure_ascii=False) + '\n')
    with output.open('rb') as stream:
        prepared_digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'source': str(source), 'source_sha256': digest, 'source_rows': total,
            'selected_rows': matches, 'prepared_sha256': prepared_digest}


def empty():
    return {'next_row': 0, 'counts': [{}, {}, {}], 'selected_ids': []}


def process(state, rows, cap):
    totals = [Counter(c) for c in state['counts']]
    for row in rows:
        stack = row['skills'][:cap] if cap else row['skills']
        for k in (1, 2, 3):
            totals[k - 1].update(json.dumps(combo, ensure_ascii=False) for combo in combinations(stack, k))
        state['selected_ids'].append(row['id'])
    state['next_row'] += len(rows)
    state['counts'] = [dict(c) for c in totals]
    return state


def result(state, cap, source_rows):
    records = [{'k': k, 'skills': json.loads(combo), 'frequency': count}
               for k, counts in enumerate(state['counts'], 1)
               for combo, count in counts.items()]
    records.sort(key=lambda row: (row['k'], row['skills']))
    return {'method': 'mr-zookeeper', 'cap': cap, 'source_rows': source_rows,
            'selected_rows': state['next_row'], 'records': records,
            'sum_frequencies': [sum(c.values()) for c in state['counts']],
            'unique_combinations': [len(c) for c in state['counts']],
            'selected_ids': sorted(state['selected_ids'])}
