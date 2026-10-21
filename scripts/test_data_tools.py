#!/usr/bin/env python3
"""Offline unit tests for source acquisition and temporal synthetic fixture checks."""
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("download_datasets", HERE / "download_datasets.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class MockHTTP(io.BytesIO):
    def __init__(self, data: bytes, content_type="application/json"):
        super().__init__(data)
        self.headers = {"Content-Type": content_type}


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old = mod.ROOT
        mod.ROOT = self.root

    def tearDown(self):
        mod.ROOT = self.old
        self.tmp.cleanup()

    def test_zip_download_and_hash(self):
        mem = io.BytesIO()
        with zipfile.ZipFile(mem, "w") as z:
            z.writestr("sales.csv", "sku,date,units\nA,2020-01-01,3\n")
        payload = mem.getvalue()
        with patch.object(mod.urllib.request, "urlopen", return_value=MockHTTP(payload, "application/zip")):
            result = mod.download_binary("https://example.org/sample.zip", self.root / "data/a.zip")
        self.assertEqual(result["bytes"], len(payload))
        self.assertEqual(len(result["sha256"]), 64)
        self.assertTrue(zipfile.is_zipfile(self.root / "data/a.zip"))

    def test_html_fails_archive_validation(self):
        with patch.object(mod.urllib.request, "urlopen", return_value=MockHTTP(b"<html>blocked</html>", "text/html")):
            with self.assertRaises(ValueError):
                mod.download_binary("https://example.org/data.zip", self.root / "data/b.zip")
        self.assertFalse((self.root / "data/b.zip").exists())

    def test_worldbank_complete(self):
        rows = [{"contract_id": "WB-1"}]
        with patch.object(mod, "request_json", return_value={"data": rows}):
            result = mod.world_bank_fetch({"download_url": "https://example.org/?a=1", "source_url": "https://example.org"},
                                          self.root / "data/awards.jsonl", 0)
        self.assertEqual(result["rows"], 1)
        self.assertTrue(result["complete"])
        self.assertEqual(json.loads((self.root / "data/awards.jsonl").read_text().strip())["contract_id"], "WB-1")

    def test_m5_requires_explicit_license_ack(self):
        with self.assertRaises(PermissionError):
            mod.m5_fetch(self.root / "m5", False)

    def test_ted_bounded_response(self):
        payload = {"notices": [{"publication-number": "123456-2026", "notice-title": {"eng": ["Test notice"]}}]}
        with patch.object(mod.urllib.request, "urlopen", return_value=MockHTTP(json.dumps(payload).encode())):
            result = mod.ted_fetch({"download_url": "https://example.org/search"},
                                   self.root / "knowledge/notices.jsonl", 'FT~"pumps"', 2)
        self.assertEqual(result["rows"], 1)
        self.assertTrue(result["complete"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
