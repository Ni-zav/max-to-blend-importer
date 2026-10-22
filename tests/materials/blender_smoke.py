# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic node-link smoke test, invoked ONLY within Blender 4.2+.

blender --background --factory-startup --python tests/materials/blender_smoke.py
No client meshes, MAX files, textures, licenses, or downloads.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "source"))
import bpy
from maxblend_core.materials import plan_material
from maxblend_core.materials.blender_nodes import build_material

assert bpy.app.version >= (4, 2, 0), "Requires Blender 4.2+"
image = bpy.data.images.new("synthetic_glossiness", width=2, height=2)
normal = bpy.data.images.new("synthetic_normal", width=2, height=2)
attrs = {
    "class": "PhysicalMtl", "name": "Deliberate duplicate",
    "params": {"diffuse": (0.1, 0.2, 0.3), "metallic": 0.5,
               "ior": 1.5, "roughness": 0.4, "opacity": 0.4,
               "transmission": 0.6, "coat": 0.2},
    "textures": {
        "glossmap": {"id": "tex:gloss", "kind": "bitmap", "state": "found"},
        "normalmap": {"id": "tex:normal", "kind": "bitmap", "state": "found"},
    },
}
result_a = build_material(plan_material("mat:a", attrs), {
    "tex:gloss": image, "tex:normal": normal})
attrs_b = {**attrs, "params": {**attrs["params"], "metallic": 0.1}}
result_b = build_material(plan_material("mat:b", attrs_b), {
    "tex:gloss": image, "tex:normal": normal})
assert result_a.material != result_b.material, "Material names must never conflate IDs"
assert result_a.material["maxblend.material_id"] == "mat:a"
assert result_b.material["maxblend.material_id"] == "mat:b"
assert "roughness" in result_a.linked_channels
assert "normal" in result_a.linked_channels
assert normal.colorspace_settings.name == "Non-Color"
nodes = list(result_a.material.node_tree.nodes)
assert any(node.type == "MATH" and node.operation == "SUBTRACT" for node in nodes)
shader = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
assert shader.inputs["Roughness"].is_linked
assert shader.inputs["Normal"].is_linked
assert abs(shader.inputs["Metallic"].default_value - 0.5) < 1e-6
assert abs(shader.inputs["IOR"].default_value - 1.5) < 1e-6
assert abs(shader.inputs["Alpha"].default_value - 0.4) < 1e-6
assert abs(shader.inputs["Coat Weight"].default_value - 0.2) < 1e-6
assert abs(shader.inputs["Transmission Weight"].default_value - 0.6) < 1e-6
missing = build_material(plan_material("mat:missing", {
    "class": "Physical", "params": {"base_color": (0.4, 0.4, 0.4)},
    "textures": {"bitmap": {"id": "tex:absent", "state": "missing"}},
}), {})
assert missing.status == "partial"
assert any(d.code == "unresolved_image" for d in missing.diagnostics)
print("F3 synthetic Blender real-node smoke PASS (not native MAX fidelity)")
