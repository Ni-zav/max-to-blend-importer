# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic offline tests against the frozen P0 texture item schema snapshot."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "source"))
from maxblend_core.interfaces import Diagnostic  # noqa: E402
from maxblend_core.textures.resolver import ResolutionDetail  # noqa: E402
from maxblend_core.textures.projection import project_texture_v1  # noqa: E402

SCHEMA = json.loads((Path(__file__).parent / "fixtures/p0_texture_item.schema.json").read_text(encoding="utf-8"))


def validate_shape(test, record):
    """Enforce the P0 fixture's exact keys, enums, bounds and warning layout with stdlib."""
    test.assertEqual(set(record), set(SCHEMA["required"]))
    test.assertFalse(SCHEMA["additionalProperties"])
    for name, schema in SCHEMA["properties"].items():
        value = record[name]
        if "enum" in schema:
            test.assertIn(value, schema["enum"])
        if "anyOf" in schema:
            test.assertIn("null" if value is None else "string", {v["type"] for v in schema["anyOf"]})
        if "pattern" in schema and value is not None:
            test.assertRegex(value, schema["pattern"])
        if isinstance(value, str):
            test.assertGreaterEqual(len(value), schema.get("minLength", 0))
            test.assertLessEqual(len(value), schema.get("maxLength", 2**32))
    p = SCHEMA["properties"]["provenance"]
    test.assertEqual(set(record["provenance"]), set(p["required"]))
    test.assertFalse(p["additionalProperties"])
    test.assertIn(record["provenance"]["method"], p["properties"]["method"]["enum"])
    ev = record["provenance"]["evidence"]
    test.assertTrue(ev is None or (1 <= len(ev) <= 512))
    w = SCHEMA["properties"]["warnings"]
    test.assertLessEqual(len(record["warnings"]), w["maxItems"])
    for warning in record["warnings"]:
        test.assertEqual(set(warning), set(w["items"]["required"]))
        test.assertFalse(w["items"]["additionalProperties"])
        for key, schema in w["items"]["properties"].items():
            value = warning[key]
            if "enum" in schema:
                test.assertIn(value, schema["enum"])
            if "pattern" in schema and value is not None:
                test.assertRegex(value, schema["pattern"])
            if "anyOf" in schema:
                test.assertIn("null" if value is None else "string", {v["type"] for v in schema["anyOf"]})
            if isinstance(value, str):
                test.assertGreaterEqual(len(value), schema.get("minLength", 0))
                test.assertLessEqual(len(value), schema.get("maxLength", 2**32))
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return  # stdlib shape checks above remain mandatory without P0 dependency
    Draft202012Validator.check_schema(SCHEMA)
    Draft202012Validator(SCHEMA).validate(record)


class ProjectionTests(unittest.TestCase):
    def project(self, detail, **kwargs):
        result = project_texture_v1(detail, stable_id="tex:stable-1", provenance_method="native", **kwargs)
        validate_shape(self, result)
        return result

    def test_fixture_is_exact_p0_texture_shape(self):
        self.assertIn("976b084ba6b357756872911bdb3de483cd8cff51", SCHEMA["$comment"])
        self.assertEqual(set(SCHEMA["required"]), {"id", "source_ref", "path_status", "channel",
                         "color_space_role", "sha256", "provenance", "warnings"})

    def test_hash_and_path_redaction(self):
        detail = ResolutionDetail("found", "private/nested/a.png", "base_color", "color",
                                  "a" * 64, "/confidential/customer/a.png")
        record = self.project(detail, provenance_evidence="verified_chunk")
        self.assertIsNone(record["source_ref"])
        self.assertEqual(record["sha256"], "a" * 64)
        self.assertNotIn("confidential", json.dumps(record))
        self.assertEqual(self.project(detail, publish_basename=True)["source_ref"], "a.png")

    def test_reject_untrusted_opt_in_source(self):
        for path in ("../../private.png", "C:/private.png", "//host/share.png", "https://x/a.png"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.project(ResolutionDetail("blocked", path, None, "unknown"), publish_basename=True)

    def test_failed_states_never_retain_digest(self):
        for status in ("missing", "blocked", "ambiguous"):
            with self.subTest(status=status):
                value = self.project(ResolutionDetail(status, "a.png", "normal", "data", "b" * 64))
                self.assertEqual(value["path_status"], status)
                self.assertIsNone(value["sha256"])

    def test_warning_schema_and_no_leaks(self):
        diag = Diagnostic("HASH_COLLISION", "C:/customer/private/file.png", "warning", "secret")
        value = self.project(ResolutionDetail("ambiguous", "a.png", "normal", "data", diagnostics=(diag,)))
        self.assertEqual(value["warnings"][0]["code"], "hash_collision")
        self.assertNotIn("customer", json.dumps(value))
        self.assertIsNone(value["warnings"][0]["evidence"])
        unknown = Diagnostic("C:/private/secret", "client-name", "warning", "/some/root")
        value = self.project(ResolutionDetail("blocked", "a.png", None, "unknown", diagnostics=(unknown,)))
        self.assertEqual(value["warnings"][0]["code"], "unverified_texture_diagnostic")
        self.assertNotIn("client-name", json.dumps(value))

    def test_role_mismatch_visible_not_rewritten(self):
        value = self.project(ResolutionDetail("found", "normal.png", "normal", "color", "a" * 64))
        self.assertEqual(value["color_space_role"], "color")
        self.assertIn("color_space_mismatch", [w["code"] for w in value["warnings"]])

    def test_channel_roles(self):
        for slot, role in (("base_color", "color"), ("emission", "color"), ("normal", "data"),
                           ("roughness", "data"), ("metallic", "data"), ("opacity", "data")):
            with self.subTest(slot=slot):
                self.assertEqual(self.project(ResolutionDetail("found", "a.png", slot, role, "a" * 64))["warnings"], [])

    def test_caller_supplied_identity_and_evidence_required(self):
        detail = ResolutionDetail("missing", "a.png", None, "unknown")
        for bad in ("", "1bad", "bad space", "C:/private", "z" * 97):
            with self.subTest(id=bad), self.assertRaises(ValueError):
                project_texture_v1(detail, stable_id=bad, provenance_method="native")
        for bad in ("C:/secret", "private value", "https://host", "z" * 97):
            with self.subTest(evidence=bad), self.assertRaises(ValueError):
                self.project(detail, provenance_evidence=bad)
        with self.assertRaises(ValueError):
            project_texture_v1(detail, stable_id="tex-1", provenance_method="unspecified")

    def test_invalid_status_channel_role_and_hash_rejected(self):
        for d in (ResolutionDetail("invalid", "a.png", None, "unknown"),
                  ResolutionDetail("found", "a.png", "normal", "data", "garbage"),
                  ResolutionDetail("found", "a.png", "../../secret", "data"),
                  ResolutionDetail("found", "a.png", "normal", "linear")):
            with self.subTest(state=d.state), self.assertRaises(ValueError):
                self.project(d)

    def test_warning_count_capped(self):
        diag = Diagnostic("MISSING_TEXTURE", "missing", "warning")
        with self.assertRaises(ValueError):
            self.project(ResolutionDetail("missing", "a.png", None, "unknown", diagnostics=(diag,) * 10000))


if __name__ == "__main__":
    unittest.main()
