# SPDX-License-Identifier: GPL-2.0-or-later
"""I0 official-first/fork-first + strict importer and P0 v1 semantic smoke."""
from pathlib import Path
import importlib.util
import json
import math
import sys
import tempfile

import bpy
from mathutils import Matrix

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "maxblend_i0_smoke", root / "source/__init__.py",
    submodule_search_locations=[str(root / "source")])
assert spec and spec.loader
addon = importlib.util.module_from_spec(spec)
sys.modules["maxblend_i0_smoke"] = addon
spec.loader.exec_module(addon)
from maxblend_i0_smoke.maxblend_bridge import capture

class FakeOfficialMax(bpy.types.Operator):
    bl_idname = "import_scene.max"
    bl_label = "Official MAX registration fixture"
    def execute(self, context):
        return {'FINISHED'}


def test_dual_registration(first):
    try:
        if first == "official":
            bpy.utils.register_class(FakeOfficialMax)
            addon.register()
        else:
            addon.register()
            bpy.utils.register_class(FakeOfficialMax)
        assert bpy.ops.import_scene.max.get_rna_type().identifier == "IMPORT_SCENE_OT_max"
        assert bpy.ops.import_scene.maxblend.get_rna_type().identifier == "IMPORT_SCENE_OT_maxblend"
        assert addon.ImportMax.bl_idname != FakeOfficialMax.bl_idname
        assert addon.IO_FH_max.bl_import_operator == "import_scene.maxblend"
    finally:
        addon.unregister()
        assert bpy.ops.import_scene.max.get_rna_type().identifier == "IMPORT_SCENE_OT_max"
        bpy.utils.unregister_class(FakeOfficialMax)
        try:
            bpy.ops.import_scene.max.get_rna_type()
        except KeyError:
            pass
        else:
            raise AssertionError("Official simulator retained after unregister")


test_dual_registration("official")
test_dual_registration("fork")
addon.register()
try:
    with tempfile.TemporaryDirectory() as tmp:
        bogus = Path(tmp) / "never-execute.max"
        bogus.write_bytes(b"BOGUS!!!" + bytes(1536))
        before = len(bpy.data.objects)
        try:
            result = bpy.ops.import_scene.maxblend(filepath=str(bogus), use_image_search=False)
            assert result == {"CANCELLED"}, result
        except RuntimeError as error:
            # Blender bpy.ops raises for report({'ERROR'}) despite CANCELLED.
            assert "WORKER_FAILED_OR_RESOURCE_LIMIT" in str(error), str(error)
        assert len(bpy.data.objects) == before, "failed subprocess materialized objects"
    obmesh = bpy.data.meshes.new("Synthetic")
    obmesh.from_pydata([(0,0,0), (1,0,0), (0,1,0)], [], [(0,1,2)])
    obj = bpy.data.objects.new("Synthetic", obmesh)
    bpy.context.collection.objects.link(obj)
    obj["maxblend.node_id"] = "node_3"
    raw = {"schema": "maxblend.worker/v1", "status": "partial",
           "source_sha256": "a" * 64, "objects": [{
               "id": "node_3", "name": "Synthetic", "parent": None, "kind": "MESH",
               "world": [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1],
               "mesh": {"vertices": [[0,0,0],[1,0,0],[0,1,0]],
                        "faces": [[0,1,2]], "uv": []}}]}
    session = capture({"node_3": obj}, raw, context=bpy.context)
    assert session.resolve("node_3") is obj
    scene = session.scene_manifest
    assert scene["schema_version"] == "maxblend.scene/v1"
    assert scene["status"] == "partial"
    assert scene["source"]["sha256"] == "a" * 64
    assert scene["objects"][0]["geometry"]["face_count"] == 1
    assert scene["objects"][0]["bounds_m"] is None
    assert scene["objects"][0]["local_matrix"] is None
    assert scene["objects"][0]["face_material_ids"] is None
    assert scene["source_units"]["meters_per_unit"] is None
    assert scene["axes"]["handedness"] == "UNKNOWN"
    print("F6 I0 Blender 4.2 smoke PASS: official-first/fork-first, hostile worker reject, canonical partial session")
finally:
    addon.unregister()
