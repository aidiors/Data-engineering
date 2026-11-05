import csv
from collections import Counter
from itertools import combinations

from .calculation import prepare
from .zk_common import ROOT, save


def create_fixture():
    directory = ROOT / '.runtime/selftest'
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / 'synthetic.csv'
    expected = [Counter(), Counter(), Counter()]
    ids = []
    with source.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['source', 'vacancy_id', 'role', 'name', 'key_skills'])
        writer.writeheader()
        for index in range(2400):
            selected = index % 4 != 0
            stack = sorted({'css', 'javascript', 'react', 'typescript', f'skill{index % 11}'})
            writer.writerow({'source': 'synthetic-self-test', 'vacancy_id': str(index),
                             'role': 'Программист, разработчик',
                             'name': 'Frontend developer' if selected else 'Backend developer',
                             'key_skills': ';'.join(stack)})
            if selected:
                ids.append(['synthetic-self-test', str(index)])
                for k in (1, 2, 3):
                    expected[k - 1].update(combinations(stack[:5], k))
    provenance = prepare(source, directory / 'frontend.jsonl')
    provenance['dataset_kind'] = 'synthetic-self-test'
    save(directory / 'provenance.json', provenance)
    save(directory / 'reference.json', {
        'source_rows': 2400, 'selected_rows': len(ids), 'selected_ids': sorted(ids),
        'sum_frequencies': [sum(c.values()) for c in expected],
        'unique_combinations': [len(c) for c in expected],
        'records': [{'k': k, 'skills': list(combo), 'frequency': count}
                    for k, counts in enumerate(expected, 1)
                    for combo, count in sorted(counts.items())]})
    return directory
