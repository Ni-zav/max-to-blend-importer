# SPDX-License-Identifier: GPL-2.0-or-later
"""F6 I0 Linux isolation, untrusted JSON validation and timeout tests."""
from pathlib import Path
import importlib
import math
import os
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[2] / "source"
sys.path.insert(0, str(ROOT))
PACKAGE = "test_f6_package"
if PACKAGE not in sys.modules:
    module = types.ModuleType(PACKAGE)
    module.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = module
isolation = importlib.import_module(PACKAGE + ".maxblend_isolation")
ImportRejected = isolation.ImportRejected  # same package-qualified exception class


def object_record(node_id="node_0", parent=None):
    return {"id": node_id, "parent": parent, "name": "synthetic",
            "kind": "MESH", "world": [1, 0, 0, 0, 0, 1, 0, 0,
                                      0, 0, 1, 0, 0, 0, 0, 1],
            "mesh": {"vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                     "faces": [[0, 1, 2]], "uv": []}}


class ValidationTests(unittest.TestCase):
    def test_valid_partial_synthetic_shape(self):
        result = {"schema": "maxblend.worker/v1", "status": "partial",
                  "source_sha256": "a" * 64, "objects": [object_record()]}
        self.assertIs(isolation.validate_response(result), result)

    def test_no_success_or_unknown_schema(self):
        for v in ("success", "unknown", None):
            with self.subTest(v=v), self.assertRaises(ImportRejected):
                isolation.validate_response({"schema": "maxblend.worker/v1",
                                             "status": v, "objects": []})

    def test_duplicate_cycle_and_missing_parent(self):
        for objs in ([object_record(), object_record()],
                     [object_record("node_0", "node_1"),
                      object_record("node_1", "node_0")],
                     [object_record("node_0", "node_999")]):
            with self.subTest(objs=objs), self.assertRaises(ImportRejected):
                isolation.validate_response({"schema": "maxblend.worker/v1",
                                             "status": "partial", "objects": objs})

    def test_oversized_and_hostile_payloads(self):
        obj = object_record()
        obj["world"][0] = float("nan")
        with self.assertRaises(ImportRejected):
            isolation.validate_response({"schema": "maxblend.worker/v1",
                                         "status": "partial", "objects": [obj]})
        obj = object_record()
        obj["mesh"]["faces"] = [[0, 1, 200]]
        with self.assertRaises(ImportRejected):
            isolation.validate_response({"schema": "maxblend.worker/v1",
                                         "status": "partial", "objects": [obj]})
        obj = object_record()
        obj["mesh"]["uv"] = [{"name": "uv", "coords": [[0, 0]]}]
        with self.assertRaises(ImportRejected):
            isolation.validate_response({"schema": "maxblend.worker/v1",
                                         "status": "partial", "objects": [obj]})

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux constrained worker only")
    def test_worker_timeout_kills_process(self):
        with self.assertRaisesRegex(ImportRejected, "WORKER_WALLTIME_EXCEEDED"):
            isolation.run_worker([sys.executable, "-c",
                                  "import time; time.sleep(10)"], timeout=0.2)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux constrained worker only")
    def test_worker_resource_limits_applied(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "marker"
            code = ("import resource,pathlib;"
                    "assert resource.getrlimit(resource.RLIMIT_CPU)[0] == 20;"
                    "assert resource.getrlimit(resource.RLIMIT_FSIZE)[0] == 33554432;"
                    f"pathlib.Path({str(marker)!r}).write_text('ok')")
            isolation.run_worker([sys.executable, "-c", code], timeout=5)
            self.assertEqual(marker.read_text(), "ok")

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux constrained worker only")
    def test_no_shell_arguments(self):
        with self.assertRaises(ImportRejected):
            isolation.run_worker(["python\x00malicious", "-c", "pass"])


if __name__ == "__main__":
    unittest.main()
