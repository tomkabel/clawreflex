import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from clawreflex.server import RepairRun, RunServer
from clawreflex.test_server import PROBES

TOKEN = 'local-test-token-with-more-than-24-characters'


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = RepairRun('sql', 'http', Path(self.tmp.name))
        self.server = RunServer(('127.0.0.1', 0), self.run, TOKEN)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def request(self, method, route, value=None, *, auth=True, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        request_headers = {'Content-Type': 'application/json'}
        if auth:
            request_headers['Authorization'] = 'Bearer ' + TOKEN
        request_headers.update(headers or {})
        body = json.dumps(value) if value is not None else None
        connection.request(method, route, body, request_headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def test_health_public_state_authenticated(self):
        self.assertEqual(self.request('GET', '/health', auth=False)[0], 200)
        self.assertEqual(self.request('GET', '/state', auth=False)[0], 401)
        status, state = self.request('GET', '/state')
        self.assertEqual(status, 200)
        self.assertEqual(state['state'], 'waiting_for_probe')
        self.assertEqual(self.request('POST', '/tool/clawreflex_probe', {}, auth=False)[0], 401)

    def test_malformed_object_types_and_oversize(self):
        for value in ([], {'test_source': 42}, {'wrong': 'value'}, {'test_source': 'x', 'extra': 'x'}):
            with self.subTest(value=value):
                self.assertEqual(self.request('POST', '/tool/clawreflex_probe', value)[0], 400)
        self.assertEqual(self.request('POST', '/tool/clawreflex_probe', {'test_source': 'x'*70000})[0], 413)

    def test_invalid_host_and_cross_origin_refused(self):
        self.assertEqual(self.request('GET', '/health', headers={'Host': 'attacker.example'})[0], 403)
        self.assertEqual(self.request('POST', '/tool/clawreflex_probe', {},
                                      headers={'Origin': 'https://attacker.example'})[0], 403)

    def test_red_green_and_rejected_probe_contract(self):
        status, rejected = self.request('POST', '/tool/clawreflex_probe', {'test_source': 'import os'})
        self.assertEqual(status, 422)
        self.assertFalse(rejected['ok'])
        status, red = self.request('POST', '/tool/clawreflex_probe', {'test_source': PROBES['sql']})
        self.assertEqual(status, 200, red)
        self.assertTrue(red['red_confirmed'])
        status, green = self.request('POST', '/tool/clawreflex_patch', {'source': self.run.spec['reference']})
        self.assertEqual(status, 200, green)
        self.assertTrue(green['ok'])
        self.assertEqual(green['application_scope'], 'artifact')

    def test_concurrent_tool_call_returns_busy_without_interleaving(self):
        self.run.http_lock.acquire()
        try:
            status, error = self.request('POST', '/tool/clawreflex_probe', {'test_source': PROBES['sql']})
        finally:
            self.run.http_lock.release()
        self.assertEqual(status, 429)
        self.assertEqual(error['error'], 'run_busy')
        self.assertEqual(self.run.probe_attempts, 0)

    def test_rate_limit_and_unknown_route(self):
        self.assertEqual(self.request('GET', '/missing')[0], 404)
        self.server.rate_per_minute = 1
        self.assertEqual(self.request('GET', '/health')[0], 429)

    def test_nonloopback_bind_and_short_token_refused(self):
        with self.assertRaises(ValueError):
            RunServer(('0.0.0.0', 0), self.run, TOKEN)
        with self.assertRaises(ValueError):
            RunServer(('127.0.0.1', 0), self.run, 'short')

    def test_patch_precondition_and_action_schema(self):
        self.assertEqual(self.request('POST', '/tool/clawreflex_patch', {'source': self.run.spec['reference']})[0], 400)
        self.assertEqual(self.request('POST', '/action/apply', {'idempotency_key': ''})[0], 400)
        self.assertEqual(self.request('POST', '/action/apply', {'idempotency_key': 'valid'})[0], 400)
