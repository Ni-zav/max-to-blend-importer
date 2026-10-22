# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded, Blender-free Editable Mesh/Poly reconstruction plans.

This module consumes *extracted* 3ds Max chunk payloads, not arbitrary CFB files.
It never applies transforms, evaluates modifiers or changes source topology.
F6 must call this through the F0 dispatcher after F5 validates the container.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Literal, Sequence

from maxblend_core.interfaces import Diagnostic, GeometryPlan


@dataclass(frozen=True)
class Limits:
    max_chunk_bytes: int = 128_000_000
    max_vertices: int = 1_000_000
    max_faces: int = 1_000_000
    max_loops: int = 4_000_000
    max_face_corners: int = 1024
    max_map_vertices: int = 1_000_000
    max_map_channels: int = 32


@dataclass(frozen=True)
class PolyFaceChunk:
    """0x0118: 0x0110 face payload; optional 0x0130 material payload."""
    indices: bytes
    material: bytes | None = None
    source_element: int | None = None
    smoothing_group: int | None = None


@dataclass(frozen=True)
class MapChunk:
    """0x0128 / 0x0916 / 0x2394 map XYZ; 0x012B / 0x0918 / 0x2396 indices.

    `triangles` is a u32 count followed by triples (legacy get_uvw_coords).
    `polygons` is a sequence of <u32 corner_count, corner_count*u32> records
    (legacy get_poly_data).  No heuristic conversion between layouts.
    """
    channel: int
    points: bytes
    indices: bytes
    encoding: Literal["triangles", "polygons"]


@dataclass(frozen=True)
class FaceOrigin:
    source_face: int
    source_element: int | None = None
    chunk_type: int | None = None
    edge_flags: int | None = None
    face_flags: int | None = None
    smoothing_group: int | None = None


@dataclass(frozen=True)
class MapLayer:
    channel: int
    points: tuple[tuple[float, float, float], ...]
    corner_indices: tuple[tuple[int, ...], ...]
    # Per-loop UV coordinates use independent map indices: UV seams do not
    # duplicate geometry vertices, and source map W is retained in points.
    loop_uv: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class MeshBuffer:
    vertices: tuple[tuple[float, float, float], ...]
    faces: tuple[tuple[int, ...], ...]
    face_material_ids: tuple[int | None, ...]
    face_origins: tuple[FaceOrigin, ...]
    maps: tuple[MapLayer, ...] = ()
    # These are populated only when explicitly provided as trusted decoded data.
    sharp_edges: tuple[tuple[int, int], ...] | None = None
    corner_normals: tuple[tuple[float, float, float], ...] | None = None
    source_point_ids: tuple[int, ...] | None = None


@dataclass(frozen=True)
class Reconstruction:
    status: Literal["success", "partial", "failed", "unsupported"]
    mesh: MeshBuffer | None
    plan: GeometryPlan
    diagnostics: tuple[Diagnostic, ...]


class _Invalid(ValueError):
    def __init__(self, code: str, message: str, evidence: str):
        super().__init__(message)
        self.code, self.evidence = code, evidence


def _bad(code: str, reason: str, evidence: str) -> None:
    raise _Invalid(code, reason, evidence)


def _buffer(raw: bytes, label: str, limits: Limits) -> memoryview:
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        _bad("invalid_chunk", "Chunk payload must be bytes", label)
    view = memoryview(raw)
    if view.ndim != 1 or view.itemsize != 1:
        _bad("invalid_chunk", "Chunk must be a flat byte buffer", label)
    if view.nbytes > limits.max_chunk_bytes:
        _bad("allocation_limit", "Chunk exceeds byte limit", label)
    return view


def _header(view: memoryview, label: str, limit: int, stride: int | None = None) -> int:
    if len(view) < 4:
        _bad("truncated_chunk", "Missing 32-bit count", label)
    count = struct.unpack_from("<I", view)[0]
    if count > limit:
        _bad("allocation_limit", "Declared record count exceeds limit", label)
    if stride is not None and len(view) != 4 + count * stride:
        _bad("invalid_length", "Record count does not match exact byte length", label)
    return count


def _xyz(view: memoryview, count: int, offset: int, label: str) -> tuple[tuple[float, float, float], ...]:
    out = []
    for i in range(count):
        value = struct.unpack_from("<fff", view, offset + 12 * i)
        if not all(math.isfinite(v) for v in value):
            _bad("nonfinite_coordinate", "NaN/Inf coordinate", f"{label}[{i}]")
        out.append(value)
    return tuple(out)


