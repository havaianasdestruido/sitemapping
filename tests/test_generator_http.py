import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_generator_with_fake_requests():
    fake_requests = types.ModuleType("requests")

    class RequestException(Exception):
        pass

    fake_requests.RequestException = RequestException
    fake_requests.get = lambda *args, **kwargs: None
    spec = importlib.util.spec_from_file_location("generate_report_http_test", ROOT / "scripts/generate_report.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token", "GITHUB_ACTOR": "test-user"}), patch.dict(
        sys.modules, {"requests": fake_requests}
    ):
        spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class GeneratorHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = load_generator_with_fake_requests()

    def setUp(self):
        self.generator.API_ERRORS.clear()

    def test_request_refuses_untrusted_origins_before_sending_credentials(self):
        get = Mock()
        with patch.object(self.generator.requests, "get", get):
            result = self.generator.safe_request("https://attacker.example/collect")
        self.assertEqual(result, [])
        get.assert_not_called()
        self.assertEqual(self.generator.API_ERRORS[-1]["status"], "blocked_untrusted_url")
        self.assertNotIn("attacker.example", self.generator.API_ERRORS[-1]["url"])

    def test_get_uses_a_bounded_timeout_and_auth_header(self):
        get = Mock(return_value=FakeResponse(200, {"ok": True}))
        with patch.object(self.generator.requests, "get", get):
            result = self.generator.safe_request("https://api.github.com/test")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(get.call_args.kwargs["timeout"], (5, 30))
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "token test-token")

    def test_transient_network_error_is_retried(self):
        get = Mock(side_effect=[self.generator.requests.RequestException("temporary"), FakeResponse(200, [])])
        with patch.object(self.generator.requests, "get", get), patch.object(self.generator.time, "sleep"):
            result = self.generator.safe_request("https://api.github.com/test")
        self.assertEqual(result, [])
        self.assertEqual(get.call_count, 2)
        self.assertEqual(self.generator.API_ERRORS, [])

    def test_transient_server_error_is_retried(self):
        get = Mock(side_effect=[FakeResponse(503, text="unavailable"), FakeResponse(200, [1])])
        with patch.object(self.generator.requests, "get", get), patch.object(self.generator.time, "sleep"):
            result = self.generator.safe_request("https://api.github.com/test")
        self.assertEqual(result, [1])
        self.assertEqual(get.call_count, 2)

    def test_invalid_json_is_reported_and_returns_empty_data(self):
        get = Mock(return_value=FakeResponse(200, ValueError("bad JSON")))
        with patch.object(self.generator.requests, "get", get):
            result = self.generator.safe_request("https://api.github.com/test")
        self.assertEqual(result, [])
        self.assertEqual(self.generator.API_ERRORS[-1]["status"], "invalid_json")

    def test_untrusted_markdown_cannot_add_autolinks_or_emphasis(self):
        escaped = self.generator.esc("https://outside.example **bold**")
        self.assertIn(r"https\:\/\/outside\.example", escaped)
        self.assertNotIn("**", escaped)

    def test_code_spans_are_valid_for_empty_and_backtick_values(self):
        self.assertEqual(self.generator.code_span(""), "—")
        self.assertEqual(self.generator.code_span("has `tick"), "``has `tick``")

    def test_markdown_links_and_images_use_strict_host_allowlists(self):
        self.assertIsNotNone(self.generator.safe_markdown_url("https://github.com/owner/repo"))
        self.assertIsNone(self.generator.safe_markdown_url("https://github.com.evil.test/owner/repo"))
        self.assertIsNone(self.generator.safe_markdown_url("https://user:pass@github.com/owner/repo"))
        self.assertEqual(self.generator.md_link("label", "javascript:alert(1)"), "label")
        self.assertNotIn("](<", self.generator.md_link("label", "https://outside.example/"))
        self.assertEqual(self.generator.md_image("avatar", "https://github.com/owner/repo"), "")

    def test_profile_failure_stops_before_generating_a_new_report(self):
        with patch.object(self.generator, "safe_request", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "existing report and exports were left untouched"):
                self.generator.build_report()

    def test_atomic_write_keeps_previous_file_when_writer_fails(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text("previous", encoding="utf-8")

            def fail_after_partial_write(handle):
                handle.write("partial")
                raise RuntimeError("simulated interruption")

            with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                self.generator.atomic_write(str(path), fail_after_partial_write)
            self.assertEqual(path.read_text(encoding="utf-8"), "previous")
            self.assertEqual(list(Path(directory).glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
