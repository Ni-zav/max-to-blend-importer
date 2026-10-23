# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute untrusted native MAX parsing in an isolated Blender process.

Invoked only by the F6 supervising worker. Never called by native scene files
or user scripts; --disable-autoexec and factory startup mandatory.
"""
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

import bpy
from mathutils import Matrix

MAX_OUTPUT = 24 * 1024 * 1024
MAX_OBJECTS = 512
MAX_VERTICES = 200_000
MAX_FACES = 300_000
MAX_LOOPS = 600_000


def load_addon():
    module_name = "maxblend_isolated_worker"
    directory = Path(__file__).parent
    spec = importlib.util.spec_from_file_location(
        module_name, directory / "__init__.py",
        submodule_search_locations=[str(directory)])
    if not spec or not spec.loader:
        raise ValueError("ADDON_NOT_FOUND")
    addon = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = addon
    spec.loader.exec_module(addon)
    return addon


def snapshot_objects(objects):
    if len(objects) > MAX_OBJECTS:
        raise ValueError("OBJECT_LIMIT")
    result = []
    verts = faces = loops = 0
    for obj in objects:
        source_id = obj.get("maxblend.node_id")
        if not isinstance(source_id, str) or not source_id.startswith("node_"):
            raise ValueError("MISSING_SOURCE_INDEX")
        if obj.type not in ("MESH", "EMPTY"):
            raise ValueError("UNSUPPORTED_OBJECT_KIND")
        parent = obj.parent.get("maxblend.node_id") if obj.parent else None
        world = [float(x) for row in obj.matrix_world for x in row]
        if any(not math.isfinite(x) for x in world):
            raise ValueError("NONFINITE_MATRIX")
        record = {
            "id": source_id, "parent": parent, "name": obj.name[:256],
            "kind": obj.type, "world": world, "mesh": None,
        }
        if obj.type == "MESH":
            mesh = obj.data
            vs = [list(v.co[:]) for v in mesh.vertices]
            fs = [list(poly.vertices) for poly in mesh.polygons]
            verts += len(vs)
            faces += len(fs)
            count = sum(len(face) for face in fs)
            loops += count
            if verts > MAX_VERTICES or faces > MAX_FACES or loops > MAX_LOOPS:
                raise ValueError("GEOMETRY_LIMIT")
            uv = []
            for layer in mesh.uv_layers:
                uv.append({
                    "name": layer.name[:64],
                    "coords": [[float(x) for x in item.uv] for item in layer.data],
                })
            if len(uv) > 16:
                raise ValueError("UV_LAYER_LIMIT")
            record["mesh"] = {"vertices": vs, "faces": fs, "uv": uv}
        result.append(record)
    return result


def main():
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) != 1:
        raise ValueError("WORKER_ARGS")
    request_path = Path(args[0])
    with request_path.open("rb") as fp:
        raw = fp.read(4096 + 1)
    if len(raw) > 4096:
        raise ValueError("REQUEST_TOO_LARGE")
    params = json.loads(raw.decode("utf-8"))
    source, target = params["source"], Path(params["output"])
    filter_set = set(params["filter"])
    if not filter_set.issubset({"UV", "MATERIAL", "EMPTY", "PRIMITIVE", "ARMATURE"}):
        raise ValueError("UNSAFE_FILTER")
    matrix = Matrix(params["global_matrix"])
    if any(not math.isfinite(float(x)) for row in matrix for x in row):
        raise ValueError("INVALID_MATRIX")
    addon = load_addon()
    from maxblend_isolated_worker import import_max
    # No texture root is authorized in this isolated MVP. Image decoding,
    # original renderer graphs, and external XRefs remain unsupported.
    import_max._texture_root = None
    import_max._strict_import = True
    existing = {obj.as_pointer() for obj in bpy.data.objects}
    report = import_max.read(
        bpy.context, source, matrix, filter_set,
        search=False, transform=True)
    # Legacy import may have created objects even on partially unsupported
    # data. Return only explicitly tagged/imported node IDs.
    added = [obj for obj in bpy.data.objects if obj.as_pointer() not in existing]
    if any("maxblend.node_id" not in obj for obj in added):
        raise ValueError("UNATTESTED_BLENDER_OBJECT")
    objects = snapshot_objects(added)
    if report.status == "failed":
        raise ValueError("IMPORT_FAILED")
    import hashlib
    sha256 = getattr(report, "source_sha256", None)
    if not isinstance(sha256, str) or len(sha256) != 64:
        raise ValueError("SOURCE_HASH_MISSING")
    payload = {
        "schema": "maxblend.worker/v1",
        "status": "partial" if objects else "unsupported",
        "source_sha256": sha256,
        "objects": objects,
        "warnings": ["SOURCE_UNITS_UNVERIFIED", "MATERIALS_NOT_REPLAYED",
                     "NATIVE_SEMANTICS_UNVERIFIED"],
    }
    encoded = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_OUTPUT:
        raise ValueError("WORKER_OUTPUT_TOO_LARGE")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as fp:
        fp.write(encoded)
        fp.flush()
        os.fsync(fp.fileno())


if __name__ == "__main__":
    main()
