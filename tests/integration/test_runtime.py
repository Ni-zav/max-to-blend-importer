# SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic F6 security and integration-port regression; no customer files."""
import ast
import io
from pathlib import Path
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "source"
sys.path.insert(0, str(SOURCE))
from maxblend_runtime import ImportRejected, ImportReport, preflight_bytes, checked_bytes  # noqa: E402


class ImportBoundaryTests(unittest.TestCase):
    def test_malformed_and_zip_containers_rejected(self):
        for blob in (b"", b"INVALID!", b"PK\\x03\\x04" + bytes(1024),
                     b"\\xd0\\xcf\\x11\\xe0\\xa1\\xb1\\x1a\\xe1" + bytes(1024)):
            with self.subTest(blob=blob[:8]), self.assertRaises(ImportRejected):
                preflight_bytes(blob)

    def test_untrusted_path_is_not_accepted_as_bytes(self):
        with self.assertRaises(ImportRejected):
            preflight_bytes("/not-a-max")
        with self.assertRaises(ImportRejected):
            preflight_bytes(b"INVALID!", max_bytes=4)

    def test_reject_symlink_and_nonregular(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            target = path / "dummy.max"
            target.write_bytes(b"INVALID!")
            alias = path / "alias.max"
            alias.symlink_to(target)
            with self.assertRaises(ImportRejected):
                checked_bytes(str(alias))
            with self.assertRaises(ImportRejected):
                checked_bytes(str(path))
            with self.assertRaises(ImportRejected):
                checked_bytes(str(target))

    def test_reports_are_path_free_and_status_nonfictional(self):
        report = ImportReport()
        report.warn("MATERIAL_PARTIAL")
        report.warn("/private/source/file.max")
        obj = report.as_dict()
        self.assertEqual(obj["status"], "partial")
        self.assertNotIn("/private", str(obj))
        self.assertFalse(obj["native_max_export"])
        self.assertFalse(obj["source_units_verified"])

    def test_dispatch_still_has_only_legacy_reader_port(self):
        code = (SOURCE / "import_max.py").read_text()
        tree = ast.parse(code)
        functions = {f.name: f for f in tree.body if isinstance(f, ast.FunctionDef)}
        self.assertIn("_dispatch_scene_import", functions)
        self.assertIn("_make_scene_verified", functions)
        self.assertIn("checked_bytes(", code)
        self.assertNotIn("export_scene.max", code)


if __name__ == "__main__":
    unittest.main()
