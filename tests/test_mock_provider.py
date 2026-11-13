"""T01: the injectable mock provider contract, before its implementation.

Reply facts are authored from planning/plan.md B1 and IT-001's message.
These tests exercise provider mechanics, without asserting routing or accuracy.
"""

import json
import os
import socket
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RESPONSES = ROOT / "tests" / "mock_responses"


class OfflineMockContract(unittest.TestCase):
    def start_patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def setUp(self):
        # Fail on credential reads even when the runner has API_KEY unset.
        original_getitem = os._Environ.__getitem__

        def forbid_credential_read(environ, key):
            if key == "API_KEY":
                raise AssertionError("T01 must not read API_KEY")
            return original_getitem(environ, key)

        self.start_patch(mock.patch.object(os._Environ, "__getitem__", forbid_credential_read))
        self.socket_guard = self.start_patch(mock.patch.object(
            socket, "socket", side_effect=AssertionError("T01 must not open sockets")
        ))
        self.connection_guard = self.start_patch(mock.patch.object(
            socket, "create_connection", side_effect=AssertionError("T01 must not use network")
        ))
        self.request = {
            "document_id": "IT-001.json",
            "message": json.loads(
                (ROOT / "materials" / "requests" / "IT-001.json").read_text(encoding="utf-8")
            )["message"],
        }

    def tearDown(self):
        self.socket_guard.assert_not_called()
        self.connection_guard.assert_not_called()

    def test_t01_saved_response_and_request_capture(self):
        from access_intake.providers import MockProvider, Provider

        provider = MockProvider(RESPONSES, schedule=["complete-001"])
        self.assertIsInstance(provider, Provider)
        reply = provider.extract(self.request)

        self.assertEqual(reply["response_source"], "mock")
        self.assertEqual(reply["status"], "completed")
        self.assertEqual(reply["extraction"]["request_id"], "IT-001")
        self.assertEqual(reply["extraction"]["requester"], "Maya Chen")
        self.assertEqual(reply["extraction"]["permission"], "read")
        self.assertEqual(reply["extraction"]["end_date"], "2026-11-06")
        self.assertEqual(reply, json.loads(
            (RESPONSES / "complete-001.json").read_text(encoding="utf-8")
        ))  # Transport fidelity only; the fact assertions above are independent.
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(provider.requests, [dict(self.request)])
        self.request["message"] = "changed after submission"
        self.assertIn("Maya Chen from Analytics", provider.requests[0]["message"])

    def test_t01_scheduled_error_then_saved_reply(self):
        from access_intake.providers import MockProvider

        failure = TimeoutError("scheduled mock timeout")
        provider = MockProvider(RESPONSES, schedule=[failure, "complete-001"])
        with self.assertRaises(TimeoutError) as caught:
            provider.extract(self.request)
        self.assertIs(caught.exception, failure)
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(provider.requests, [self.request])
        self.assertEqual(provider.extract(self.request)["response_source"], "mock")
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(provider.requests, [self.request, self.request])
        with self.assertRaisesRegex(RuntimeError, "exhausted"):
            provider.extract(self.request)

    def test_t01_barrier_allows_an_independent_call_to_finish(self):
        from access_intake.providers import ControlledResponse, MockProvider

        started, release = Event(), Event()
        provider = MockProvider(RESPONSES, schedule=[
            ControlledResponse("complete-001", started=started, release=release),
            "complete-001",
        ])
        with ThreadPoolExecutor(max_workers=2) as pool:
            delayed = pool.submit(provider.extract, self.request)
            try:
                self.assertTrue(started.wait(timeout=2), "delayed call never reached barrier")
                self.assertFalse(delayed.done())
                fast = pool.submit(provider.extract, dict(self.request))
                self.assertEqual(fast.result(timeout=2)["extraction"]["system"], "Atlas")
                self.assertFalse(delayed.done(), "barrier released without its signal")
                self.assertEqual(provider.call_count, 2)
                self.assertEqual(provider.requests, [self.request, self.request])
            finally:
                release.set()
            self.assertEqual(delayed.result(timeout=2)["response_source"], "mock")


if __name__ == "__main__":
    unittest.main()
