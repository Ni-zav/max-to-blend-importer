# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Wire projection and additional adversarial synthetic material regressions."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "source"))
from maxblend_core.materials import plan_material
from maxblend_core.materials.manifest import as_manifest_material


class WireTests(unittest.TestCase):
    def test_manifest_matches_frozen_material_shape(self):
        d = plan_material("mat:1", {"class": "CoronaPhysicalMtl", "params": {
            "base_color": (0.2, 0.3, 0.4), "transmission": 0.7,
            "coat": 0.2, "unsupported_feature": "not-implemented",
        }, "assignment_ids": ["obj:1"]})
        wire = as_manifest_material(d)
        self.assertEqual(set(wire), {"id", "original_class", "renderer",
                                     "assignment_ids", "pbr", "unknown_parameters",
                                     "coverage", "warnings"})
        self.assertEqual(wire["assignment_ids"], ["obj:1"])
        self.assertNotIn("coat", wire["pbr"])
        self.assertNotIn("transmission", wire["pbr"])
        self.assertEqual(wire["coverage"], "partial")
        self.assertTrue(wire["warnings"])
        self.assertTrue(all(set(w) == {"code", "severity", "reason", "evidence",
                                      "attribute", "before", "after"} for w in wire["warnings"]))

    def test_metadata_path_redaction_without_data_loss_in_plan(self):
        d = plan_material("mat:path", {"class": "PhysicalMtl", "params": {
            "roughness": 0.5, "unknown_path": "C:\\confidential\\texture.png",
            "unknown_mode": "multiply",
        }})
        self.assertEqual(d.source_parameters["unknown_path"], "C:\\confidential\\texture.png")
        unknown = {entry["name"]: entry for entry in as_manifest_material(d)["unknown_parameters"]}
        self.assertIsNone(unknown["unknown_path"]["value"])
        self.assertEqual(unknown["unknown_mode"]["value"], "multiply")

    def test_hostile_huge_int_and_bad_color(self):
        huge = 10 ** 10000
        d = plan_material("mat:hostile", {"class": "Physical", "params": {
            "ior": huge, "metallic": -12.0, "base_color": (0.2, float("inf"), 0.1),
        }})
        self.assertEqual(d.plan.coverage, "unknown")
        for key in ("ior", "metallic", "base_color"):
            self.assertIsNone(d.plan.pbr_slots[key])
        self.assertGreaterEqual(d.warning_counts["warning"], 3)

    def test_shared_rgba_image_uses_color_space_without_false_loss(self):
        detail = plan_material("mat:rgba_shared", {
            "class": "PhysicalMtl",
            "textures": {
                "bitmap": {"id": "tex:rgba", "kind": "bitmap", "state": "found"},
                "alpha": {"id": "tex:rgba", "kind": "bitmap", "state": "found",
                          "use_alpha": True},
            },
        })
        self.assertEqual([t.role for t in detail.textures], ["color", "color"])
        self.assertTrue(detail.textures[1].use_alpha)
        self.assertEqual(detail.plan.pbr_slots["opacity"]["texture_id"], "tex:rgba")
        self.assertEqual(detail.plan.coverage, "partial")
        self.assertIn("shader_links_unverified", {d.code for d in detail.plan.diagnostics})

    def test_missing_map_not_claimed_supported(self):
        detail = plan_material("mat:missing", {
            "class": "PhysicalMtl",
            "textures": {"bitmap": {"id": "tex:missing", "state": "missing"}},
        })
        self.assertNotEqual(detail.plan.coverage, "supported")
        self.assertIn("unresolved_texture", {d.code for d in detail.plan.diagnostics})

    def test_rgba_alpha_and_ambiguous_bump(self):
        d = plan_material("mat:rgba", {"class": "Physical", "params": {
            "base_color": (0.1, 0.2, 0.3, 0.25),
        }, "textures": {
            "bump": {"id": "tex:bump", "kind": "bitmap", "state": "found"},
            "transmap": {"id": "tex:opacity", "kind": "bitmap", "state": "found"},
        }})
        self.assertIsNone(d.plan.pbr_slots["opacity"]["value"])
        self.assertEqual({t.transform for t in d.textures}, {"ambiguous"})
        self.assertIn("rgba_alpha_ambiguous", {x.code for x in d.plan.diagnostics})
        self.assertEqual(d.plan.coverage, "partial")


if __name__ == "__main__":
    unittest.main()
