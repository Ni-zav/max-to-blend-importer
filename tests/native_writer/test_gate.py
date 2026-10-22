# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic-only tests: no .max file, renderer, network, or Autodesk runtime."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.native_max_writer.gate import GATES, MINIMAL_TARGET, assess  # noqa: E402


class GateTests(unittest.TestCase):
    def test_default_fails_closed(self):
        report = assess({})
        self.assertEqual(report["decision"], "no_go")
        self.assertFalse(report["native_export_enabled"])
        self.assertTrue(all(state == "not_run" for state in report["gates"].values()))

    def test_evidence_order_does_not_change_digest(self):
        a = assess({"cfb_structure": "pass", "native_stream_layout": "not_run"})
        b = assess({"native_stream_layout": "not_run", "cfb_structure": "pass"})
        self.assertEqual(a["evidence_sha256"], b["evidence_sha256"])
        self.assertEqual(len(a["evidence_sha256"]), 64)
        self.assertEqual(a["checksum_scope"], "normalized_claims_only_not_max_file")

    def test_bad_states_fail_closed(self):
        for value in ("success", "PASS", True, 1, [], "../../secret.max", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                assess({"cfb_structure": value})

    def test_unrecognized_gate_does_not_get_serialized(self):
        with self.assertRaises(ValueError):
            assess({"client_file": "/private/studio.max"})

    def test_self_parser_cannot_satisfy_independent_gate(self):
        with self.assertRaises(ValueError):
            assess({"independent_open": "pass"}, consumer_kind="own_parser",
                   tested_version="2023")

    def test_independent_claim_requires_specific_release(self):
        with self.assertRaises(ValueError):
            assess({"independent_open": "pass"}, consumer_kind="independent_reader")

    def test_native_resave_without_open_rejected(self):
        with self.assertRaises(ValueError):
            assess({"authorized_native_resave": "pass"},
                   consumer_kind="authorized_native_max", tested_version="2023")

    def test_semantic_pass_needs_schema_and_class_registry(self):
        with self.assertRaises(ValueError):
            assess({"mesh_semantics": "pass"})

    def test_independent_reader_does_not_count_as_native_max(self):
        with self.assertRaises(ValueError):
            assess({"independent_open": "pass", "authorized_native_open": "pass"},
                   consumer_kind="independent_reader", tested_version="2023")

    def test_synthetic_independent_reader_is_not_production_support(self):
        claims = {key: "pass" for key in GATES[:8]}
        report = assess(claims, consumer_kind="independent_reader", tested_version="2023")
        self.assertEqual(report["decision"], "authorized_native_validation_required")
        self.assertFalse(report["native_export_enabled"])

    def test_mock_all_pass_still_needs_manual_review(self):
        # A synthetic claim is NOT an actual independent test result.
        claims = {key: "pass" for key in GATES}
        report = assess(claims, consumer_kind="authorized_native_max", tested_version="2023")
        self.assertEqual(report["decision"], "manual_release_review_required")
        self.assertFalse(report["native_export_enabled"])

    def test_any_failed_gate_makes_no_go(self):
        claims = {key: "pass" for key in GATES}
        claims["material_semantics"] = "fail"
        report = assess(claims, consumer_kind="authorized_native_max", tested_version="2023")
        self.assertEqual(report["decision"], "no_go")

    def test_malformed_version_rejected(self):
        for version in ("/home/client", "../../foo", "", "a" * 64):
            with self.subTest(version=version), self.assertRaises(ValueError):
                assess({}, tested_version=version)

    def test_minimal_target_is_exactly_one_triangle_transformed(self):
        m = MINIMAL_TARGET["local_to_world_row_major"]
        for local, world in zip(MINIMAL_TARGET["vertices_local_m"],
                                MINIMAL_TARGET["expected_world_vertices_m"]):
            self.assertEqual(tuple(sum(m[row][j] * local[j] for j in range(3)) + m[row][3]
                                   for row in range(3)), world)
        self.assertEqual(MINIMAL_TARGET["triangles"], ((0, 1, 2),))
        self.assertEqual(len(MINIMAL_TARGET["single_material_rgba_linear"]), 4)


if __name__ == "__main__":
    unittest.main()
