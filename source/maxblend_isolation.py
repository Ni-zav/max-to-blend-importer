# SPDX-License-Identifier: GPL-2.0-or-later
"""F6 isolated Blender subprocess; no scene parser/bitmap decoder in parent.

Linux/POSIX fail-closed isolation, not a hardened OS sandbox. No shell or
network use. One private request and one bounded response per invocation.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile

from .maxblend_runtime import ImportRejected, ImportReport

MAX_RESPONSE = 24 * 1024 * 1024
MAX_OBJECTS = 512
MAX_VERTICES = 200_000
MAX_FACES = 300_000
MAX_UV_LOOPS = 600_000
_ID = re.compile(r"^node_[0-9]{1,8}$")


def _limits():
    if os.name != "posix" or not hasattr(os, "setsid"):
        raise ImportRejected("ISOLATED_WORKER_LINUX_ONLY")
    import sys
    if not sys.platform.startswith("linux"):
        raise ImportRejected("ISOLATED_WORKER_LINUX_ONLY")
    try:
        import resource
        for key in ("RLIMIT_AS", "RLIMIT_CPU", "RLIMIT_FSIZE", "RLIMIT_CORE"):
            if not hasattr(resource, key):
                raise ImportRejected("WORKER_LIMITS_UNAVAILABLE")
    except ImportError:
        raise ImportRejected("WORKER_LIMITS_UNAVAILABLE") from None
    return resource


def _worker_limits(resource):
    # Bound virtual memory, CPU time, output size; walltime in supervising host.
    # Set before exec of untrusted parser. This does not provide syscall or
    # network namespace confinement and is NOT a security certification.
    for key, soft, hard in (
        ("RLIMIT_AS", 8 * 1024**3, 8 * 1024**3),
        ("RLIMIT_CPU", 20, 22),
        ("RLIMIT_FSIZE", 32 * 1024**2, 32 * 1024**2),
        ("RLIMIT_CORE", 0, 0),
    ):
        resource.setrlimit(getattr(resource, key), (soft, hard))


def run_worker(argv, *, timeout=30, cwd=None, env=None):
    """Trusted argv only; timeout kills whole worker process group."""
    resource = _limits()
    if not isinstance(argv, (list, tuple)) or not argv or any(
            not isinstance(x, str) or "\x00" in x for x in argv):
        raise ImportRejected("WORKER_ARGUMENTS_INVALID")
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
        raise ImportRejected("WORKER_TIMEOUT_INVALID")
    try:
        process = subprocess.Popen(
            list(argv), cwd=cwd, env=env, shell=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
            preexec_fn=lambda: _worker_limits(resource),
            close_fds=True)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise ImportRejected("WORKER_START_FAILED") from None
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise ImportRejected("WORKER_WALLTIME_EXCEEDED") from None
    if code != 0:
        raise ImportRejected("WORKER_FAILED_OR_RESOURCE_LIMIT") from None
    return code


def _read_private(path: Path):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), "rb") as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_RESPONSE:
            raise ImportRejected("WORKER_RESPONSE_SIZE_INVALID")
        data = f.read(MAX_RESPONSE + 1)
    if len(data) > MAX_RESPONSE:
        raise ImportRejected("WORKER_RESPONSE_TOO_LARGE")
    try:
        return json.loads(data.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError):
        raise ImportRejected("WORKER_RESPONSE_INVALID_JSON") from None


def validate_response(response):
    """Validate caps/schema before materializing any Blender data."""
    if not isinstance(response, dict) or response.get("schema") != "maxblend.worker/v1":
        raise ImportRejected("WORKER_SCHEMA_INVALID")
    if response.get("status") not in ("partial", "unsupported", "failed"):
        raise ImportRejected("WORKER_STATUS_INVALID")
    digest = response.get("source_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ImportRejected("WORKER_SOURCE_DIGEST_INVALID")
    objects = response.get("objects")
    if not isinstance(objects, list) or len(objects) > MAX_OBJECTS:
        raise ImportRejected("WORKER_OBJECT_LIMIT")
    identifiers = set()
    total_vertices = total_faces = total_loops = 0
    for item in objects:
        if not isinstance(item, dict) or not _ID.fullmatch(str(item.get("id", ""))):
            raise ImportRejected("WORKER_ID_INVALID")
        if item["id"] in identifiers:
            raise ImportRejected("WORKER_DUPLICATE_ID")
        identifiers.add(item["id"])
        if item.get("kind") not in ("MESH", "EMPTY"):
            raise ImportRejected("WORKER_KIND_INVALID")
        if not isinstance(item.get("name"), str) or not 0 < len(item["name"]) <= 256:
            raise ImportRejected("WORKER_NAME_INVALID")
        mat = item.get("world")
        if not isinstance(mat, list) or len(mat) != 16 or any(
                type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e9 for v in mat):
            raise ImportRejected("WORKER_MATRIX_INVALID")
        if tuple(round(x, 7) for x in mat[12:]) != (0, 0, 0, 1):
            raise ImportRejected("WORKER_MATRIX_NONAFFINE")
        mesh = item.get("mesh")
        if item["kind"] == "EMPTY" and mesh is not None:
            raise ImportRejected("WORKER_EMPTY_WITH_MESH")
        if item["kind"] == "MESH":
            if not isinstance(mesh, dict):
                raise ImportRejected("WORKER_MESH_MISSING")
            verts, faces = mesh.get("vertices"), mesh.get("faces")
            uvs = mesh.get("uv", [])
            raw_ids = mesh.get("native_face_ids")
            if raw_ids is not None and (
                    not isinstance(raw_ids, list) or len(raw_ids) != len(faces)
                    or any(type(x) is not int or not -1 <= x <= 65535 for x in raw_ids)):
                raise ImportRejected("WORKER_NATIVE_FACE_IDS_INVALID")
            if not isinstance(verts, list) or not isinstance(faces, list) or not isinstance(uvs, list):
                raise ImportRejected("WORKER_MESH_INVALID")
            total_vertices += len(verts)
            total_faces += len(faces)
            if total_vertices > MAX_VERTICES or total_faces > MAX_FACES or len(uvs) > 16:
                raise ImportRejected("WORKER_MESH_LIMIT")
            for v in verts:
                if not isinstance(v, list) or len(v) != 3 or any(
                        type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 1e9 for x in v):
                    raise ImportRejected("WORKER_VERTEX_INVALID")
            for face in faces:
                if not isinstance(face, list) or not 3 <= len(face) <= 1024 or any(
                        type(idx) is not int or idx < 0 or idx >= len(verts) for idx in face):
                    raise ImportRejected("WORKER_FACE_INVALID")
            loops = sum(len(face) for face in faces)
            total_loops += loops
            if total_loops > MAX_UV_LOOPS:
                raise ImportRejected("WORKER_LOOP_LIMIT")
            for layer in uvs:
                if not isinstance(layer, dict) or not isinstance(layer.get("name"), str) or len(layer["name"]) > 64:
                    raise ImportRejected("WORKER_UV_INVALID")
                coords = layer.get("coords")
                if not isinstance(coords, list) or len(coords) != loops:
                    raise ImportRejected("WORKER_UV_COUNT_INVALID")
                for co in coords:
                    if not isinstance(co, list) or len(co) != 2 or any(
                            type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 1e9 for x in co):
                        raise ImportRejected("WORKER_UV_VALUE_INVALID")
        parent = item.get("parent")
        if parent is not None and not _ID.fullmatch(str(parent)):
            raise ImportRejected("WORKER_PARENT_INVALID")
    for item in objects:
        if item.get("parent") is not None and item["parent"] not in identifiers:
            raise ImportRejected("WORKER_PARENT_MISSING")
    # Independent topology cycle detection even if child claimed safe.
    parents = {item["id"]: item.get("parent") for item in objects}
    for first in parents:
        visited = set()
        current = first
        while current:
            if current in visited:
                raise ImportRejected("WORKER_PARENT_CYCLE")
            visited.add(current)
            current = parents[current]
    return response


def materialize(response, context, *, collection=None):
    """Construct validated data; never link original native shaders/scripts."""
    import bpy
    from mathutils import Matrix
    validate_response(response)
    parent = collection or context.view_layer.active_layer_collection.collection
    created = {}
    created_meshes = []
    try:
        for item in response["objects"]:
            if item["kind"] == "MESH":
                blob = item["mesh"]
                mesh = bpy.data.meshes.new("MAXBLEND geometry")
                created_meshes.append(mesh)
                mesh.from_pydata(blob["vertices"], [], blob["faces"])
                mesh.validate()
                mesh.update()
                for channel in blob["uv"]:
                    layer = mesh.uv_layers.new(name=channel["name"])
                    for idx, co in enumerate(channel["coords"]):
                        layer.data[idx].uv = co
                obj = bpy.data.objects.new(item["name"], mesh)
                if blob.get("native_face_ids") is not None:
                    obj["maxblend.raw_face_material_ids"] = blob["native_face_ids"]
            else:
                obj = bpy.data.objects.new(item["name"], None)
            parent.objects.link(obj)
            obj["maxblend.node_id"] = item["id"]
            obj["maxblend.provenance"] = "Scene:index"
            # Original raw chunk ID is document-local, not an asserted native GUID.
            created[item["id"]] = obj
        pending = {item["id"]: item for item in response["objects"]}
        while pending:
            progressed = False
            for ident, item in list(pending.items()):
                parent_id = item.get("parent")
                if parent_id is not None and parent_id in pending:
                    continue
                obj = created[ident]
                if parent_id is not None:
                    obj.parent = created[parent_id]
                world = [item["world"][i:i+4] for i in (0, 4, 8, 12)]
                obj.matrix_world = Matrix(world)
                del pending[ident]
                progressed = True
            if not progressed:
                raise ImportRejected("WORKER_PARENT_CYCLE")
        context.view_layer.update()
        return created
    except Exception:
        for obj in created.values():
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in created_meshes:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        raise ImportRejected("WORKER_REPLAY_FAILED") from None


def isolated_import(filename, context, *, global_matrix=None,
                    object_filter=None, use_collection=False, timeout=30):
    """Only public import entrypoint. Strict Linux; no in-process fallback."""
    import bpy
    _limits()
    name = os.fspath(filename)
    if not Path(name).is_absolute():
        raise ImportRejected("INPUT_MUST_BE_ABSOLUTE")
    if not isinstance(bpy.app.binary_path, str) or not os.path.isabs(bpy.app.binary_path):
        raise ImportRejected("TRUSTED_BLENDER_BINARY_UNAVAILABLE")
    with tempfile.TemporaryDirectory(prefix="maxblend-private-") as stage:
        root = Path(stage)
        os.chmod(root, 0o700)
        request = root / "request.json"
        output = root / "output.json"
        params = {
            "source": name, "output": str(output),
            "global_matrix": [[float(x) for x in row] for row in
                              (global_matrix if global_matrix is not None else
                               __import__("mathutils").Matrix.Identity(4))],
            "filter": sorted(object_filter or ("MATERIAL", "UV", "EMPTY")),
        }
        fd = os.open(request, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(params, f)
        worker = Path(__file__).with_name("maxblend_worker.py")
        # No Blender plugins, Python injections or user startup scripts supplied.
        env = {"PATH": "/usr/bin:/bin", "HOME": str(root), "TMPDIR": str(root),
               "BLENDER_USER_CONFIG": str(root / "config"),
               "BLENDER_USER_SCRIPTS": str(root / "scripts"),
               "BLENDER_USER_DATAFILES": str(root / "data"),
               "PYTHONNOUSERSITE": "1", "LC_ALL": "C.UTF-8"}
        run_worker([bpy.app.binary_path, "--background", "--factory-startup",
                    "--disable-autoexec", "--python-exit-code", "1",
                    "--python", str(worker), "--", str(request)],
                   timeout=timeout, cwd=stage, env=env)
        result = validate_response(_read_private(output))
        if result["status"] in ("failed", "unsupported"):
            raise ImportRejected("WORKER_SCENE_UNSUPPORTED")
        collection = None
        if use_collection:
            collection = bpy.data.collections.new("MAXBLEND Import")
            context.scene.collection.children.link(collection)
        try:
            mapping = materialize(result, context, collection=collection)
        except ImportRejected:
            if collection is not None:
                bpy.data.collections.remove(collection)
            raise
        # Same-host opaque references are returned and intentionally never
        # serialized as pointers into P0 JSON.
        context.scene["maxblend_last_import_report"] = json.dumps({
            "schema": "maxblend.import/v1", "status": "partial",
            "container": "max_cfb", "objects_created": len(mapping),
            "materials_created": 0, "textures_linked": 0,
            "warnings": ["ISOLATED_PREVIEW_ONLY", "SOURCE_UNITS_UNVERIFIED",
                         "MATERIAL_MAPPING_UNVERIFIED"],
            "native_max_export": False, "source_units_verified": False,
        })
        return mapping, result
