# SPDX-License-Identifier: GPL-2.0-or-later
"""F6 -> P6 canonical scene/v1 view of real isolated-import Blender objects.

No claims of recovered source units, source shader graphs or native MAX
fidelity. No raw filesystem path, image content or runtime pointer is
serialized. bpy references stay in this Blender process only.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Mapping

_ID = re.compile(r"^node_[0-9]{1,8}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass
class ImportSession:
    """Per-process capability; P6 must not rehydrate pointers from JSON."""
    objects_by_id: dict[str, object]
    scene_manifest: dict
    raw_worker_status: str

    def resolve(self, node_id: str):
        return self.objects_by_id.get(node_id)


def warning(code: str, reason: str, *, evidence: str | None = None) -> dict:
    return {
        "code": code, "severity": "warning", "reason": reason,
        "evidence": evidence, "attribute": None,
        "before": None, "after": None,
    }


def canonical_scene(objects_by_id: Mapping[str, object], response: dict,
                    *, context, importer_commit: str | None = None) -> dict:
    """Project only independently observed bpy attributes and trusted IDs.

    The v1 schema requires meters for matrix/bounds values. The source units
    are not verified, so all physical matrices/bounds are null rather than
    silently reporting Blender display units as verified meters.
    """
    if importer_commit is not None and not _COMMIT.fullmatch(importer_commit):
        raise ValueError("INVALID_IMPORTER_COMMIT")
    sha256 = response.get("source_sha256")
    if not isinstance(sha256, str) or not _SHA.fullmatch(sha256):
        raise ValueError("INVALID_SOURCE_DIGEST")
    if response.get("status") != "partial":
        raise ValueError("UNVERIFIED_IMPORT_STATUS")
    raw_objects = response.get("objects")
    if not isinstance(raw_objects, list) or len(raw_objects) != len(objects_by_id):
        raise ValueError("OBJECT_ATTESTATION_MISMATCH")
    expected = {o.get("id") for o in raw_objects}
    if expected != set(objects_by_id) or any(
            not isinstance(k, str) or not _ID.fullmatch(k) for k in expected):
        raise ValueError("OBJECT_IDS_UNTRUSTED")
    display = context.scene.unit_settings
    if display.system not in ("NONE", "METRIC", "IMPERIAL"):
        raise ValueError("BLENDER_DISPLAY_INVALID")
    manifest_objects = []
    for record in raw_objects:
        node_id = record["id"]
        obj = objects_by_id[node_id]
        if obj.get("maxblend.node_id") != node_id:
            raise ValueError("BLENDER_OBJECT_ID_MISMATCH")
        kind = obj.type if obj.type in ("MESH", "EMPTY") else "OTHER"
        parent = obj.parent.get("maxblend.node_id") if obj.parent else None
        if parent is not None and parent not in objects_by_id:
            raise ValueError("PARENT_ATTESTATION_MISMATCH")
        mesh = obj.data if kind == "MESH" else None
        if mesh:
            vertices = len(mesh.vertices)
            faces = len(mesh.polygons)
            triangles = sum(max(0, len(face.vertices) - 2) for face in mesh.polygons)
            channels = len(mesh.uv_layers)
        else:
            vertices = faces = triangles = channels = None
        evidence = "Scene:record=" + node_id.removeprefix("node_")
        manifest_objects.append({
            "id": node_id, "native_id": None, "name": obj.name[:256],
            "kind": kind, "parent_id": parent,
            "local_matrix": None, "world_matrix": None,
            "source_raw_matrix": None, "bounds_m": None,
            "geometry": {
                "vertex_count": vertices, "face_count": faces,
                "triangle_count": triangles, "uv_channel_count": channels,
            },
            "material_ids": [], "face_material_ids": None,
            "provenance": {"method": "derived", "evidence": evidence},
            "warnings": [
                warning("physical_units_unknown",
                        "Physical source units are not evidenced; normalized matrices and bounds omitted",
                        evidence=evidence),
                warning("material_mapping_unverified",
                        "MAX native Multi/Sub IDs cannot be mapped to verified Blender material slots",
                        evidence=evidence),
            ],
        })
    manifest = {
        "schema_version": "maxblend.scene/v1",
        "status": "partial",
        "source": {"extension": ".max", "version": "1.9.3",
                   "commit": importer_commit, "sha256": sha256},
        "source_units": {"unit": None, "meters_per_unit": None},
        "blender_display": {"system": display.system,
                            "scale_length": float(display.scale_length),
                            "length_unit": display.length_unit},
        "axes": {"handedness": "UNKNOWN", "up": None, "forward": None},
        "transforms": {"space": "BLENDER_RH_Z_UP", "layout": "ROW_MAJOR",
                       "vectors": "COLUMN", "world_rule": "PARENT_WORLD_AT_LOCAL",
                       "values_in_meters": True,
                       "axis_conversion_applied": None,
                       "unit_conversion_applied": None},
        "objects": manifest_objects,
        "materials": [], "textures": [], "animations": [],
        "warnings": [
            warning("physical_units_unknown",
                    "MAX physical source-unit and axis metadata not independently decoded"),
            warning("native_materials_not_replayed",
                    "Renderer graph and native material-slot assignments were not transferred"),
            warning("animation_not_verified",
                    "Absence of decoded tracks does not prove absence of source animation"),
        ],
    }
    return manifest


def capture(objects_by_id, response, *, context, importer_commit=None) -> ImportSession:
    scene = canonical_scene(objects_by_id, response, context=context,
                            importer_commit=importer_commit)
    return ImportSession(dict(objects_by_id), scene, response["status"])