def _mesh_vertices(raw: bytes, limits: Limits):
    view = _buffer(raw, "0x0914", limits)
    count = _header(view, "0x0914", limits.max_vertices, 12)
    return _xyz(view, count, 4, "vertex"), None


def _poly_vertices(raw: bytes, limits: Limits):
    view = _buffer(raw, "0x0100", limits)
    count = _header(view, "0x0100", limits.max_vertices, 16)
    vertices = []
    point_ids = []
    for i in range(count):
        point_ids.append(struct.unpack_from("<I", view, 4 + 16 * i)[0])
        vertex = struct.unpack_from("<fff", view, 8 + 16 * i)
        if not all(math.isfinite(v) for v in vertex):
            _bad("nonfinite_coordinate", "NaN/Inf coordinate", f"vertex[{i}]")
        vertices.append(vertex)
    return tuple(vertices), tuple(point_ids)


def _mesh_faces(raw: bytes, limits: Limits):
    view = _buffer(raw, "0x0912", limits)
    count = _header(view, "0x0912", limits.max_faces, 20)
    if count * 3 > limits.max_loops:
        _bad("allocation_limit", "Triangle corners exceed loop limit", "0x0912")
    faces, materials, origins = [], [], []
    for i in range(count):
        a, b, c, edge, faceflag, mat = struct.unpack_from("<IIIIHH", view, 4 + 20 * i)
        faces.append((a, b, c))
        materials.append(mat)
        origins.append(FaceOrigin(i, chunk_type=0x0912, edge_flags=edge, face_flags=faceflag))
    return tuple(faces), tuple(materials), tuple(origins)


def _poly_faces(chunks: Sequence[PolyFaceChunk], limits: Limits):
    if len(chunks) > limits.max_faces:
        _bad("allocation_limit", "Polygon count exceeds limit", "0x0118")
    faces, materials, origins = [], [], []
    loops = 0
    for i, chunk in enumerate(chunks):
        view = _buffer(chunk.indices, f"0x0110[{i}]", limits)
        n = _header(view, f"0x0110[{i}]", limits.max_face_corners, 4)
        if n < 3:
            _bad("invalid_topology", "Polygon requires at least 3 vertices", f"face[{i}]")
        loops += n
        if loops > limits.max_loops:
            _bad("allocation_limit", "Polygon loops exceed limit", f"face[{i}]")
        faces.append(struct.unpack_from(f"<{n}I", view, 4))
        if chunk.material is None:
            materials.append(None)
        else:
            m = _buffer(chunk.material, f"0x0130[{i}]", limits)
            if len(m) != 2:
                _bad("invalid_length", "Material ID requires exactly 2 bytes", f"face[{i}]")
            materials.append(struct.unpack_from("<H", m)[0])
        if chunk.smoothing_group is not None and (isinstance(chunk.smoothing_group, bool) or
                                                   not isinstance(chunk.smoothing_group, int) or
                                                   not 0 <= chunk.smoothing_group <= 0xffffffff):
            _bad("invalid_smoothing", "Smoothing group must be u32", f"face[{i}]")
        origins.append(FaceOrigin(i, chunk.source_element, 0x0118,
                                  smoothing_group=chunk.smoothing_group))
    return tuple(faces), tuple(materials), tuple(origins)


def _map_points(raw: bytes, limits: Limits, channel: int):
    view = _buffer(raw, f"map[{channel}].points", limits)
    count = _header(view, f"map[{channel}].points", limits.max_map_vertices, 12)
    return _xyz(view, count, 4, f"map[{channel}].point")


def _map_indices(raw: bytes, encoding: str, faces: tuple[tuple[int,...], ...],
                 limits: Limits, channel: int):
    view = _buffer(raw, f"map[{channel}].indices", limits)
    if encoding == "triangles":
        count = _header(view, f"map[{channel}].indices", limits.max_loops, None)
        if len(view) != 4 + len(faces) * 12 or count not in (len(faces), len(faces) * 3):
            _bad("invalid_uv_topology", "UV triangle count or byte length differs from faces",
                 f"map[{channel}]")
        if any(len(face) != 3 for face in faces):
            _bad("invalid_uv_topology", "Triangle UV indices require triangle geometry", f"map[{channel}]")
        return tuple(struct.unpack_from("<III", view, 4 + i * 12) for i in range(len(faces)))
    if encoding == "polygons":
        offset, output = 0, []
        for i, face in enumerate(faces):
            if len(view) - offset < 4:
                _bad("truncated_chunk", "Missing UV face corner count", f"map[{channel}].face[{i}]")
            n = struct.unpack_from("<I", view, offset)[0]
            offset += 4
            if n != len(face) or len(view) - offset < 4 * n:
                _bad("invalid_uv_topology", "UV corners differ from geometry face",
                     f"map[{channel}].face[{i}]")
            output.append(struct.unpack_from(f"<{n}I", view, offset))
            offset += 4 * n
        if offset != len(view):
            _bad("invalid_length", "Trailing UV polygon bytes", f"map[{channel}]")
        return tuple(output)
    _bad("unsupported_uv_encoding", "Unrecognized map index encoding", f"map[{channel}]")


