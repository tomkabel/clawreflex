import os
import queue
import unittest
from unittest import mock

from clawreflex import race


class BrokenResponse:
    status = 200

    def __iter__(self):
        return self

    def __next__(self):
        raise OSError("connection reset mid-stream")


class Connection:
    def __init__(self, *_, **__):
        pass

    def request(self, *_, **__):
        pass

    def getresponse(self):
        return BrokenResponse()


class RaceTests(unittest.TestCase):
    def test_mid_stream_failure_emits_terminal_error(self):
        events = queue.Queue()
        endpoint = {"model": "test-model", "base_url": "https://example.test/v1", "key_env": "CLAWREFLEX_TEST_KEY"}
        with mock.patch.object(race, "endpoint_config", return_value=endpoint), \
                mock.patch.object(race.http.client, "HTTPSConnection", Connection), \
                mock.patch.dict(os.environ, {"CLAWREFLEX_TEST_KEY": "test-key"}):
            race.stream("cerebras", events, 10)
        event = events.get_nowait()
        self.assertEqual(event["lane"], "cerebras")
        self.assertEqual(event["type"], "error")
        self.assertEqual(event["status"], "connection reset mid-stream")
        self.assertGreaterEqual(event["t"], 0)
        self.assertTrue(events.empty())


if __name__ == "__main__":
    unittest.main()
