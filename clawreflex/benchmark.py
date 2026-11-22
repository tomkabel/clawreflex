#!/usr/bin/env python3
"""Paired direct repair benchmark with immutable receipts and explicit live gates."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import secrets
import threading
import time
from typing import Any

if __package__:
    from .benchmark_stats import summarize_paired
    from .fixtures import fixture
    from .provider import Endpoint, ProviderClient, TOOLS, packed, repair_loop
    from .server import RepairRun, save_json
else:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from clawreflex.benchmark_stats import summarize_paired
    from clawreflex.fixtures import fixture
    from clawreflex.provider import Endpoint, ProviderClient, TOOLS, packed, repair_loop
    from clawreflex.server import RepairRun, save_json


def endpoint_config(name: str) -> dict[str, str]:
    """Historical demo aliases; production models must be configured explicitly."""
    if name == 'cerebras':
        return dict(name=name, base_url=os.environ.get('CEREBRAS_BASE_URL', 'https://api.cerebras.ai/v1'),
                    model=os.environ.get('CEREBRAS_MODEL', 'moonshotai-kimi-k3.1-pro-trial'), key_env='CEREBRAS_API_KEY')
    return dict(name=name, base_url=os.environ.get('CLAWREFLEX_BASELINE_URL', 'https://openrouter.ai/api/v1'),
                model=os.environ.get('CLAWREFLEX_BASELINE_MODEL', ''), key_env='OPENROUTER_API_KEY')


def task_prompt(fixture_name: str, nonce: str) -> str:
    spec = fixture(fixture_name, nonce)
    return f"Audit this saved owned Python module. Contract: {spec['contract']}\n\n{spec['code']}"


def normalized_request_hash(fixture_name: str, nonce: str, token_budget: int, stream: bool = True) -> str:
    return hashlib.sha256(packed({'prompt': task_prompt(fixture_name, nonce), 'token_budget': token_budget,
                                 'stream': stream, 'tools': TOOLS, 'temperature': 0})).hexdigest()


def run_endpoint(endpoint: Endpoint, fixture_name: str, nonce: str, output: Path,
                 timeout: float, max_tokens: int, *, client: ProviderClient | None = None,
                 warm_worker: Any = None) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    own = client is None
    client = client or ProviderClient(endpoint)
    run = RepairRun(fixture_name, nonce, output / 'evidence',
                    **({'executor': warm_worker.executor} if warm_worker is not None else {}))
    try:
        result = repair_loop(client, run, task_prompt(fixture_name, nonce), output / 'provider',
                             token_budget=max_tokens, deadline=time.monotonic() + timeout, cancel=threading.Event())
        result.update(provider=endpoint.name, model=endpoint.model, fixture=fixture_name,
                      scope='two direct API turns + isolated verification; excludes workspace watch/debounce and OpenClaw',
                      worker='warm' if warm_worker is not None else 'cold',
                      request_sha256=normalized_request_hash(fixture_name, nonce, max_tokens),
                      total_wall_ms=result['wall_ms'])
        save_json(output / 'loop.json', result)
        return result
    finally:
        if own:
            client.close()


def run_provider(name: str, fixture_name: str, nonce: str, output: Path, timeout: int, max_tokens: int) -> dict[str, Any]:
    return run_endpoint(Endpoint(**endpoint_config(name)), fixture_name, nonce, output, timeout, max_tokens)


def markdown(summary: dict[str, Any]) -> str:
    lines = ['# ClawReflex paired benchmark', '',
             'Generated from receipts. Direct API/tool loop; excludes OpenClaw and workspace saves.', '',
             '| Provider | Success / attempts | Wall p50 ms | Wall p95 ms | Queue p50 ms |',
             '| --- | ---: | ---: | ---: | ---: |']
    for name, values in sorted(summary['providers'].items()):
        def value(key: str) -> str:
            return 'unavailable' if values[key] is None else f"{values[key]:.2f}"
        lines.append(f"| {name} | {values['successes']} / {values['attempts']} | {value('wall_p50_ms')} | {value('wall_p95_ms')} | {value('queue_p50_ms')} |")
    lines += ['', f"Live readiness gates passed: **{summary['passed']}**.", '', summary['method'], '',
              summary['limitation'], '', 'A replay or dry-run result is never live speed evidence.', '']
    return '\n'.join(lines)


def paired(endpoints: list[Endpoint], output: Path, runs: int = 30, *, timeout: float = 60,
           max_tokens: int = 4096, warm: bool = False) -> dict[str, Any]:
    if len({endpoint.name for endpoint in endpoints}) != len(endpoints) or len(endpoints) < 2:
        raise ValueError('at least two uniquely named providers required')
    if not 1 <= runs <= 1000:
        raise ValueError('runs must be 1–1000')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', endpoint.name) for endpoint in endpoints):
        raise ValueError('invalid provider name')
    # Validate every key before spending on even the first request.
    if any(not os.environ.get(endpoint.key_env) for endpoint in endpoints):
        raise ValueError('one or more provider credential environment variables are missing')
    output.mkdir(parents=True, exist_ok=False)
    clients = {endpoint.name: ProviderClient(endpoint) for endpoint in endpoints}
    worker = None
    if warm:
        from .warm_worker import WarmWorker
        worker = WarmWorker()
    rows = []
    rng = random.Random(0)
    try:
        for index in range(runs):
            order = list(endpoints)
            rng.shuffle(order)
            fixture_name = ('sql', 'path', 'ledger')[index % 3]
            nonce = f'paired{index:06d}'
            for endpoint in order:
                started = time.monotonic()
                try:
                    result = run_endpoint(endpoint, fixture_name, nonce, output / f'pair-{index:03d}' / endpoint.name,
                                          timeout, max_tokens, client=clients[endpoint.name], warm_worker=worker)
                except Exception as exc:
                    result = dict(success=False, error=type(exc).__name__, wall_ms=(time.monotonic() - started) * 1000,
                                  queue_ms=0)
                row = dict(provider=endpoint.name, model=endpoint.model, pair_id=str(index), mode='live',
                           fixture=fixture_name, success=result['success'], wall_ms=result['wall_ms'],
                           queue_ms=min(result.get('queue_ms', 0), result['wall_ms']),
                           request_sha256=normalized_request_hash(fixture_name, nonce, max_tokens))
                rows.append(row)
                save_json(output / 'rows.json', rows)
                print(json.dumps(row), flush=True)
        summary = summarize_paired(rows)
        summary['product_save_to_done_measured'] = False
        summary['full_user_targets_pass'] = False
        summary['scope'] = 'direct API/tool repair; independent of unmeasured workspace/OpenClaw latency'
        save_json(output / 'summary.json', summary)
        (output / 'summary.md').write_text(markdown(summary), encoding='utf-8')
        receipts = {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(output.rglob('*')) if path.is_file()}
        save_json(output / 'manifest.json', {'schema': 'clawreflex-benchmark-manifest/v1', 'files': receipts})
        return summary
    finally:
        for client in clients.values():
            client.close()
        if worker is not None:
            worker.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument('--endpoints', type=Path, help='JSON list of name/base_url/model/key_env; Cerebras and two GPU baselines')
    selector.add_argument('--only', choices=['cerebras', 'baseline'], help='single-endpoint diagnostic; cannot pass paired gates')
    selector.add_argument('--replay', type=Path, help='summarize receipt rows as replay; cannot pass live gates')
    parser.add_argument('--runs', type=int, default=30)
    parser.add_argument('--fixture', choices=['sql', 'path', 'ledger'], default='sql')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--max-tokens', type=int, default=4096)
    parser.add_argument('--warm', action='store_true')
    args = parser.parse_args()
    if args.replay:
        args.output.mkdir(parents=True, exist_ok=False)
        rows = json.loads(args.replay.read_text())
        for row in rows:
            row['mode'] = 'replay'
        summary = summarize_paired(rows)
        save_json(args.output / 'summary.json', summary)
        (args.output / 'summary.md').write_text(markdown(summary))
        print(json.dumps(summary, indent=2))
        return 1
    if args.only:
        args.output.mkdir(parents=True, exist_ok=False)
        result = run_provider(args.only, args.fixture, 'cr' + secrets.token_hex(6), args.output / args.only,
                              args.timeout, args.max_tokens)
        save_json(args.output / 'results.json', {'results': [result], 'full_user_targets_pass': False,
                                               'note': 'single endpoint is not paired speedup evidence'})
        print(json.dumps(result, indent=2))
        return 0 if result['success'] else 1
    raw = json.loads(args.endpoints.read_text())
    if not isinstance(raw, list) or any(not isinstance(item, dict) or set(item) != {'name', 'base_url', 'model', 'key_env'} for item in raw):
        parser.error('endpoints must be a JSON list of name/base_url/model/key_env objects')
    summary = paired([Endpoint(**item) for item in raw], args.output, args.runs,
                     timeout=args.timeout, max_tokens=args.max_tokens, warm=args.warm)
    print(json.dumps(summary, indent=2))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