def _validate_topology(vertices, faces, limits: Limits):
    if not faces:
        _bad("missing_topology", "No explicit polygon faces", "geometry.faces")
    if not vertices:
        _bad("missing_topology", "No vertices", "geometry.vertices")
    for i, face in enumerate(faces):
        if not 3 <= len(face) <= limits.max_face_corners:
            _bad("invalid_topology", "Face corner count invalid", f"face[{i}]")
        if any(index >= len(vertices) for index in face):
            _bad("invalid_topology", "Face vertex index out of range", f"face[{i}]")
        if len(set(face)) != len(face):
            _bad("invalid_topology", "Repeated vertex in a face", f"face[{i}]")
    # No remapping, triangulation, vertex weld, auto-normal, or orientation flip.


def _finish(node_id, vertices, source_ids, faces, materials, origins, maps,
            limits, mirrored_transform, unknown_modifiers, sharp_edges, corner_normals):
    _validate_topology(vertices, faces, limits)
    diagnostics = []
    if any(mat is None for mat in materials):
        diagnostics.append(Diagnostic("missing_material_id", "Some polygon face material IDs are absent",
                                      "warning", "0x0130"))
    if mirrored_transform:
        diagnostics.append(Diagnostic("mirrored_transform_unapplied",
                                      "Geometry winding left unchanged; transform planner handles reflection",
                                      "warning", "transform.determinant"))
    if unknown_modifiers:
        diagnostics.append(Diagnostic("unknown_modifier_stack",
                                      "Base mesh does not represent unverified evaluated modifier stack",
                                      "warning", "modifiers"))
    if sharp_edges is not None:
        unique = set()
        for i, edge in enumerate(sharp_edges):
            if len(edge) != 2 or any(isinstance(v, bool) or not isinstance(v, int) or
                                     v < 0 or v >= len(vertices) for v in edge) or edge[0] == edge[1]:
                _bad("invalid_sharp_edge", "Sharp edge references invalid vertices", f"edge[{i}]")
            canonical = tuple(sorted(edge))
            if canonical in unique:
                _bad("invalid_sharp_edge", "Duplicated sharp edge", f"edge[{i}]")
            unique.add(canonical)
        present = {tuple(sorted((f[i], f[(i+1) % len(f)]))) for f in faces
                   for i in range(len(f))}
        if not unique.issubset(present):
            _bad("invalid_sharp_edge", "Sharp edge not present in topology", "sharp_edges")
        sharp_edges = tuple(sorted(unique))
    if corner_normals is not None:
        if len(corner_normals) != sum(len(f) for f in faces):
            _bad("invalid_normals", "Normal count must equal mesh loop count", "corner_normals")
        norm = []
        for i, normal in enumerate(corner_normals):
            if len(normal) != 3 or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in normal):
                _bad("invalid_normals", "Nonfinite/malformed corner normal", f"normal[{i}]")
            magnitude = math.sqrt(sum(v*v for v in normal))
            if magnitude < 1e-12 or not math.isfinite(magnitude):
                _bad("invalid_normals", "Zero/overflow normal", f"normal[{i}]")
            norm.append(tuple(v / magnitude for v in normal))
        corner_normals = tuple(norm)
    # Unknown smoothness / normals stay None; never guess from triangle flags.
    uv = []
    channels = set()
    if len(maps) > limits.max_map_channels:
        _bad("allocation_limit", "UV map channel count exceeds limit", "maps")
    for item in maps:
        try:
            if isinstance(item.channel, bool) or not isinstance(item.channel, int) or not 0 <= item.channel < 65536:
                _bad("invalid_map_channel", "Map channel must be unsigned 16-bit", "map.channel")
            if item.channel in channels:
                _bad("duplicate_map_channel", "Duplicate channel ID", f"map[{item.channel}]")
            channels.add(item.channel)
            points = _map_points(item.points, limits, item.channel)
            ids = _map_indices(item.indices, item.encoding, faces, limits, item.channel)
            if any(idx >= len(points) for face in ids for idx in face):
                _bad("invalid_uv_topology", "Map index out of bounds", f"map[{item.channel}]")
            uv.append(MapLayer(item.channel, points, ids,
                               tuple(points[idx][:2] for face in ids for idx in face)))
            if item.channel == 0:
                diagnostics.append(Diagnostic("channel_zero_semantics_unknown",
                                              "Map channel zero may represent vertex color rather than UV",
                                              "warning", "map[0]"))
        except _Invalid as exc:
            diagnostics.append(Diagnostic(exc.code, str(exc), "warning", exc.evidence))
    if corner_normals is None:
        diagnostics.append(Diagnostic("normals_unverified", "No explicit corner normals supplied; hard normals unknown",
                                      "warning", "corner_normals"))
    mesh = MeshBuffer(vertices, faces, materials, origins, tuple(uv),
                      sharp_edges=sharp_edges, corner_normals=corner_normals,
                      source_point_ids=source_ids)
    status = "partial" if diagnostics else "success"
    plan = GeometryPlan(node_id, len(vertices), len(faces), len(uv),
                        tuple(materials) if all(i is not None for i in materials) else None,
                        tuple(diagnostics))
    return Reconstruction(status, mesh, plan, tuple(diagnostics))


