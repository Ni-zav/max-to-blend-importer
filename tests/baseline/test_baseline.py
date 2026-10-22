# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Dependency-free tests. None of these establish actual .max conversion fidelity."""
import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "source"))
from maxblend_core import interfaces as api  # noqa: E402


class InterfaceTests(unittest.TestCase):
    def test_import_without_blender(self):
        self.assertNotIn("bpy", sys.modules)
        self.assertEqual(api.MaterialPlan("mat").coverage, "unknown")
        self.assertEqual(api.TransformPlan().world_matrix, None)
        self.assertEqual(api.TextureReference("brick.png").color_space_role, "unknown")

    def test_frozen_plans(self):
        plan = api.GeometryPlan("id", vertex_count=None)
        with self.assertRaises(FrozenInstanceError):
            plan.vertex_count = 10

    def test_explicit_evidence(self):
        diagnostic = api.Diagnostic("UNVERIFIED", "No scene fixture", "warning")
        self.assertIsNone(diagnostic.evidence)
        self.assertEqual(diagnostic.status, "partial")

    def test_protocol_methods_exist(self):
        for spec in (
            api.TransformPlanner, api.GeometryPlanner, api.MaterialPlanner,
            api.TextureResolver, api.ContainerProbe, api.SceneNodePlanner,
            api.InstancePlanner,
        ):
            self.assertIn("plan" if spec not in (api.TextureResolver, api.ContainerProbe) else
                          ("resolve" if spec is api.TextureResolver else "probe"), spec.__dict__)


class UpstreamCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addon = ast.parse((ROOT / "source/__init__.py").read_text(encoding="utf-8"))
        cls.parser = ast.parse((ROOT / "source/import_max.py").read_text(encoding="utf-8"))

    def test_manifest_identifiers_unchanged(self):
        manifest = tomllib.loads((ROOT / "source/blender_manifest.toml").read_text())
        self.assertEqual(manifest["id"], "io_scene_max")
        self.assertEqual(manifest["version"], "1.9.2")
        self.assertEqual(manifest["blender_version_min"], "4.2.0")

    def test_existing_operator_cli_properties_preserved(self):
        operators = [node for node in self.addon.body if isinstance(node, ast.ClassDef)
                     and node.name == "ImportMax"]
        self.assertEqual(len(operators), 1)
        items = {node.targets[0].id for node in operators[0].body
                 if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}
        self.assertTrue({"bl_idname", "scale_objects", "use_image_search",
                         "object_filter", "use_collection", "use_apply_matrix"}.issubset(items))
        assert_id = next(node.value.value for node in operators[0].body
                         if isinstance(node, ast.Assign)
                         and any(isinstance(target, ast.Name) and target.id == "bl_idname"
                                 for target in node.targets))
        self.assertEqual(assert_id, "import_scene.max")

    def test_no_nonexistent_export_handler(self):
        handler, = [node for node in self.addon.body
                    if isinstance(node, ast.ClassDef) and node.name == "IO_FH_max"]
        assigns = {target.id for node in handler.body if isinstance(node, ast.Assign)
                   for target in node.targets if isinstance(target, ast.Name)}
        self.assertNotIn("bl_export_operator", assigns)
        self.assertIn("bl_import_operator", assigns)

    def test_dispatch_seam_falls_back_to_legacy(self):
        functions = {node.name: node for node in self.parser.body
                     if isinstance(node, ast.FunctionDef)}
        self.assertIn("read_scene", functions)
        self.assertIn("_dispatch_scene_import", functions)
        self.assertIn("read", functions)
        dispatcher_calls = [node.func.id for node in ast.walk(functions["_dispatch_scene_import"])
                            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        self.assertEqual(dispatcher_calls, ["read_scene"])
        read_calls = [node.func.id for node in ast.walk(functions["read"])
                      if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        self.assertIn("_dispatch_scene_import", read_calls)
        self.assertNotIn("read_scene", read_calls)


if __name__ == "__main__":
    unittest.main()
