import csv
import json
import re
import unittest
from datetime import datetime
from urllib.parse import urlsplit
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


class ReportExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata = json.loads((REPORTS / "metadata.json").read_text(encoding="utf-8"))

    def test_metadata_matches_every_json_export(self):
        self.assertEqual(self.metadata["schemaVersion"], 1)
        self.assertTrue(self.metadata["profile"]["login"])
        self.assertTrue(self.metadata["generatedAt"].endswith("Z"))
        datetime.fromisoformat(self.metadata["generatedAt"].replace("Z", "+00:00"))

        json_exports = {path.stem for path in REPORTS.glob("*.json") if path.name != "metadata.json"}
        self.assertEqual(json_exports, set(self.metadata["counts"]))
        for category, expected_count in self.metadata["counts"].items():
            with self.subTest(category=category):
                records = json.loads((REPORTS / f"{category}.json").read_text(encoding="utf-8"))
                self.assertIsInstance(records, list)
                self.assertEqual(len(records), expected_count)

    def test_csv_and_jsonl_files_have_matching_record_counts(self):
        for category, expected_count in self.metadata["counts"].items():
            with self.subTest(category=category):
                jsonl_path = REPORTS / f"{category}.jsonl"
                jsonl_rows = [line for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line]
                self.assertEqual(len(jsonl_rows), expected_count)
                for line in jsonl_rows:
                    self.assertIsInstance(json.loads(line), dict)

                csv_path = REPORTS / f"{category}.csv"
                with csv_path.open(newline="", encoding="utf-8") as handle:
                    csv_rows = list(csv.DictReader(handle))
                self.assertEqual(len(csv_rows), expected_count)

    def test_webmcp_uses_bounded_allowlisted_tools(self):
        source = (ROOT / "assets/js/site.js").read_text(encoding="utf-8")
        for name in (
            "get_site_overview",
            "search_repositories",
            "get_repository_details",
            "search_report",
            "get_dataset_page",
        ):
            with self.subTest(tool=name):
                self.assertIn(f'name: "{name}"', source)
        self.assertIn("readOnlyHint: true", source)
        self.assertIn("untrustedContentHint: true", source)
        self.assertIn('credentials: "omit"', source)
        self.assertIn('mode: "same-origin"', source)
        self.assertIn("additionalProperties: false", source)

    def test_site_pages_have_csp_and_no_inline_scripts(self):
        for page_name in ("index.html", "webmcp.html", "_layouts/default.html"):
            page = (ROOT / page_name).read_text(encoding="utf-8")
            with self.subTest(page=page_name):
                self.assertIn("Content-Security-Policy", page)
                self.assertIn("script-src 'self'", page)
                self.assertNotRegex(page, r"(?is)<script\b(?![^>]*\bsrc\s*=)[^>]*>")
                self.assertNotRegex(page, r"(?i)\son[a-z]+\s*=")

    def test_current_markdown_report_has_no_active_markup_or_untrusted_hosts(self):
        report = (ROOT / "REPORT.md").read_text(encoding="utf-8")
        self.assertNotRegex(report, r"(?i)<\s*(script|iframe|object|embed|form|svg)\b")
        urls = re.findall(r"\]\(\s*<?(https?://[^)>]+)", report)
        self.assertTrue(urls)
        allowed_hosts = {
            "github.com",
            "avatars.githubusercontent.com",
            "objects.githubusercontent.com",
            "release-assets.githubusercontent.com",
        }
        for url in urls:
            with self.subTest(url=url[:120]):
                self.assertIn(urlsplit(url.rstrip(">")).hostname, allowed_hosts)


if __name__ == "__main__":
    unittest.main()