def _failed(node_id: str, exc: _Invalid) -> Reconstruction:
    diag = Diagnostic(exc.code, str(exc), "error", exc.evidence, status="failed")
    return Reconstruction("failed", None, GeometryPlan(node_id, diagnostics=(diag,)), (diag,))


def reconstruct_editable_mesh(node_id: str, vertex_data: bytes, face_data: bytes, *,
                              maps: Sequence[MapChunk] = (), limits: Limits = Limits(),
                              mirrored_transform: bool = False, unknown_modifiers: bool = False,
                              sharp_edges: Sequence[tuple[int, int]] | None = None,
                              corner_normals: Sequence[tuple[float, float, float]] | None = None
                              ) -> Reconstruction:
    """Decode 0x0914 vertices and 0x0912 triangle/material records atomically."""
    try:
        verts, ids = _mesh_vertices(vertex_data, limits)
        faces, mats, origins = _mesh_faces(face_data, limits)
        return _finish(node_id, verts, ids, faces, mats, origins, maps, limits,
                       mirrored_transform, unknown_modifiers, sharp_edges, corner_normals)
    except _Invalid as exc:
        return _failed(node_id, exc)


def reconstruct_editable_poly(node_id: str, vertex_data: bytes, face_chunks: Sequence[PolyFaceChunk], *,
                              maps: Sequence[MapChunk] = (), limits: Limits = Limits(),
                              mirrored_transform: bool = False, unknown_modifiers: bool = False,
                              sharp_edges: Sequence[tuple[int, int]] | None = None,
                              corner_normals: Sequence[tuple[float, float, float]] | None = None
                              ) -> Reconstruction:
    """Decode 0x0100 vertices and ordered 0x0118/0x0110/0x0130 polygon chunks."""
    try:
        verts, ids = _poly_vertices(vertex_data, limits)
        faces, mats, origins = _poly_faces(face_chunks, limits)
        return _finish(node_id, verts, ids, faces, mats, origins, maps, limits,
                       mirrored_transform, unknown_modifiers, sharp_edges, corner_normals)
    except _Invalid as exc:
        return _failed(node_id, exc)


def unsupported_geometry(node_id: str, kind: str) -> Reconstruction:
    """Explicitly decline primitives, procedurals, and unknown topology paths."""
    # Kind is deliberately not echoed: untrusted asset names/paths must not leak.
    diag = Diagnostic("unsupported_geometry", "No verified decoder for geometry class",
                      "warning", "geometry.class", status="unsupported")
    return Reconstruction("unsupported", None, GeometryPlan(node_id, diagnostics=(diag,)), (diag,))


__all__ = ["Limits", "PolyFaceChunk", "MapChunk", "FaceOrigin", "MapLayer", "MeshBuffer",
           "Reconstruction", "reconstruct_editable_mesh", "reconstruct_editable_poly",
           "unsupported_geometry"]
