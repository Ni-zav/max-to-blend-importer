# SPDX-License-Identifier: GPL-2.0-or-later
"""I0 exact importer identity/commit and adversarial provenance regressions.

Only the F6 repository's own public checkout is consulted. No MAX input,
customer metadata, or network access is needed.
"""
from pathlib import Path
import importlib
import os
import subprocess
import sys
import tempfile
import tomllib
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "source"
sys.path.insert(0, str(SOURCE))
PACKAGE = "f6_contract_identity"
if PACKAGE not in sys.modules:
    stub = types.ModuleType(PACKAGE)
    stub.__path__ = [str(SOURCE)]
    sys.modules[PACKAGE] = stub
bridge = importlib.import_module(PACKAGE + ".maxblend_bridge")

FORK_ID = "maxblend_importer_fork"
FORK_VERSION = "1.9.3"


class ImporterIdentityTests(unittest.TestCase):
    def test_manifest_and_python_version_exact_match(self):
        manifest = tomllib.loads((SOURCE / "blender_manifest.toml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["id"], FORK_ID)
        self.assertEqual(manifest["version"], FORK_VERSION)
        import ast
        syntax = ast.parse((SOURCE / "__init__.py").read_text(encoding="utf-8"))
        versions = [n.value.value for n in syntax.body
                    if isinstance(n, ast.Assign)
                    and isinstance(n.value, ast.Constant)
                    and any(isinstance(t, ast.Name) and t.id == "__version__"
                            for t in n.targets)]
        self.assertEqual(versions, [FORK_VERSION])

    def test_clean_checkout_attests_exact_head(self):
        actual = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
        self.assertRegex(actual, r"^[a-f0-9]{40}$")
        self.assertEqual(bridge._verified_checkout_commit(actual), actual)
        self.assertEqual(bridge._verified_checkout_commit(), actual)

    def test_wrong_rev_and_untrusted_values_rejected(self):
        for wrong in ("not-a-sha", "", None if False else " "):
            with self.subTest(value=wrong), self.assertRaises(ValueError):
                bridge._verified_checkout_commit(wrong)
        actual = bridge._verified_checkout_commit()
        mismatched = "a" * 40 if actual != "a" * 40 else "b" * 40
        with self.assertRaisesRegex(ValueError, "IMPORTER_COMMIT_MISMATCH"):
            bridge._verified_checkout_commit(mismatched)

    def test_missing_git_metadata_fails_closed(self):
        with tempfile.TemporaryDirectory() as stage:
            simulated = Path(stage) / "source"
            simulated.mkdir()
            with mock.patch.object(bridge, "__file__", str(simulated / "maxblend_bridge.py")):
                with self.assertRaisesRegex(ValueError, "IMPORTER_CHECKOUT_UNATTESTED"):
                    bridge._verified_checkout_commit()

    def test_tampered_extension_identity_fails_closed(self):
        old_load = bridge.tomllib.loads
        def spoof_manifest(raw):
            result = old_load(raw)
            result["id"] = "io_scene_max"
            return result
        with mock.patch.object(bridge.tomllib, "loads", side_effect=spoof_manifest):
            with self.assertRaisesRegex(ValueError, "IMPORTER_PACKAGE_VERSION_MISMATCH"):
                bridge._verified_checkout_commit()

    def test_tracked_source_modified_fails_closed(self):
        original_run = bridge.subprocess.run
        def simulated_dirty(*args, **kwargs):
            argv = args[0]
            if "status" in argv:
                return subprocess.CompletedProcess(argv, 0, b" M source/maxblend_bridge.py\n", b"")
            return original_run(*args, **kwargs)
        with mock.patch.object(bridge.subprocess, "run", side_effect=simulated_dirty):
            with self.assertRaisesRegex(ValueError, "IMPORTER_SOURCE_DIRTY"):
                bridge._verified_checkout_commit()

    def test_canonical_source_importer_not_input_suffix(self):
        sha = bridge._verified_checkout_commit()
        settings = types.SimpleNamespace(system="NONE", scale_length=1.0,
                                         length_unit="DEFAULT")
        ctx = types.SimpleNamespace(scene=types.SimpleNamespace(unit_settings=settings))
        response = {"schema": "maxblend.worker/v1", "status": "partial",
                    "source_sha256": "d" * 64, "objects": []}
        doc = bridge.canonical_scene({}, response, context=ctx, importer_commit=sha)
        self.assertEqual(doc["schema_version"], "maxblend.scene/v1")
        self.assertEqual(doc["status"], "partial")
        self.assertEqual(doc["source"], {
            "extension": FORK_ID, "version": FORK_VERSION,
            "commit": sha, "sha256": "d" * 64,
        })
        self.assertIsNone(doc["source_units"]["meters_per_unit"])
        self.assertEqual(doc["axes"]["handedness"], "UNKNOWN")
        mismatch = "e" * 40 if sha != "e" * 40 else "f" * 40
        with self.assertRaisesRegex(ValueError, "IMPORTER_COMMIT_MISMATCH"):
            bridge.canonical_scene({}, response, context=ctx, importer_commit=mismatch)
        for digest in (".max", "no", "0" * 63):
            with self.subTest(digest=digest), self.assertRaisesRegex(ValueError, "INVALID_SOURCE_DIGEST"):
                bridge.canonical_scene({}, dict(response, source_sha256=digest),
                                       context=ctx, importer_commit=sha)


if __name__ == "__main__":
    unittest.main()
