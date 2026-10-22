# SPDX-License-Identifier: GPL-2.0-or-later
"""F6 synthetic Blender 4.2 import/build/registration smoke; no client MAX file."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile

import bpy
from mathutils import Matrix

root = Path(__file__).resolve().parents[2]
package = "maxblend_w2_smoke"
spec = importlib.util.spec_from_file_location(
    package, root / "source/__init__.py", submodule_search_locations=[str(root / "source")])
assert spec and spec.loader
addon = importlib.util.module_from_spec(spec)
sys.modules[package] = addon
spec.loader.exec_module(addon)
from maxblend_w2_smoke import import_max
from maxblend_w2_smoke.maxblend_runtime import ImportReport, ImportRejected
from maxblend_core.geometry import reconstruct_editable_mesh, MapChunk
from maxblend_core.materials import plan_material
from maxblend_core.materials.blender_nodes import build_material

addon.register()
try:
    assert bpy.ops.import_scene.max.get_rna_type().identifier == "IMPORT_SCENE_OT_max"
    # Real Blender mesh datablock with per-loop UV seam and raw MAX face IDs.
    verts = [(0, 0, 0), (2, 0, 0), (2, 3, 0), (0, 3, 0)]
    v = struct.pack("<I", 4) + b"".join(struct.pack("<3f", *p) for p in verts)
    f = struct.pack("<I", 2) + b"".join(
        struct.pack("<3IIHH", *face, 7, 3, mid)
        for face, mid in [((0, 1, 2), 1), ((0, 2, 3), 12)])
    uvxyz = struct.pack("<I", 5) + b"".join(struct.pack("<3f", *p) for p in [
        (0, 0, 0), (1, 0, 0), (1, 1, 0), (.4, .4, 0), (0, 1, 0)])
    uvidx = struct.pack("<I", 2) + struct.pack("<6I", 0, 1, 2, 3, 2, 4)
    reconstruction = reconstruct_editable_mesh("synthetic", v, f,
                                              maps=[MapChunk(1, uvxyz, uvidx, "triangles")])
    assert reconstruction.mesh is not None
    class Node:
        def get_first(self, _typ):
            return None
    import_max._import_report = ImportReport()
    obj = import_max._create_planned_shape(
        bpy.context, ("", {"UV"}, False), Node(), None, reconstruction)
    assert len(obj.data.polygons) == 2
    assert len(obj.data.uv_layers) == 1
    assert tuple(obj.data.polygons[0].vertices) == (0, 1, 2)
    assert tuple(obj.data.polygons[1].vertices) == (0, 2, 3)
    assert tuple(float(x) for x in obj.data.uv_layers[0].data[0].uv) == (0.0, 0.0)
    assert abs(obj.data.uv_layers[0].data[3].uv[0] - .4) < .00001
    assert "NATIVE_FACE_MATERIAL_IDS_UNMAPPED" in import_max._import_report.warnings
    detail = plan_material("mat_synthetic", {
        "class": "Physical", "name": "Synthetic", "params": {
            "base_color": (0.2, 0.3, 0.4), "roughness": 0.4, "ior": 1.45}})
    built = build_material(detail, bpy_module=bpy)
    obj.data.materials.append(built.material)
    assert obj.data.materials[0].node_tree.nodes.get("Principled BSDF") is not None
    # Actual Blender parent/child regression with same display names: parent
    # scale and global coordinate conversion must apply *once*, including
    # negative determinant and nonuniform scale. IDs, never names, bind links.
    parent_obj = bpy.data.objects.new("Repeated", None)
    child_obj = bpy.data.objects.new("Repeated", None)
    bpy.context.collection.objects.link(parent_obj)
    bpy.context.collection.objects.link(child_obj)
    scale_mirror = Matrix.Diagonal((2.0, 3.0, -1.0, 1.0))
    local_parent = Matrix.Translation((5.0, 0.0, 0.0)) @ scale_mirror
    local_child = Matrix.Translation((2.0, 0.0, 0.0))
    parent_world = local_parent
    child_world = parent_world @ local_child
    def matrix_tuple(value):
        return tuple(tuple(float(x) for x in row) for row in value)
    import_max._apply_import_transforms(
        bpy.context, {"node_child": child_obj, "node_parent": parent_obj},
        {"node_parent": None, "node_child": "node_parent"},
        {"node_parent": matrix_tuple(local_parent), "node_child": matrix_tuple(local_child)},
        {"node_parent": matrix_tuple(parent_world), "node_child": matrix_tuple(child_world)},
        ["node_parent", "node_child"], Matrix.Scale(2.0, 4), True)
    expected = Matrix.Scale(2.0, 4) @ child_world
    assert child_obj.parent is parent_obj
    assert max(abs(child_obj.matrix_world[i][j] - expected[i][j])
               for i in range(4) for j in range(4)) < 1e-5
    assert child_obj.matrix_world.determinant() < 0
    import_max._apply_import_transforms(
        bpy.context, {"node_child": child_obj, "node_parent": parent_obj},
        {"node_parent": None, "node_child": "node_parent"},
        {"node_parent": matrix_tuple(local_parent), "node_child": matrix_tuple(local_child)},
        {"node_parent": matrix_tuple(parent_world), "node_child": matrix_tuple(child_world)},
        ["node_parent", "node_child"], Matrix.Scale(2.0, 4), False)
    assert abs(child_obj.matrix_world[0][0] - 2.0) < 1e-5
    assert abs(child_obj.matrix_world.translation.x) < 1e-5
    # Restoring verified basis must be idempotent.
    import_max._apply_import_transforms(
        bpy.context, {"node_child": child_obj, "node_parent": parent_obj},
        {"node_parent": None, "node_child": "node_parent"},
        {"node_parent": matrix_tuple(local_parent), "node_child": matrix_tuple(local_child)},
        {"node_parent": matrix_tuple(parent_world), "node_child": matrix_tuple(child_world)},
        ["node_parent", "node_child"], Matrix.Scale(2.0, 4), True)
    assert max(abs(child_obj.matrix_world[i][j] - expected[i][j])
               for i in range(4) for j in range(4)) < 1e-5
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "invalid.max"
        bad.write_bytes(b"INVALID!" + bytes(2048))
        before = len(bpy.data.objects)
        try:
            import_max.read(bpy.context, str(bad), Matrix.Identity(4),
                            {"MATERIAL", "UV"}, False, True)
        except ImportRejected:
            pass
        else:
            raise AssertionError("Malformed MAX accepted")
        assert len(bpy.data.objects) == before
        outcome = json.loads(bpy.context.scene["maxblend_last_import_report"])
        assert outcome["status"] == "failed"
        assert "invalid.max" not in json.dumps(outcome)
    print("F6 Blender 4.2 synthetic smoke PASS: operator, F1 nested mirrored world, F2 UV/material IDs, F3 nodes, F5 reject")
finally:
    addon.unregister()
