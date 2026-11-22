"""Paired latency statistics with explicit live-evidence requirements."""
from __future__ import annotations

from collections import defaultdict
import math
import random
import statistics
from typing import Any


def percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * probability) - 1)]


def summarize_paired(rows: list[dict[str, Any]], bootstrap_samples: int = 2000) -> dict[str, Any]:
    if bootstrap_samples < 100:
        raise ValueError("bootstrap requires at least 100 samples")
    providers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pairs: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        for key in ("provider", "pair_id", "request_sha256", "mode"):
            if not isinstance(row.get(key), str) or not row[key]:
                raise ValueError(f"missing or invalid {key}")
        if type(row.get("success")) is not bool:
            raise ValueError("success must be boolean")
        for key in ("wall_ms", "queue_ms"):
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid {key}")
        if row["queue_ms"] > row["wall_ms"]:
            raise ValueError("queue cannot exceed wall time")
        if row["provider"] in pairs[row["pair_id"]]:
            raise ValueError("duplicate provider in pair")
        providers[row["provider"]].append(row)
        pairs[row["pair_id"]][row["provider"]] = row
    provider_names = set(providers)
    complete = [pair for pair in pairs.values() if set(pair) == provider_names]
    matching = all(len({row["request_sha256"] for row in pair.values()}) == 1 for pair in complete)
    if not matching:
        raise ValueError("paired initial requests differ after normalizing provider model")
    provider_results: dict[str, dict[str, Any]] = {}
    for name, records in providers.items():
        successes = [row for row in records if row["success"]]
        wall = [row["wall_ms"] for row in successes]
        queue = [row["queue_ms"] for row in successes]
        active = [row["wall_ms"] - row["queue_ms"] for row in successes]
        provider_results[name] = {
            "attempts": len(records), "successes": len(successes),
            "failures": len(records) - len(successes),
            "wall_p50_ms": percentile(wall, .5), "wall_p95_ms": percentile(wall, .95),
            "queue_p50_ms": percentile(queue, .5), "queue_p95_ms": percentile(queue, .95),
            "nonqueue_p50_ms": percentile(active, .5), "nonqueue_p95_ms": percentile(active, .95),
            "latency_population": "successful runs only; failures retained in counts and block pass",
        }
    rng = random.Random(0)
    comparisons = {}
    for name in sorted(provider_names - {"cerebras"}):
        ratios = [pair[name]["wall_ms"] / pair["cerebras"]["wall_ms"] for pair in complete
                  if "cerebras" in pair and pair[name]["success"] and pair["cerebras"]["success"]
                  and pair["cerebras"]["wall_ms"] > 0]
        if ratios:
            samples = [statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(bootstrap_samples)]
            comparisons[name] = {
                "successful_pairs": len(ratios), "median_wall_speedup": statistics.median(ratios),
                "paired_bootstrap_95pct_ci": [percentile(samples, .025), percentile(samples, .975)],
            }
    cerebras = provider_results.get("cerebras", {})
    gates = {
        "live_receipts_only": bool(rows) and all(row["mode"] == "live" for row in rows),
        "cerebras_and_two_gpu_baselines": "cerebras" in providers and len(provider_names - {"cerebras"}) >= 2,
        "at_least_thirty_complete_pairs": len(complete) >= 30,
        "no_incomplete_pairs": bool(pairs) and len(complete) == len(pairs),
        "all_runs_successful": bool(rows) and all(row["success"] for row in rows),
        "cerebras_wall_p50_at_most_2000ms": cerebras.get("wall_p50_ms") is not None and cerebras["wall_p50_ms"] <= 2000,
        "cerebras_wall_p95_at_most_5000ms": cerebras.get("wall_p95_ms") is not None and cerebras["wall_p95_ms"] <= 5000,
    }
    return {
        "schema": "clawreflex-paired-statistics/v1", "complete_pairs": len(complete),
        "providers": provider_results, "comparisons_to_cerebras": comparisons,
        "gates": gates, "passed": all(gates.values()),
        "method": "nearest-rank quantiles; paired bootstrap median wall-time ratio, seed 0",
        "request_matching": "identical initial task/prompt/options except provider model; later tool transcripts may differ",
        "limitation": "Backend hardware identity and receipt provenance require audit; labels alone do not establish GPU execution.",
    }
