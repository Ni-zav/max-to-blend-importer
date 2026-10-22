# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real Blender 4.2+ node-link smoke with *synthetic, in-memory* images only.

blender --background --factory-startup --disable-autoexec --python tests/materials/blender_smoke.py

No private MAX scenes, textures, path resolution or external services.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "source"))
import bpy
from maxblend_core.materials import plan_material
from maxblend_core.materials.blender_nodes import build_material

assert bpy.app.version >= (4, 2, 0), "Blender 4.2+ required"

# F4 would normally authorize and supply these image objects. In this test,
# image buffers are generated in Blender memory; no filesystem is consulted.
albedo = bpy.data.images.new("F3_synthetic_rgba", width=2, height=2, alpha=True)
gloss = bpy.data.images.new("F3_synthetic_gloss", width=2, height=2)
normal_image = bpy.data.images.new("F3_synthetic_normal", width=2, height=2)
images = {"tex:albedo": albedo, "tex:gloss": gloss, "tex:normal": normal_image}
params = {
    "base_color": (0.1, 0.2, 0.3),
    "roughness": 0.4, "metallic": 0.5, "opacity": 0.4,
    "ior": 1.5, "transmission": 0.6, "coat": 0.2,
}
attrs = {
    "class": "PhysicalMtl", "name": "Synthetic duplicate surface",
    "params": params,
    "textures": {
        "bitmap": {"id": "tex:albedo", "kind": "bitmap", "state": "found"},
        "alpha": {"id": "tex:albedo", "kind": "bitmap", "state": "found",
                  "use_alpha": True},
        "glossmap": {"id": "tex:gloss", "kind": "bitmap", "state": "found"},
        "normalmap": {"id": "tex:normal", "kind": "bitmap", "state": "found"},
    },
}
first = build_material(plan_material("mat:a", attrs), images)
second = build_material(plan_material("mat:b", {
    **attrs, "params": {**params, "metallic": 0.1},
}), images)

assert first.material is not second.material, "Name collision must never merge distinct material IDs"
assert first.material["maxblend.material_id"] == "mat:a"
assert second.material["maxblend.material_id"] == "mat:b"
assert first.status == "partial", "Scalar/map blending evidence cannot claim full renderer fidelity"
assert set(("base_color", "roughness", "normal", "opacity")).issubset(first.linked_channels)
assert not any(d.code == "conflicting_color_space" for d in first.diagnostics)
assert gloss.colorspace_settings.name == "Non-Color"
assert normal_image.colorspace_settings.name == "Non-Color"

nodes = tuple(first.material.node_tree.nodes)
shader = next(node for node in nodes if node.type == "BSDF_PRINCIPLED")
assert len(tuple(first.material.node_tree.links)) >= 7, "Expect BSDF, color, alpha, gloss, normal links"
for channel in ("Base Color", "Alpha", "Roughness", "Normal"):
    assert shader.inputs[channel].is_linked, f"Missing real {channel} shader link"
base_link = shader.inputs["Base Color"].links[0]
assert base_link.from_node.type == "TEX_IMAGE"
assert base_link.from_socket.name == "Color"
assert base_link.from_node.image is albedo
alpha_link = shader.inputs["Alpha"].links[0]
assert alpha_link.from_node.type == "TEX_IMAGE"
assert alpha_link.from_socket.name == "Alpha", "Must not substitute RGB grayscale for PNG alpha"
assert alpha_link.from_node.image is albedo
roughness_link = shader.inputs["Roughness"].links[0]
assert roughness_link.from_node.type == "MATH"
assert roughness_link.from_node.operation == "SUBTRACT"
assert abs(roughness_link.from_node.inputs[0].default_value - 1.0) < 1e-6
assert roughness_link.from_node.inputs[1].is_linked
assert roughness_link.from_node.inputs[1].links[0].from_node.image is gloss
normal_link = shader.inputs["Normal"].links[0]
assert normal_link.from_node.type == "NORMAL_MAP"
assert normal_link.from_node.inputs["Color"].is_linked
assert normal_link.from_node.inputs["Color"].links[0].from_node.image is normal_image
for socket, value in (("Metallic", 0.5), ("IOR", 1.5),
                      ("Coat Weight", 0.2), ("Transmission Weight", 0.6)):
    assert abs(shader.inputs[socket].default_value - value) < 1e-6, socket

missing = build_material(plan_material("mat:missing", {
    "class": "Physical", "params": {"base_color": (0.4, 0.4, 0.4)},
    "textures": {"bitmap": {"id": "tex:absent", "state": "missing"}},
}), {})
assert missing.status == "partial"
assert "base_color" not in missing.linked_channels
assert any(d.code == "unresolved_image" for d in missing.diagnostics)
unknown = build_material(plan_material("mat:unknown", {
    "class": "ImaginaryRendererShader", "name": "preview only",
}), {})
assert unknown.status == "unsupported"
assert any(d.code == "preview_only" for d in unknown.diagnostics)
print("PASS: F3 synthetic Blender 4.2+ linked node smoke (NOT native MAX conversion)")
