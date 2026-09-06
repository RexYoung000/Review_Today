import unittest
from unittest.mock import patch
from agent_service import model_capabilities as capabilities
from agent_service.service_diagnostics import diagnose
from agent_service.openai_client import ModelCallError


class ServiceRecoveryTests(unittest.TestCase):
    def states(self, transient=True):
        return {
            "router": dict(model="luna", status="unavailable", category="access_denied", retryable=False),
            "coach": dict(model="terra", status="unavailable", category="connection", retryable=transient),
            "risk": dict(model="sol", status="unavailable", category="unsupported", retryable=False),
        }

    def test_access_denied_is_not_network_and_diagnostics_are_allowlisted(self):
        error = ModelCallError("PROVIDER", "HTTP 403", request_id="req_abc")
        error.body = "secret key and provider html"
        result = diagnose(error)
        self.assertEqual(result["category"], "access_denied")
        self.assertFalse(result["retryable"])
        self.assertEqual(result["request_id"], "req_abc")
        self.assertNotIn("secret", str(result))

    def test_transient_roles_retry_without_reprobing_access_denied(self):
        states = self.states()
        with patch.object(capabilities, "_state", states), patch.object(capabilities, "_probing", False), patch.object(capabilities, "_scheduler_started", True), patch.object(capabilities.threading, "Thread") as thread:
            capabilities.start_probe(reset=False)
        self.assertEqual(thread.call_args.kwargs["args"], (["coach"],))
        self.assertEqual(states["router"]["status"], "unavailable")
        self.assertEqual(states["coach"]["status"], "checking")

    def test_backoff_is_10_30_120_and_stops_for_nontransient_errors(self):
        with patch.object(capabilities, "_state", self.states()), patch.object(capabilities, "probe"), patch.object(capabilities, "_retry_attempt", 0), patch.object(capabilities, "_next_probe", 0), patch.object(capabilities.time, "time", return_value=100):
            for expected in [110, 130, 220, 220]:
                capabilities.probe_with_streaming()
                self.assertEqual(capabilities._next_probe, expected)
            capabilities._state["coach"]["retryable"] = False
            capabilities.probe_with_streaming()
            self.assertEqual(capabilities._next_probe, 0)

    def test_manual_probe_is_single_flight(self):
        with patch.object(capabilities, "_probing", True), patch.object(capabilities.threading, "Thread") as thread:
            capabilities.start_probe()
        thread.assert_not_called()

    def test_stream_transport_failure_retries_only_affected_role(self):
        states = self.states()
        states["coach"].update(status="ready", retryable=False)
        with patch.object(capabilities, "_state", states), patch.object(capabilities, "probe"), \
             patch.object(capabilities, "_retry_attempt", 0), patch.object(capabilities, "_next_probe", 0), \
             patch.object(capabilities.time, "time", return_value=100), \
             patch.object(capabilities, "model_stream_capability", side_effect=ModelCallError("CONNECTION")):
            capabilities.probe_with_streaming()
            self.assertEqual(capabilities._next_probe, 110)
            self.assertTrue(states["coach"]["stream_retryable"])
            self.assertFalse(states["router"]["retryable"])
