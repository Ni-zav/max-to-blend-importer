# SPDX-License-Identifier: GPL-2.0-or-later
"""I0 official-first/fork-first + strict importer and P0 v1 semantic smoke."""
from pathlib import Path
import importlib.util
import json
import math
import subprocess
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
assert addon.__version__ == "1.9.3", "Python package/extension identity drift"
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
        # Every ordinary install/API call is default-deny, before native IO.
        try:
            result = bpy.ops.import_scene.maxblend(
                filepath=str(bogus), use_image_search=False)
            assert result == {"CANCELLED"}, result
        except RuntimeError as error:
            assert "EXPERIMENTAL_IMPORT_ACK_REQUIRED" in str(error), str(error)
        assert len(bpy.data.objects) == before
        # Only an explicitly acknowledged, clean-Git experiment reaches the
        # actual constrained subprocess; bogus source must still fail closed.
        try:
            result = bpy.ops.import_scene.maxblend(
                filepath=str(bogus), use_image_search=False,
                experimental_ack=True)
            assert result == {"CANCELLED"}, result
        except RuntimeError as error:
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
    from maxblend_i0_smoke.maxblend_isolation import materialize, validate_response
    raw["objects"][0]["mesh"]["native_face_ids"] = [13]
    validated = validate_response(raw)
    replayed = materialize(validated, bpy.context)
    assert replayed["node_3"].type == 'MESH'
    assert replayed["node_3"]["maxblend.raw_face_material_ids"][0] == 13
    assert replayed["node_3"].data.polygons[0].material_index == 0
    expected_commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    session = capture(replayed, validated, context=bpy.context,
                      importer_commit=expected_commit)
    assert session.resolve("node_3") is replayed["node_3"]
    try:
        capture(replayed, validated, context=bpy.context,
                importer_commit="f" * 40 if expected_commit != "f" * 40 else "e" * 40)
    except ValueError as error:
        assert "IMPORTER_COMMIT_MISMATCH" in str(error)
    else:
        raise AssertionError("Spoofed importer commit accepted")
    scene = session.scene_manifest
    assert scene["schema_version"] == "maxblend.scene/v1"
    assert scene["status"] == "partial"
    assert scene["source"] == {
        "extension": "maxblend_importer_fork", "version": "1.9.3",
        "commit": expected_commit, "sha256": "a" * 64,
    }
    assert scene["objects"][0]["geometry"]["face_count"] == 1
    assert scene["objects"][0]["bounds_m"] is None
    assert scene["objects"][0]["local_matrix"] is None
    assert scene["objects"][0]["face_material_ids"] is None
    assert scene["source_units"]["meters_per_unit"] is None
    assert scene["axes"]["handedness"] == "UNKNOWN"
    print("F6 I0 Blender 4.2 smoke PASS: dual namespace, default deny, experimental subprocess rejection, partial manifest")
finally:
    addon.unregister()
