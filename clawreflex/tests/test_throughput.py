import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from clawreflex.tests.test_provider import provider_server, stream_call
from clawreflex.throughput import main, stream_once


class ThroughputTests(unittest.TestCase):
    def test_diagnostic_records_reasoning_queue_usage_and_server_decode(self):
        with provider_server(lambda *_: stream_call('unused', {}, reasoning='kept thinking')) as (endpoint, _), \
                mock.patch.dict(os.environ, {endpoint.key_env: 'local-key'}):
            result = stream_once(vars(endpoint), {'model': endpoint.model, 'stream': True}, 3)
            self.assertEqual(result['http_status'], 200)
            self.assertEqual(result['reasoning_content'], 'kept thinking')
            self.assertEqual(result['server_decode_tok_s'], 1250)
            self.assertIn('client_decode_tok_s', result)

    def test_http_failure_is_recorded_without_provider_error_body(self):
        with provider_server(lambda *_: (500, b'private response body', 'application/json')) as (endpoint, _), \
                mock.patch.dict(os.environ, {endpoint.key_env: 'local-key'}):
            result = stream_once(vars(endpoint), {'model': endpoint.model, 'stream': True}, 3)
            self.assertEqual(result['http_status'], 500)
            self.assertNotIn('private response', json.dumps(result))

    def test_cli_uses_explicit_model_and_counts_attempts(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch('clawreflex.throughput.endpoint_config', return_value={
            'name': 'cerebras', 'base_url': 'http://localhost', 'model': 'configured', 'key_env': 'TEST'}), \
                mock.patch('clawreflex.throughput.stream_once', return_value={
                    'http_status': 200, 'client_decode_tok_s': 123, 'text': 'source', 'reasoning_content': 'thinking'}), \
                mock.patch('sys.argv', ['throughput', '--only', 'cerebras', '--model', 'explicit', '--runs', '1', '--output', str(Path(tmp) / 'output')]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)
            summary = json.loads((Path(tmp) / 'output' / 'summary.json').read_text())
            self.assertEqual(summary['n'], 1)
            self.assertEqual(summary['client_decode_tok_s_median'], 123)
