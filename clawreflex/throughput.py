#!/usr/bin/env python3
"""Raw streaming diagnostics. These results are not product repair latency."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import tempfile
import threading
import time
from typing import Any

if __package__:
    from .benchmark import endpoint_config
    from .fixtures import fixture
    from .provider import Endpoint, ProviderClient, ProviderError, sanitized
else:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from clawreflex.benchmark import endpoint_config
    from clawreflex.fixtures import fixture
    from clawreflex.provider import Endpoint, ProviderClient, ProviderError, sanitized

PROMPT = "Repair authenticate() so only an exact valid credential pair passes; explain the SQL injection fix.\n\n{code}"


def stream_once(endpoint: dict[str, str], body: dict[str, Any], timeout: float,
                output: Path | None = None, client: ProviderClient | None = None) -> dict[str, Any]:
    own = client is None
    client = client or ProviderClient(Endpoint(**endpoint))
    temporary = tempfile.TemporaryDirectory(prefix='clawreflex-throughput-') if output is None else None
    output = Path(temporary.name) if temporary else output
    assert output is not None
    try:
        result = client.complete(sanitized(body), output, deadline=time.monotonic() + timeout, cancel=threading.Event())
        assistant = result['assistant']
        completion = result['usage'].get('completion_tokens', 0)
        info = result.get('time_info') or {}
        first_ms = result.get('ttft_ms')
        stream_s = max(0, (result['wall_ms'] - (first_ms or 0) - result['queue_ms']) / 1000)
        value = dict(http_status=200, wall_s=result['wall_ms'] / 1000, queue_s=result['queue_ms'] / 1000,
                     ttft_s=None if first_ms is None else first_ms / 1000, stream_s=stream_s,
                     completion_tokens=completion, usage=result['usage'], time_info=info,
                     provider=result.get('provider'), text=assistant.get('content') or '',
                     reasoning_content=assistant.get('reasoning_content') or assistant.get('reasoning') or '',
                     measurement='client decode estimated from total completion usage after first delta; reasoning included')
        if completion > 1 and stream_s > 0:
            value['client_decode_tok_s'] = (completion - 1) / stream_s
        if completion and isinstance(info, dict) and type(info.get('completion_time')) in (int, float) and info['completion_time'] > 0:
            value['server_decode_tok_s'] = completion / info['completion_time']
        return value
    except ProviderError as exc:
        return dict(http_status=client.last_call.get('http_status', 0), error=type(exc).__name__,
                    wall_s=client.last_call.get('wall_ms', 0) / 1000, queue_s=client.last_call.get('queue_ms', 0) / 1000)
    finally:
        if own:
            client.close()
        if temporary:
            temporary.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', choices=['cerebras', 'baseline'], required=True)
    parser.add_argument('--model', help='explicit configured model; baseline has no guessed default')
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--patience-s', type=float, default=60)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reasoning-effort', choices=['low', 'medium', 'high', 'max'])
    args = parser.parse_args()
    endpoint = endpoint_config(args.only)
    if args.model:
        endpoint['model'] = args.model
    if not 1 <= args.runs <= 1000:
        parser.error('runs must be 1–1000')
    client = ProviderClient(Endpoint(**endpoint))
    args.output.mkdir(parents=True, exist_ok=False)
    body: dict[str, Any] = {'model': endpoint['model'], 'stream': True, 'stream_options': {'include_usage': True},
                            'max_tokens': 1500, 'temperature': 0,
                            'messages': [{'role': 'user', 'content': PROMPT.format(code=fixture('sql', 'throughput')['code'])}]}
    if args.reasoning_effort:
        body['reasoning_effort'] = args.reasoning_effort
    runs = []
    try:
        for index in range(args.runs):
            result = stream_once(endpoint, body, args.patience_s, args.output / f'run-{index:03d}', client)
            runs.append(result)
            print(json.dumps({key: value for key, value in result.items() if key not in {'text', 'reasoning_content'}}), flush=True)
    finally:
        client.close()
    (args.output / 'runs.json').write_text(json.dumps(runs, indent=2) + '\n')
    good = [row for row in runs if row['http_status'] == 200 and 'client_decode_tok_s' in row]
    summary = {'n': len(good), 'attempts': len(runs), 'failures': len(runs) - len(good),
               'scope': 'raw streaming; not repair save-to-done',
               'client_decode_tok_s_median': statistics.median(row['client_decode_tok_s'] for row in good) if good else None}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return 0 if len(good) == len(runs) else 1


if __name__ == '__main__':
    raise SystemExit(main())
