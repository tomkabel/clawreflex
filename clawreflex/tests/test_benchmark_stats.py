import unittest

from clawreflex.benchmark_stats import percentile, summarize_paired


def receipts(mode="replay", count=30):
    return [dict(provider=provider, pair_id=str(pair), request_sha256=f"task-{pair}",
                 mode=mode, success=True, wall_ms=wall, queue_ms=20)
            for pair in range(count)
            for provider, wall in (("cerebras", 1500), ("gpu-a", 6000), ("gpu-b", 9000))]


class BenchmarkStatisticsTests(unittest.TestCase):
    def test_replay_never_satisfies_live_gate(self):
        result = summarize_paired(receipts(), 100)
        self.assertFalse(result["passed"])
        self.assertEqual(result["complete_pairs"], 30)
        self.assertEqual(result["comparisons_to_cerebras"]["gpu-a"]["median_wall_speedup"], 4)
        self.assertEqual(result["comparisons_to_cerebras"]["gpu-b"]["paired_bootstrap_95pct_ci"], [6, 6])

    def test_failures_missing_pairs_and_small_samples_block_pass(self):
        data = receipts("live", 29)
        self.assertFalse(summarize_paired(data, 100)["passed"])
        data = receipts("live")
        data[0]["success"] = False
        self.assertFalse(summarize_paired(data, 100)["gates"]["all_runs_successful"])
        data.pop()
        self.assertFalse(summarize_paired(data, 100)["gates"]["no_incomplete_pairs"])

    def test_mismatched_requests_duplicate_or_invalid_timing_rejected(self):
        for key, value in (("request_sha256", "different"), ("queue_ms", 999999), ("wall_ms", float("inf"))):
            data = receipts()
            data[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                summarize_paired(data, 100)
        with self.assertRaises(ValueError):
            summarize_paired(receipts() + receipts()[:1], 100)

    def test_queue_is_separate_and_wall_target_still_measured(self):
        data = receipts("live")
        data[0].update(wall_ms=12000, queue_ms=11000)
        result = summarize_paired(data, 100)
        self.assertEqual(result["providers"]["cerebras"]["queue_p95_ms"], 20)
        self.assertEqual(result["providers"]["cerebras"]["nonqueue_p50_ms"], 1480)
        self.assertIsNone(percentile([], .95))
        self.assertEqual(percentile([1, 2, 3], .95), 3)

    def test_no_evidence_cannot_pass(self):
        self.assertFalse(summarize_paired([], 100)["passed"])


if __name__ == "__main__":
    unittest.main()
