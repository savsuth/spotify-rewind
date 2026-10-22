"""Algorithm checks against the unpruned reference and known histories."""
import unittest

import numpy as np

from rewind import eras


class EraTests(unittest.TestCase):
    def test_pelt_matches_exact_partition_on_300_random_histories(self):
        rng = np.random.default_rng(20261018)
        for case in range(300):
            n = int(rng.integers(8, 70))
            minimum = int(rng.integers(2, 7))
            x = rng.normal(size=(n, int(rng.integers(1, 8))))
            x[n // 2:] += rng.uniform(0, 3)
            penalty = float(rng.uniform(.1, 15))
            with self.subTest(case=case, n=n, minimum=minimum):
                result = eras.pelt(x, penalty, minimum)
                self.assertEqual(result, eras.optimal_partition(x, penalty, minimum))
                self.assertTrue(all(b - a >= minimum for a, b in zip([0] + result, result)))

    def test_known_change_and_constant_history(self):
        x = np.vstack([np.zeros((12, 2)), np.ones((12, 2)) * 4])
        self.assertEqual(eras.pelt(x, 1), [12, 24])
        self.assertEqual(eras.pelt(np.ones((24, 2)), 1), [24])
        self.assertEqual(eras.pelt(np.ones((2, 2)), 1), [2])

    def test_l2_cost_matches_direct_squared_error(self):
        x = np.random.default_rng(42).normal(size=(20, 4))
        cost = eras.L2Cost(x)
        for start, end in [(0, 20), (3, 8), (7, 19)]:
            direct = ((x[start:end] - x[start:end].mean(axis=0)) ** 2).sum()
            self.assertAlmostEqual(cost(start, end), direct)

    def test_boundary_contributions_sum_to_one(self):
        minutes = np.array([[90, 10], [80, 20], [85, 15], [10, 90], [20, 80], [15, 85]])
        space = eras.MonthlySpace([f'2024-{i:02d}' for i in range(1, 7)], ['a', 'b'],
                                 {'a': 'Alpha', 'b': 'Beta'}, minutes,
                                 minutes.sum(axis=1), np.ones(6), np.ones(6, dtype=bool))
        result = eras.EraResult(4, 1, .25, 3, space.months, [3], [(0, 3), (3, 6)])
        explanation = eras.explain_boundary(space, result, 1)
        self.assertEqual(explanation['boundary_month'], '2024-04')
        self.assertAlmostEqual(sum(x['contribution'] for x in explanation['top_contributors']), 1)
        self.assertEqual(explanation['top8_contribution'], 1)
        self.assertEqual(explanation['rose'][0]['id'], 'b')
        self.assertEqual(explanation['declined'][0]['id'], 'a')

    def test_zero_month_share_is_finite(self):
        space = eras.MonthlySpace(['2024-01'], ['a'], {'a': 'Alpha'}, np.zeros((1, 1)),
                                 np.zeros(1), np.ones(1), np.zeros(1, dtype=bool))
        np.testing.assert_array_equal(space.shares, [[0]])
        self.assertTrue(np.isfinite(space.embedded).all())

    def test_dropping_boundary_merges_adjacent_segments(self):
        result = eras.EraResult(4, 1, .25, 3, list(range(12)), [3, 6, 9],
                               [(0, 3), (3, 6), (6, 9), (9, 12)])
        merged = eras.keep_boundaries(result, [3, 9])
        self.assertEqual(merged.boundaries, [3, 9])
        self.assertEqual(merged.segments, [(0, 3), (3, 9), (9, 12)])
