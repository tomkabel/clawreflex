"""Local, opt-in pilot metrics. Never collects source, prompts or credentials."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
from typing import Any

EVENTS = {"install", "repair", "session"}


def validate_event(event: dict[str, Any]) -> dict[str, Any]:
    """Reject unexpected fields instead of accidentally recording private content."""
    required = {"participant", "event", "success", "consent", "timestamp"}
    allowed = required | {"accepted", "false_apply", "latency_ms"}
    if set(event) - allowed or not required <= set(event):
        raise ValueError("invalid pilot fields")
    participant = event["participant"]
    if not isinstance(participant, str) or len(participant) != 64:
        raise ValueError("participant must be a pseudonymous SHA-256 digest")
    try:
        int(participant, 16)
        timestamp = dt.datetime.fromisoformat(event["timestamp"])
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid participant or timestamp") from exc
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    if event["event"] not in EVENTS:
        raise ValueError("unknown pilot event")
    if event["consent"] is not True or type(event["success"]) is not bool:
        raise ValueError("explicit consent and boolean success are required")
    for key in ("accepted", "false_apply"):
        if key in event and type(event[key]) is not bool:
            raise ValueError(f"{key} must be boolean")
    if event["event"] == "repair" and not {"accepted", "false_apply", "latency_ms"} <= set(event):
        raise ValueError("repair events require acceptance, false-apply and latency")
    if "latency_ms" in event:
        latency = event["latency_ms"]
        if type(latency) not in (int, float) or not math.isfinite(latency) or latency < 0:
            raise ValueError("latency must be finite and nonnegative")
    return dict(event)


def summarize(events: list[dict[str, Any]], security_signoff: bool = False) -> dict[str, Any]:
    records = [validate_event(event) for event in events]
    participants = {event["participant"] for event in records}
    groups = {kind: [event for event in records if event["event"] == kind] for kind in EVENTS}

    def ratio(kind: str, field: str) -> float | None:
        group = groups[kind]
        return sum(event.get(field) is True for event in group) / len(group) if group else None

    installs = ratio("install", "success")
    acceptance = ratio("repair", "accepted")
    crash_free = ratio("session", "success")
    latencies = sorted(event["latency_ms"] for event in groups["repair"])
    p95 = latencies[max(0, math.ceil(len(latencies) * .95) - 1)] if latencies else None
    false_applies = sum(event.get("false_apply") is True for event in groups["repair"])
    stamps = sorted(dt.datetime.fromisoformat(event["timestamp"]) for event in records)
    days = (stamps[-1] - stamps[0]).total_seconds() / 86400 if stamps else 0
    represented = all(
        {event["participant"] for event in groups[kind]} == participants
        for kind in EVENTS
    )
    gates = {
        "five_to_ten_participants": 5 <= len(participants) <= 10,
        "two_weeks_observed": days >= 14,
        "all_participants_represented": represented and bool(participants),
        "install_success_90pct": installs is not None and installs >= .90,
        "repair_acceptance_70pct": acceptance is not None and acceptance >= .70,
        "zero_false_applies": bool(groups["repair"]) and false_applies == 0,
        "crash_free_99pct": crash_free is not None and crash_free >= .99,
        "p95_at_most_5000ms": p95 is not None and p95 <= 5000,
        "external_security_signoff": security_signoff,
    }
    return {
        "schema": "clawreflex-pilot-summary/v1",
        "participants": len(participants), "observed_days": days,
        "counts": {kind: len(group) for kind, group in groups.items()},
        "install_success": installs, "repair_acceptance": acceptance,
        "crash_free_sessions": crash_free, "false_applies": false_applies,
        "p95_latency_ms": p95, "gates": gates, "passed": all(gates.values()),
        "limitation": "Self-reported local events require independent audit; no automated external certification.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path, help="consented JSONL events; never uploaded")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raw = args.events.read_bytes()
    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    result = summarize(events)
    result["input_sha256"] = hashlib.sha256(raw).hexdigest()
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
