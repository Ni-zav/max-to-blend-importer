# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Entirely synthetic, offline tests. These do NOT measure native MAX fidelity."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "source"))
from maxblend_core.materials import MaterialPlannerV1, plan_material
from maxblend_core.materials.blender_nodes import socket_names


def codes(detail):
    return {warning.code for warning in detail.plan.diagnostics}


class MaterialPlannerTests(unittest.TestCase):
    def test_standard_and_physical_table(self):
        cases = [
            ("StandardMtl", {"diffuse": (0.2, 0.3, 0.4), "glossines": 0.75,
                             "opacity": 0.3, "refraction": 1.5},
             "partial", 0.25, 0.3, 1.5),
            ("PhysicalMtl", {"base_color": [0.6, 0.4, 0.2], "roughness": 0.2,
                             "metalness": 0.9, "ior": 1.45, "transmission": 0.5,
                             "coat_weight": 0.4},
             "supported", 0.2, None, 1.45),
        ]
        for family, params, coverage, roughness, opacity, ior in cases:
            with self.subTest(family=family):
                detail = plan_material("mat:1", {"class": family, "params": params})
                self.assertEqual(detail.plan.coverage, coverage)
                slots = detail.plan.pbr_slots
                self.assertAlmostEqual(slots["roughness"]["value"], roughness)
                self.assertAlmostEqual(slots["ior"]["value"], ior)
                self.assertEqual(slots["opacity"]["value"] if slots["opacity"] else None, opacity)
                self.assertIn("coat", slots)
                self.assertNotIn("coat", detail.manifest_pbr())
                self.assertEqual(set(detail.manifest_pbr()), {
                    "base_color", "roughness", "metallic", "normal",
                    "opacity", "ior", "emission",
                })

    def test_renderer_specific_mapping_is_partial(self):
        cases = [
            ("VRayMtl", {"diffuse": (0.9, 0.5, 0.2), "refl_glossiness": 0.1,
                          "metalness": 0.7, "refraction_ior": 1.55}),
            ("CoronaMtl", {"diffuse": (0.5, 0.4, 0.3), "glossiness": 0.8,
                            "transparency": 0.2, "ior": 1.33}),
            ("CoronaPhysicalMtl", {"base_color": (0.5, 0.6, 0.7), "roughness": 0.3,
                                    "metallic": 0.6, "coat": 0.1}),
        ]
        for family, params in cases:
            with self.subTest(family=family):
                detail = plan_material("mat:renderer", {"class": family, "params": params})
                self.assertEqual(detail.plan.coverage, "partial")
                self.assertIn("renderer_shader_approximation", codes(detail))
                self.assertIn(detail.plan.renderer, ("V-Ray", "Corona"))
                self.assertIsNotNone(detail.plan.pbr_slots["base_color"])

    def test_native_multisub_ids_are_not_blender_indices(self):
        detail = plan_material("mat:multi", {
            "class": "Multi/Sub-Object", "name": "Wall",
            "submaterials": {1: "mat:wall", 5: "mat:trim", 18: "mat:glass"},
            "assignment_ids": ["obj:1", "obj:2"],
        })
        self.assertEqual(detail.submaterial_ids, ((1, "mat:wall"), (5, "mat:trim"), (18, "mat:glass")))
        self.assertEqual(detail.assignment_ids, ("obj:1", "obj:2"))
        self.assertEqual(detail.plan.coverage, "partial")
        self.assertIn("composite_shader_loss", codes(detail))

    def test_names_do_not_define_material_identity(self):
        a = plan_material("mat:first", {"class": "Physical", "name": "Chrome",
                                         "params": {"metallic": 1.0}})
        b = plan_material("mat:second", {"class": "Physical", "name": "Chrome",
                                          "params": {"metallic": 0.0}})
        self.assertEqual(a.display_name, b.display_name)
        self.assertNotEqual(a.plan.material_id, b.plan.material_id)
        self.assertNotEqual(a.plan.pbr_slots["metallic"], b.plan.pbr_slots["metallic"])

    def test_invalid_and_high_ior(self):
        for bad in (0, -1, 0.5, 1001, float("nan"), float("inf"), "1.5", True):
            with self.subTest(bad=str(bad)):
                result = plan_material("mat:ior", {"class": "Physical",
                                                    "params": {"ior": bad}})
                self.assertIsNone(result.plan.pbr_slots["ior"])
                self.assertIn("invalid_ior" if isinstance(bad, (float, int)) and
                              not isinstance(bad, bool) and bad == bad and
                              bad not in (float("inf"),) else "invalid_parameter", codes(result))
        high = plan_material("mat:high", {"class": "Physical", "params": {"ior": 5.0}})
        self.assertEqual(high.plan.pbr_slots["ior"]["value"], 5.0)
        self.assertIn("unusual_ior", codes(high))

    def test_texture_intent_and_missing_texture(self):
        material = plan_material("mat:tex", {"class": "VRayMtl", "textures": {
            "bitmap": {"id": "tex:diffuse", "kind": "bitmap", "state": "found"},
            "glossmap": {"id": "tex:gloss", "kind": "bitmap", "state": "missing"},
            "normalmap": {"id": "tex:normal", "kind": "bitmap", "state": "found"},
        }})
        self.assertEqual(material.plan.pbr_slots["base_color"]["texture_id"], "tex:diffuse")
        self.assertEqual(material.plan.pbr_slots["roughness"]["texture_id"], "tex:gloss")
        self.assertEqual(next(t for t in material.textures if t.channel == "roughness").transform, "invert")
        self.assertEqual(next(t for t in material.textures if t.channel == "normal").role, "data")
        self.assertIn("unresolved_texture", codes(material))

    def test_procedural_and_unmapped_parameters_are_lossy(self):
        detail = plan_material("mat:proc", {"class": "CoronaPhysical", "params": {
            "base_color": (0.2, 0.4, 0.6), "falloff_curve": "nonlinear",
        }, "textures": {
            "diffuse": {"id": "tex:falloff", "kind": "procedural", "state": "found"},
        }})
        self.assertIn("unsupported_procedural_map", codes(detail))
        self.assertIn("unmapped_parameter", codes(detail))
        self.assertEqual(detail.unknown_parameters, (("falloff_curve", "nonlinear"),))
        self.assertEqual(detail.plan.coverage, "partial")

    def test_alpha_is_not_ior_or_transmission(self):
        opaque = plan_material("mat:a", {"class": "Physical", "params": {
            "transparency": 0.7, "refraction": 1.51}})
        self.assertAlmostEqual(opaque.plan.pbr_slots["opacity"]["value"], 0.3)
        self.assertEqual(opaque.plan.pbr_slots["ior"]["value"], 1.51)
        self.assertIsNone(opaque.plan.pbr_slots["transmission"])
        direct = plan_material("mat:b", {"class": "Physical", "params": {
            "opacity": 0.25, "transparency": 0.7}})
        self.assertEqual(direct.plan.pbr_slots["opacity"]["value"], 0.25)

    def test_double_sided_and_layered_are_not_silent(self):
        a = plan_material("mat:two", {"class": "VRay2Sided", "front_id": "mat:front",
                                       "back_id": "mat:back"})
        b = plan_material("mat:layered", {"class": "CoronaLayeredMtl",
                                           "layer_ids": ["mat:base", "mat:coat"]})
        self.assertTrue(a.two_sided)
        self.assertIn("distinct_backface_shader", codes(a))
        self.assertEqual(b.layer_ids, ("mat:base", "mat:coat"))
        self.assertEqual(b.plan.coverage, "partial")

    def test_unknown_material_is_not_supported(self):
        a = plan_material("mat:unknown", {"class": "UnknownPlugin", "name": "Silver"})
        self.assertEqual(a.plan.coverage, "unsupported")
        self.assertIn("unsupported_material_class", codes(a))
        b = plan_material("mat:empty", {"class": "PhysicalMtl", "name": "Silver"})
        self.assertEqual(b.plan.coverage, "unknown")
        self.assertIn("no_shader_evidence", codes(b))

    def test_hostile_parameters_are_not_evaluated(self):
        marker = {"run": "never"}
        result = plan_material("mat:hostile", {"class": "Physical", "params": {
            "script": marker, "roughness": float("nan"), "nested": [[1, 2]],
        }})
        self.assertIsNone(result.source_parameters["script"])
        self.assertIsNone(result.plan.pbr_slots["roughness"])
        self.assertIn("unreadable_parameter", codes(result))
        for invalid in ("../asset", "", "a" * 97):
            with self.assertRaises(ValueError):
                plan_material(invalid, {"class": "Physical"})

    def test_interface_and_versioned_sockets(self):
        plan = MaterialPlannerV1().plan("mat:id", {
            "class": "Physical", "params": {"metallic": 0.2}})
        self.assertEqual(plan.material_id, "mat:id")
        self.assertEqual(socket_names("coat", (4, 2, 0))[0], "Coat Weight")
        self.assertEqual(socket_names("coat", (3, 6, 0))[0], "Clearcoat")
        self.assertEqual(socket_names("transmission", (4, 2, 0))[0], "Transmission Weight")
        self.assertEqual(socket_names("emission", (3, 6, 0))[0], "Emission")


if __name__ == "__main__":
    unittest.main()
