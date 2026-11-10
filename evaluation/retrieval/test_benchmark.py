"""Known-rank checks prevent inflated recall and incorrectly fused rankings."""

import unittest

from .benchmark import rank_metrics, rrf


class MetricTests(unittest.TestCase):
    def test_known_rank_and_duplicate_fragment_does_not_double_count(self):
        value = rank_metrics(["noise", "a", "a", "b"], {"a": 1, "b": 1, "c": 1}, 3)
        self.assertAlmostEqual(value["recall@3"], 2 / 3)
        self.assertEqual(value["mrr@3"], 0.5)
        self.assertEqual(value["hit@3"], 1)
        self.assertLessEqual(value["ndcg@3"], 1)

    def test_empty_relevance_is_not_silently_perfect(self):
        with self.assertRaises(ValueError):
            rank_metrics(["a"], {}, 10)

    def test_rrf_agreement_and_deterministic_tie(self):
        self.assertEqual(rrf([["a", "b"], ["b", "a"]]), ["a", "b"])
        self.assertEqual(rrf([["a", "b", "c"], ["c", "b", "a"]])[0], "a")


if __name__ == "__main__":
    unittest.main()
