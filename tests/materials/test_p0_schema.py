# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Validate the F3 output with the *actual* frozen P0 material schema.

Invoke from an authorized checkout with:
  MAXBLEND_P0_SCHEMA=/path/to/3dsmax-to-blender/schemas/scene-manifest-v1.schema.json \
    PYTHONPATH=source python -m unittest discover -s tests/materials -p 'test_*.py' -v

This test deliberately SKIPS without the live P0 schema; no copied schema or
mock interface is a substitute for an independently frozen contract.
"""
from pathlib import Path
import json
import os
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "source"))

from maxblend_core import interfaces as f0
from maxblend_core.materials import plan_material
from maxblend_core.materials.manifest import as_manifest_material

try:
    import jsonschema
except ImportError:
    jsonschema = None


class FrozenInterfaceTests(unittest.TestCase):
    def test_planner_returns_actual_f0_contract(self):
        result = plan_material("mat:api", {
            "class": "PhysicalMtl", "params": {"base_color": (0.2, 0.3, 0.4)},
        })
        self.assertIsInstance(result.plan, f0.MaterialPlan)
        self.assertEqual(set(result.manifest_pbr()), {
            "base_color", "roughness", "metallic", "normal", "opacity",
            "ior", "emission",
        })


@unittest.skipUnless(os.environ.get("MAXBLEND_P0_SCHEMA"), "P0 SCHEMA NOT PROVIDED (NOT RUN)")
@unittest.skipUnless(jsonschema is not None, "jsonschema NOT INSTALLED (NOT RUN)")
class RealP0SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(os.environ["MAXBLEND_P0_SCHEMA"])
        if not cls.source.is_file():
            raise AssertionError("Expected frozen P0 schema file not found")
        cls.schema = json.loads(cls.source.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(cls.schema)
        cls.material_schema = cls.schema["properties"]["materials"]["items"]
        cls.validator = jsonschema.Draft202012Validator(cls.material_schema)

    def test_exact_p0_material_record_semantics(self):
        sample = plan_material("mat:physical", {
            "class": "PhysicalMtl", "name": "synthetic P0 material",
            "params": {"base_color": (0.1, 0.2, 0.3), "roughness": 0.4,
                       "opacity": 0.5, "ior": 1.45,
                       "unmapped_toggle": True, "unmapped_label": "synthetic"},
            "assignment_ids": ["obj:synthetic"],
            "textures": {
                "bitmap": {"id": "tex:synthetic", "state": "missing", "kind": "bitmap"}
            },
        })
        record = as_manifest_material(sample)
        self.assertEqual(list(self.validator.iter_errors(record)), [])
        self.assertEqual(set(record["pbr"]), {
            "base_color", "roughness", "metallic", "normal", "opacity",
            "ior", "emission",
        })
        self.assertEqual(record["pbr"]["base_color"]["value"], [0.1, 0.2, 0.3])
        self.assertEqual(record["pbr"]["base_color"]["provenance"]["method"], "native")
        self.assertEqual(record["pbr"]["base_color"]["texture_id"], "tex:synthetic")
        self.assertTrue(any(w["code"] == "unresolved_texture" for w in record["warnings"]))
        self.assertEqual(record["coverage"], "partial")
        self.assertTrue(all(len(w["code"]) <= 64 for w in record["warnings"]))

    def test_unsupported_renderer_and_unknown_parameters_are_wire_safe(self):
        sample = plan_material("mat:unknown", {
            "class": "Unrecognised", "params": {
                "custom_intensity": 3, "metadata_path": "C:\\synthetic\\private.png",
                "oversize": "x" * 513, "boolean": False,
            }
        })
        record = as_manifest_material(sample)
        self.assertEqual(list(self.validator.iter_errors(record)), [])
        self.assertEqual(record["coverage"], "unsupported")
        self.assertTrue(any(w["code"] == "unsupported_material_class" for w in record["warnings"]))
        unknown = {p["name"]: p for p in record["unknown_parameters"]}
        self.assertIsNone(unknown["metadata_path"]["value"])
        self.assertIsNone(unknown["oversize"]["value"])
        self.assertEqual(unknown["boolean"]["value"], False)

    def test_named_map_reference_keeps_schema_safe_id(self):
        sample = plan_material("mat:tex", {
            "class": "VRayMtl",
            "textures": {"bitmap": {"id": "tex:synthetic", "state": "found"}},
        })
        record = as_manifest_material(sample)
        self.assertEqual(list(self.validator.iter_errors(record)), [])
        self.assertEqual(record["pbr"]["base_color"]["texture_id"], "tex:synthetic")
        self.assertEqual(record["coverage"], "partial")
        self.assertTrue(record["warnings"], "Partial texture recovery must have loss evidence")


if __name__ == "__main__":
    unittest.main()
