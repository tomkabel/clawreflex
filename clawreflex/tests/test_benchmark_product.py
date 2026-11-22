import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from clawreflex.benchmark import main, normalized_request_hash, paired
from clawreflex.provider import Endpoint


class PairedBenchmarkTests(unittest.TestCase):
    def test_balanced_requests_retains_failures_and_writes_hash_manifest(self):
        endpoints = [Endpoint(name, 'http://127.0.0.1:1', 'configured-model', 'TEST_BENCH_KEY') for name in ('cerebras', 'gpu-a', 'gpu-b')]
        orders = []
        def run(endpoint, fixture_name, nonce, output, timeout, max_tokens, **kwargs):
            orders.append((nonce, endpoint.name))
            output.mkdir(parents=True)
            (output / 'receipt.json').write_text('{}')
            return {'success': endpoint.name != 'gpu-b', 'wall_ms': 20, 'queue_ms': 2}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {'TEST_BENCH_KEY': 'local'}), \
                mock.patch('clawreflex.benchmark.run_endpoint', side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            output = Path(tmp) / 'bench'
            result = paired(endpoints, output, runs=2)
            self.assertFalse(result['passed'])
            self.assertEqual(result['complete_pairs'], 2)
            rows = json.loads((output / 'rows.json').read_text())
            self.assertEqual(len(rows), 6)
            self.assertEqual(result['providers']['gpu-b']['failures'], 2)
            manifest = json.loads((output / 'manifest.json').read_text())
            self.assertIn('rows.json', manifest['files'])
            self.assertIn('Live readiness gates passed: **False**', (output / 'summary.md').read_text())
            for pair in ('paired000000', 'paired000001'):
                self.assertEqual(len([item for item in orders if item[0] == pair]), 3)

    def test_replay_cannot_be_promoted_to_live_evidence(self):
        rows = [dict(provider=name, pair_id=str(index), request_sha256='same-task', mode='live',
                     success=True, wall_ms=1000, queue_ms=0)
                for name in ('cerebras', 'gpu-a', 'gpu-b') for index in range(30)]
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'rows.json'
            source.write_text(json.dumps(rows))
            output = Path(tmp) / 'summary'
            with mock.patch('sys.argv', ['bench', '--replay', str(source), '--output', str(output)]), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 1)
            result = json.loads((output / 'summary.json').read_text())
            self.assertFalse(result['gates']['live_receipts_only'])
            self.assertFalse(result['passed'])

    def test_missing_credentials_preflight_before_any_call(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch('clawreflex.benchmark.run_endpoint') as runner, self.assertRaises(ValueError):
            paired([Endpoint(name, 'http://localhost', 'model', 'MISSING') for name in ('a', 'b')], Path(tmp) / 'bench')
        runner.assert_not_called()
        self.assertEqual(normalized_request_hash('sql', 'nonce', 100), normalized_request_hash('sql', 'nonce', 100))


class BenchmarkTransportTests(unittest.TestCase):
    def test_direct_endpoint_loop_uses_real_local_stream_and_sandbox(self):
        from clawreflex.benchmark import run_endpoint
        from clawreflex.fixtures import fixture
        from clawreflex.test_server import PROBES
        from clawreflex.tests.test_provider import provider_server, stream_call
        def respond(body, index):
            return stream_call('clawreflex_probe', {'test_source': PROBES['sql']}) if index == 1 else stream_call('clawreflex_patch', {'source': fixture('sql', 'benchnonce')['reference'], 'summary': 'parameterized'})
        with provider_server(respond) as (endpoint, _), tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {endpoint.key_env: 'local-test-key'}):
            result = run_endpoint(endpoint, 'sql', 'benchnonce', Path(tmp) / 'endpoint', 10, 1000)
            self.assertTrue(result['success'], result)
            self.assertEqual(result['worker'], 'cold')
            self.assertEqual(len(result['request_sha256']), 64)
