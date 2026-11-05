import json
import unittest
from collections import Counter
from itertools import combinations

from src.calculation import empty, process, result


class CheckpointTests(unittest.TestCase):
    def test_recovery_does_not_skip_or_duplicate_boundary_rows(self):
        rows = [{'id': ['x', str(i)], 'skills': sorted(set(stack))}
                for i, stack in enumerate([[], ['css'], ['css', 'js'], ['a', 'b', 'c'], ['x', 'y', 'z', 'w']])]
        for cap in (0, 2, 5, 10):
            expected = Counter()
            for row in rows:
                stack = row['skills'][:cap] if cap else row['skills']
                for k in (1, 2, 3):
                    expected.update((k, combo) for combo in combinations(stack, k))
            for boundary in range(len(rows) + 1):
                with self.subTest(cap=cap, boundary=boundary):
                    state = process(empty(), rows[:boundary], cap)
                    restored = json.loads(json.dumps(state))
                    state = process(restored, rows[restored['next_row']:], cap)
                    actual = result(state, cap, len(rows))
                    counts = {(r['k'], tuple(r['skills'])): r['frequency'] for r in actual['records']}
                    self.assertEqual(counts, expected)
                    self.assertEqual(actual['selected_ids'], sorted(r['id'] for r in rows))


if __name__ == '__main__':
    unittest.main()
