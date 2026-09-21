import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from agent_service.jev_client import JevClient
from agent_service.jev_runtime import configured_judgments, runtime_status
from agent_service.judgment_types import JudgmentRequest, question


class NativeJevRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.store = SimpleNamespace(tasks=SimpleNamespace(path=self.path / "checkpoint.sqlite3"))
        self.credentials = self.path / "credential.json"
        self.credentials.write_text(json.dumps({"api_key": "synthetic-private-key"}))
        self.environment = {"REVIEW_TODAY_JEV_TEST": "1", "REVIEW_TODAY_JEV_KEY_FILE": str(self.credentials)}

    def test_default_off_does_not_read_credentials_or_make_client(self):
        with patch.object(Path, "read_text", side_effect=AssertionError("must not read key")), patch("agent_service.jev_runtime.JevClient") as client:
            self.assertIsNone(configured_judgments(self.store, port=8742, environment={}))
            self.assertIsNone(configured_judgments(self.store, port=8742, environment=dict(self.environment, REVIEW_TODAY_JEV_TEST="0")))
        client.assert_not_called()
        self.assertEqual(runtime_status(None)["status"], "off")

    def test_daily_port_and_non_temporary_database_fail_before_credential_access(self):
        normal_store = SimpleNamespace(tasks=SimpleNamespace(path=Path.home() / "Library/Application Support/Review Today/agent-harness.sqlite3"))
        with patch.object(Path, "read_text", side_effect=AssertionError("must not read key")):
            for store, port in [(self.store, 8742), (normal_store, 18742)]:
                with self.subTest(port=port), self.assertRaises((ValueError, RuntimeError)):
                    configured_judgments(store, port=port, environment=self.environment)

    def test_invalid_credentials_are_explicit_and_never_echoed(self):
        for body in ("synthetic-private-key", "[]", '{"api_key": ""}'):
            self.credentials.write_text(body)
            with self.subTest(body=body), self.assertRaisesRegex(RuntimeError, "^RT.JEV.CREDENTIAL_UNAVAILABLE$"):
                configured_judgments(self.store, port=18742, environment=self.environment)
        with self.assertRaisesRegex(RuntimeError, "INVALID_TEST_FLAG"):
            configured_judgments(self.store, port=18742, environment={"REVIEW_TODAY_JEV_TEST": "yes"})

    def test_enabled_runtime_uses_existing_key_and_reports_auth_fallback_without_secret(self):
        requests = []
        def denied(request):
            requests.append(request)
            return httpx.Response(401)
        with httpx.Client(transport=httpx.MockTransport(denied)) as http, patch(
                "agent_service.jev_runtime.JevClient", side_effect=lambda key: JevClient(key, client=http)):
            engine = configured_judgments(self.store, port=18742, environment=self.environment)
            self.assertEqual(runtime_status(engine)["status"], "enabled")
            request = JudgmentRequest(node="test", state={"text": "合成测试"}, questions={"a": question("相关吗", {"yes": "相关", "no": "无关"})})
            engine.client.call(request)
            engine.client.call(request)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0].headers["Authorization"], "Bearer synthetic-private-key")
            self.assertEqual(runtime_status(engine)["status"], "authentication_disabled")
            self.assertNotIn("synthetic-private-key", json.dumps(runtime_status(engine)))
