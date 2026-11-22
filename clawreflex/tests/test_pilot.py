import hashlib
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from clawreflex.pilot import main, summarize, validate_event


def event(kind="repair", day=1, participant=1, **extra):
    record = {
        "event": kind, "participant": hashlib.sha256(str(participant).encode()).hexdigest(),
        "consent": True, "success": True, "timestamp": f"2026-11-{day:02d}T00:00:00+00:00",
    }
    if kind == "repair":
        record.update(accepted=True, false_apply=False, latency_ms=1500)
    record.update(extra)
    return record


class PilotTests(unittest.TestCase):
    def test_no_records_cannot_pass(self):
        self.assertFalse(summarize([])["passed"])
        self.assertIsNone(summarize([])["p95_latency_ms"])

    def test_complete_metrics_still_require_external_signoff(self):
        records = [event(kind, day, person) for kind in ("install", "repair", "session")
                   for person in range(5) for day in (1, 15)]
        summary = summarize(records)
        self.assertFalse(summary["passed"])
        self.assertEqual(summary["participants"], 5)
        self.assertEqual(summary["observed_days"], 14)
        self.assertTrue(summarize(records, security_signoff=True)["passed"])

    def test_false_apply_and_p95_fail_gates(self):
        result = summarize([event(false_apply=True, latency_ms=9000)])
        self.assertFalse(result["gates"]["zero_false_applies"])
        self.assertFalse(result["gates"]["p95_at_most_5000ms"])

    def test_reject_private_data_missing_consent_and_invalid_values(self):
        for bad in (event(source="private"), event(consent=False), dict(event(), participant="email@example.org"),
                    event(latency_ms=float("nan")), event(latency_ms=-1), event(success=1),
                    event(timestamp="2026-11-01"), event(accepted="yes")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_event(bad)

    def test_missing_repair_metrics_rejected(self):
        record = event()
        del record["latency_ms"]
        with self.assertRaises(ValueError):
            validate_event(record)

    def test_invalid_identity_event_and_timestamp_rejected(self):
        for bad in (dict(event(), participant="z" * 64), event(event="unknown"), event(timestamp="invalid")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_event(bad)

    def test_cli_records_input_hash_and_does_not_certify_empty_pilot(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "events.jsonl"
            output = Path(tmp) / "summary.json"
            raw = (json.dumps(event()) + "\n").encode()
            source.write_bytes(raw)
            with mock.patch("sys.argv", ["pilot", str(source), "--output", str(output)]), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 1)
            result = json.loads(output.read_text())
            self.assertFalse(result["passed"])
            self.assertEqual(result["input_sha256"], hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    unittest.main()
