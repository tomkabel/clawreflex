import contextlib
import http.server
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from clawreflex.fixtures import fixture
from clawreflex.provider import (BudgetExceeded, Cancelled, Endpoint, ProviderClient, ProviderError,
                                public_probe, repair_loop, one_tool, sanitized)
from clawreflex.server import RepairRun
from clawreflex.test_server import PROBES


@contextlib.contextmanager
def provider_server(responder):
    requests = []
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((body, self.client_address[1]))
            status, content, content_type = responder(body, len(requests))
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Retry-After', '0')
            self.end_headers()
            try:
                self.wfile.write(content)
            except BrokenPipeError:
                pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Endpoint('test', f'http://127.0.0.1:{server.server_port}/v1', 'local-test-model', 'CLAWREFLEX_TEST_PROVIDER_KEY'), requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def stream_call(name, arguments, reasoning='full reasoning', tokens=25):
    argument_text = json.dumps(arguments)
    events = [
        {'choices': [{'delta': {'role': 'assistant', 'reasoning_content': reasoning[:4]}}]},
        {'choices': [{'delta': {'reasoning_content': reasoning[4:], 'tool_calls': [
            {'index': 0, 'id': 'call-1', 'type': 'function', 'function': {'name': name, 'arguments': argument_text[:7]}}]}}]},
        {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': argument_text[7:]}}]}, 'finish_reason': 'tool_calls'}]},
        {'choices': [], 'usage': {'completion_tokens': tokens, 'prompt_tokens': 100}, 'time_info': {'completion_time': .02}},
    ]
    # Multiple data fields in an event exercise SSE framing, not line-only parsing.
    raw = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events) + 'data: [DONE]\n\n'
    return 200, raw.encode(), 'text/event-stream'


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {'CLAWREFLEX_TEST_PROVIDER_KEY': 'local-credential-value'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_actual_streamed_repair_replays_reasoning_keeps_connection_and_hides_oracles(self):
        def respond(body, index):
            if index == 1:
                return stream_call('clawreflex_probe', {'test_source': PROBES['sql']})
            assistant = body['messages'][2]
            self.assertEqual(assistant['reasoning_content'], 'full reasoning')
            self.assertEqual(assistant['tool_calls'][0]['id'], 'call-1')
            tool = json.loads(body['messages'][3]['content'])
            self.assertNotIn('reference', tool)
            self.assertNotIn('reference_check', tool)
            self.assertNotIn('heldout', body['messages'][3]['content'])
            return stream_call('clawreflex_patch', {'source': fixture('sql', 'testnonce')['reference'], 'summary': 'parameterize query'})
        with provider_server(respond) as (endpoint, requests), tempfile.TemporaryDirectory() as tmp:
            client = ProviderClient(endpoint)
            try:
                engine = RepairRun('sql', 'testnonce', Path(tmp) / 'engine')
                result = repair_loop(client, engine, 'Public source and contract', Path(tmp) / 'provider',
                                     token_budget=1000, deadline=time.monotonic() + 10, cancel=threading.Event())
                self.assertTrue(result['success'], result)
                self.assertIsNotNone(engine.verified_source)
                self.assertEqual(requests[0][1], requests[1][1])
                self.assertNotIn('local-credential-value', ''.join(path.read_text() for path in Path(tmp).rglob('*.json')))
            finally:
                client.close()

    def test_429_is_queued_and_retried_with_separate_timing(self):
        def respond(body, index):
            return (429, b'{"error":"queue_exceeded"}', 'application/json') if index == 1 else stream_call('clawreflex_probe', {'test_source': PROBES['sql']})
        with provider_server(respond) as (endpoint, requests), tempfile.TemporaryDirectory() as tmp:
            client = ProviderClient(endpoint)
            states = []
            try:
                result = client.complete({'model': endpoint.model, 'stream': True, 'messages': []}, Path(tmp),
                                         deadline=time.monotonic() + 3, cancel=threading.Event(), on_state=states.append)
                self.assertEqual(states, ['queued', 'running'])
                self.assertGreater(result['queue_ms'], 0)
                self.assertEqual(len(requests), 2)
                self.assertEqual(result['attempts'][0]['status'], 429)
            finally:
                client.close()

    def test_cancel_and_deadline_interrupt_blocking_provider(self):
        def slow(body, index):
            time.sleep(.3)
            return stream_call('clawreflex_probe', {'test_source': PROBES['sql']})
        with provider_server(slow) as (endpoint, _), tempfile.TemporaryDirectory() as tmp:
            for cancellation in (True, False):
                client = ProviderClient(endpoint)
                cancel = threading.Event()
                timer = threading.Timer(.05, cancel.set) if cancellation else None
                if timer:
                    timer.start()
                started = time.monotonic()
                try:
                    with self.assertRaises(Cancelled if cancellation else BudgetExceeded):
                        client.complete({'model': endpoint.model, 'stream': True}, Path(tmp), cancel=cancel,
                                        deadline=time.monotonic() + (3 if cancellation else .05))
                    self.assertLess(time.monotonic() - started, .25)
                finally:
                    client.close()
                    if timer:
                        timer.join()

    def test_malformed_stream_and_http_errors_fail_without_leaking_body(self):
        for response in ((500, b'private provider error local-credential-value', 'application/json'),
                         (200, b'data: not-json\n\n', 'text/event-stream'),
                         (200, b'data: {"choices":[]}\n\n', 'text/event-stream')):
            with self.subTest(response=response), provider_server(lambda *_: response) as (endpoint, _), tempfile.TemporaryDirectory() as tmp:
                client = ProviderClient(endpoint)
                try:
                    with self.assertRaises(ProviderError):
                        client.complete({'model': endpoint.model}, Path(tmp), deadline=time.monotonic() + 2, cancel=threading.Event())
                    self.assertNotIn('private provider', (Path(tmp) / 'result.json').read_text())
                finally:
                    client.close()

    def test_budget_usage_and_bad_tool_stop_before_patch(self):
        for tokens in (None, 200):
            with provider_server(lambda *_: stream_call('clawreflex_probe', {'test_source': PROBES['sql']}, tokens=tokens)) as (endpoint, requests), tempfile.TemporaryDirectory() as tmp:
                client = ProviderClient(endpoint)
                try:
                    result = repair_loop(client, RepairRun('sql', 'testnonce', Path(tmp) / 'engine'), 'public', Path(tmp),
                                         token_budget=100, deadline=time.monotonic() + 3, cancel=threading.Event())
                    self.assertFalse(result['success'])
                    self.assertEqual(result['error_type'], 'BudgetExceeded')
                    self.assertEqual(len(requests), 1)
                finally:
                    client.close()

    def test_endpoint_schema_and_disclosure_filter(self):
        for url in ('http://example.com', 'https://user:pass@example.com', 'https://example.com?secret=x'):
            with self.assertRaises(ValueError):
                Endpoint('test', url, 'model', 'KEY')
        with self.assertRaises(ProviderError):
            one_tool({'tool_calls': []}, 'clawreflex_probe')
        clean = public_probe({'ok': True, 'reference': {'output': 'secret oracle'}, 'heldout': 'secret'})
        self.assertNotIn('secret', json.dumps(clean))
        self.assertEqual(sanitized({'text': 'secret'}, secret='secret'), {'text': '[REDACTED]'})


class ProviderEdgeTests(unittest.TestCase):
    def test_nonstream_message_preserves_reasoning_and_time_info(self):
        message = {'role': 'assistant', 'content': None, 'reasoning_content': 'retained', 'tool_calls': [
            {'id': 'id1', 'type': 'function', 'function': {'name': 'clawreflex_probe', 'arguments': json.dumps({'test_source': PROBES['sql']})}}]}
        raw = json.dumps({'choices': [{'message': message, 'finish_reason': 'tool_calls'}],
                          'usage': {'completion_tokens': 40}, 'time_info': {'completion_time': .1}}).encode()
        with provider_server(lambda *_: (200, raw, 'application/json')) as (endpoint, _), tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {endpoint.key_env: 'not-a-real-key'}):
            client = ProviderClient(endpoint)
            try:
                result = client.complete({'model': endpoint.model, 'stream': False}, Path(tmp),
                                         deadline=time.monotonic() + 2, cancel=threading.Event())
                self.assertEqual(result['assistant'], message)
                self.assertEqual(result['time_info']['completion_time'], .1)
            finally:
                client.close()

    def test_queued_failure_has_failure_receipt_and_does_not_retry_forever(self):
        with provider_server(lambda *_: (429, b'{"error":"busy"}', 'application/json')) as (endpoint, requests), \
                tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {endpoint.key_env: 'not-a-real-key'}):
            client = ProviderClient(endpoint, max_attempts=2)
            try:
                with self.assertRaises(ProviderError):
                    client.complete({'model': endpoint.model}, Path(tmp), deadline=time.monotonic() + 2, cancel=threading.Event())
                self.assertEqual(len(requests), 2)
                result = json.loads((Path(tmp) / 'result.json').read_text())
                self.assertFalse(result['success'])
                self.assertEqual(len(result['attempts']), 2)
                self.assertGreater(result['queue_ms'], 0)
            finally:
                client.close()

    def test_sensitive_reasoning_stops_replay_instead_of_dropping_field(self):
        with provider_server(lambda *_: stream_call('clawreflex_probe', {'test_source': PROBES['sql']}, reasoning='not-a-real-key')) as (endpoint, requests), \
                tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {endpoint.key_env: 'not-a-real-key'}):
            client = ProviderClient(endpoint)
            try:
                result = repair_loop(client, RepairRun('sql', 'testnonce', Path(tmp) / 'engine'), 'public', Path(tmp) / 'provider',
                                     token_budget=1000, deadline=time.monotonic() + 3, cancel=threading.Event())
                self.assertFalse(result['success'])
                self.assertIn('sensitive', result['error'])
                self.assertEqual(len(requests), 1)
                self.assertNotIn('not-a-real-key', (Path(tmp) / 'provider' / 'provider.json').read_text())
            finally:
                client.close()

    def test_malformed_native_tool_schemas_rejected(self):
        for calls in ({'bad': 'type'}, [None], [{'id': 'x', 'function': []}],
                      [{'id': 'x', 'function': {'name': 'clawreflex_probe', 'arguments': []}}],
                      [{'id': 'x', 'function': {'name': 'clawreflex_probe', 'arguments': '{"test_source":4}'}}]):
            with self.subTest(calls=calls), self.assertRaises(ProviderError):
                one_tool({'tool_calls': calls}, 'clawreflex_probe')

    def test_missing_key_and_sensitive_outgoing_request_are_blocked(self):
        endpoint = Endpoint('test', 'http://localhost:1', 'model', 'MISSING_TEST_KEY')
        with tempfile.TemporaryDirectory() as tmp:
            client = ProviderClient(endpoint)
            with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(ProviderError):
                client.complete({}, Path(tmp), deadline=time.monotonic() + 2, cancel=threading.Event())
            with mock.patch.dict(os.environ, {'MISSING_TEST_KEY': 'private-key-value'}), self.assertRaises(ProviderError):
                client.complete({'messages': [{'content': 'private-key-value'}]}, Path(tmp), deadline=time.monotonic() + 2, cancel=threading.Event())
            self.assertIsNone(client.connection)
