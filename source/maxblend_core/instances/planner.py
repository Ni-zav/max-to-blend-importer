# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded, Blender-free identity/instancing plan for MAX scene nodes.

This does not decode .max files, resolve assets, evaluate modifiers, compose
matrices or create Blender meshes. Only explicitly evidenced geometry identities
may be shared. F6 supplies stable source indices and vetted F1 transforms.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Literal

from ..interfaces import Diagnostic, InstancePlan, Matrix4, ResultStatus, SceneNode

Role = Literal["mesh", "instance", "group", "empty", "proxy", "xref", "other"]
PathState = Literal["found", "missing", "ambiguous", "blocked", "unknown"]
_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,95}$")
_MAX_NODES = 100_000  # matches interchange-v1 object cap


@dataclass(frozen=True)
class Limits:
    max_nodes: int = _MAX_NODES
    max_depth: int = 128
    max_diagnostics: int = 1_000
    max_materials_per_object: int = 1_024

    def __post_init__(self) -> None:
        if not (1 <= self.max_nodes <= _MAX_NODES):
            raise ValueError("max_nodes outside scene manifest limit")
        if not (1 <= self.max_depth <= 512):
            raise ValueError("max_depth outside hard limit")
        if not (1 <= self.max_diagnostics <= 10_000):
            raise ValueError("max_diagnostics outside hard limit")
        if not (1 <= self.max_materials_per_object <= 1_024):
            raise ValueError("max_materials_per_object outside manifest limit")


@dataclass(frozen=True)
class InstanceInput:
    """Evidence extracted by F6, *not* inferred from names or raw paths.

    geometry_id MUST be a stable, document-local original geometry chunk ID,
    not a node name/class or a hash guessed from similar geometry. Do not pass
    vertex arrays here: a later Blender adapter resolves this key to ONE mesh
    data block and uses object-level material binding / copy-on-write.
    """

    node: SceneNode
    role: Role
    native_id: str | None = None
    source_node_id: str | None = None  # reference target, NOT a mesh clone
    geometry_id: str | None = None
    vertex_count: int | None = None
    face_count: int | None = None
    world_matrix: Matrix4 | None = None  # provided by F1 only
    material_ids: tuple[str, ...] = ()
    material_overrides: tuple[tuple[int, str], ...] = ()
    external_reference: str | None = None
    external_state: PathState = "unknown"


@dataclass(frozen=True)
class GeometryResource:
    geometry_id: str
    owner_node_id: str
    vertex_count: int | None
    face_count: int | None


@dataclass(frozen=True)
class ObjectInstance:
    id: str
    native_id: str | None
    name: str
    role: Role
    parent_id: str | None
    source_node_id: str | None
    geometry_id: str | None
    local_matrix: Matrix4 | None
    world_matrix: Matrix4 | None
    material_ids: tuple[str, ...]
    material_overrides: tuple[tuple[int, str], ...]
    external_reference: str | None
    external_state: PathState


@dataclass(frozen=True)
class InstanceReport:
    status: ResultStatus
    objects: tuple[ObjectInstance, ...]
    geometries: tuple[GeometryResource, ...]
    diagnostics: tuple[Diagnostic, ...]
    counts: tuple[tuple[str, int], ...]
    truncated: bool = False

    def count(self, code: str) -> int:
        return dict(self.counts).get(code, 0)


def _valid_id(value: str | None) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _matrix_ok(matrix: Matrix4 | None) -> bool:
    if matrix is None:
        return True
    try:
        return len(matrix) == 4 and all(
            len(row) == 4 and all(isinstance(v, (float, int)) and
                                  not isinstance(v, bool) and math.isfinite(v) for v in row)
            for row in matrix
        )
    except (TypeError, ValueError, OverflowError):
        return False


def _safe_reference(path: str | None) -> tuple[str | None, bool]:
    """Keep relative lexical references only. Never touch the filesystem.

    Do not leak original absolute paths in diagnostics, reports or logs.
    A safe reference is still NOT permission to read the path.
    """
    if path is None:
        return None, True
    if not isinstance(path, str) or not path or len(path) > 256:
        return None, False
    if path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", path):
        return None, False
    path = path.replace("\\", "/")
    if any(part in ("", ".", "..") for part in path.split("/")):
        return None, False
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in path):
        return None, False
    return path, True


class InstanceGraphPlanner:
    """Iterative O(nodes + edges) graph validation and geometry sharing plan.

    No recursive object cloning; a source ref is a pointer to a source node,
    and geometry storage is represented once per vetted geometry_id. A report
    with hard errors is FAILED and must not be materialized by F6.
    """

    def __init__(self, limits: Limits | None = None):
        self.limits = limits or Limits()

    def plan(self, node: SceneNode) -> InstancePlan:
        """F0 InstancePlanner-compatible single-node seam.

        A per-node call cannot establish graph uniqueness or parent transforms.
        F6 should use plan_scene and reject its failed/truncated reports.
        """
        meta = node.source_metadata
        target = meta.get("instance_source_id")
        world = meta.get("world_matrix")
        diags: list[Diagnostic] = []
        if target is not None and not _valid_id(target):
            target = None
            diags.append(Diagnostic("INVALID_INSTANCE_SOURCE", "Invalid source node identifier", "error"))
        if not _matrix_ok(world):
            world = None
            diags.append(Diagnostic("INVALID_WORLD_MATRIX", "World matrix is not finite 4x4", "error"))
        return InstancePlan(node_id=node.node_id, source_node_id=target,
                            world_matrix=world, diagnostics=tuple(diags))

    def plan_scene(self, inputs: Iterable[InstanceInput]) -> InstanceReport:
        limits = self.limits
        counts: Counter[str] = Counter()
        diagnostics: list[Diagnostic] = []
        hard_error = False
        limited = False
        indexed: dict[str, InstanceInput] = {}
        objects: list[ObjectInstance] = []
        geometry: dict[str, GeometryResource] = {}

        def warn(code: str, reason: str, *, evidence: str | None = None,
                 error: bool = False) -> None:
            nonlocal hard_error
            counts[code] += 1
            if error:
                hard_error = True
            if len(diagnostics) < limits.max_diagnostics:
                diagnostics.append(Diagnostic(code, reason,
                                              "error" if error else "warning",
                                              evidence=evidence,
                                              status="failed" if error else "partial"))

        # Never list(inputs) or traverse more than max_nodes + 1 records.
        for index, item in enumerate(inputs):
            if index >= limits.max_nodes:
                limited = True
                warn("NODE_LIMIT", "Object count exceeds configured bound", error=True)
                break
            if not isinstance(item, InstanceInput):
                warn("INVALID_INPUT", "Expected InstanceInput", error=True)
                continue
            node = item.node
            if not _valid_id(node.node_id) or node.node_id in indexed:
                warn("INVALID_OR_DUPLICATE_ID", "Invalid or repeated object identifier", error=True)
                continue
            indexed[node.node_id] = item
            if item.role not in ("mesh", "instance", "group", "empty", "proxy", "xref", "other"):
                warn("UNKNOWN_KIND", "Unrecognized scene component kind", error=True)
                role: Role = "other"
            else:
                role = item.role
            if not _matrix_ok(node.local_matrix) or not _matrix_ok(item.world_matrix):
                warn("INVALID_MATRIX", "Nonfinite or malformed matrix; never place at origin", error=True)
            if node.local_matrix is None and item.world_matrix is None:
                warn("PLACEMENT_UNRESOLVED", "No evidenced local or world transform")
            elif node.parent_id is not None and item.world_matrix is None:
                warn("WORLD_UNRESOLVED", "F1 world placement not supplied; no origin fallback")
            if node.parent_id is not None and not _valid_id(node.parent_id):
                warn("INVALID_PARENT_ID", "Parent identifier is invalid", error=True)
            if item.source_node_id is not None and not _valid_id(item.source_node_id):
                warn("INVALID_SOURCE_ID", "Reference identifier is invalid", error=True)
            if item.native_id is not None and (not isinstance(item.native_id, str) or
                                                len(item.native_id) > 128):
                warn("INVALID_NATIVE_ID", "Native identifier exceeds bound", error=True)
            if len(node.name) > 256:
                warn("NAME_LIMIT", "Object name exceeds bound", error=True)
            if not isinstance(item.material_ids, tuple) or len(item.material_ids) > limits.max_materials_per_object:
                warn("MATERIAL_LIMIT", "Material slot count exceeds bound", error=True)
            if not isinstance(item.material_overrides, tuple) or len(item.material_overrides) > limits.max_materials_per_object:
                warn("MATERIAL_LIMIT", "Material overrides exceed bound", error=True)
            if not all(_valid_id(s) for s in item.material_ids):
                warn("INVALID_MATERIAL_ID", "Invalid material identifier", error=True)
            if not all(isinstance(i, int) and not isinstance(i, bool) and i >= 0
                       and i < limits.max_materials_per_object and _valid_id(v)
                       for i, v in item.material_overrides):
                warn("INVALID_MATERIAL_OVERRIDE", "Invalid material override slot or id", error=True)
            if len({i for i, _ in item.material_overrides}) != len(item.material_overrides):
                warn("DUPLICATE_OVERRIDE", "Multiple values for one material slot", error=True)
            if item.geometry_id is not None and not _valid_id(item.geometry_id):
                warn("INVALID_GEOMETRY_ID", "Invalid geometry source identifier", error=True)
            for count in (item.vertex_count, item.face_count):
                if count is not None and (not isinstance(count, int) or isinstance(count, bool)
                                          or count < 0 or count > 1_000_000_000):
                    warn("INVALID_GEOMETRY_COUNT", "Invalid geometry count", error=True)
            if role in ("group", "empty", "xref", "proxy", "other") and item.geometry_id is not None:
                warn("UNSUPPORTED_GEOMETRY", "Nonmesh component cannot supply direct mesh", error=True)
            if role == "mesh" and item.geometry_id is None:
                warn("GEOMETRY_UNRESOLVED", "Mesh has no evidenced geometry source")
            if role == "instance" and item.source_node_id is None and item.geometry_id is None:
                warn("INSTANCE_UNRESOLVED", "Instance has no source node or geometry key")
            if role == "other":
                warn("UNSUPPORTED_COMPONENT", "Unrecognized component retained as metadata only")
            if role in ("proxy", "xref"):
                warn("EXTERNAL_UNSUPPORTED", "External renderer asset not imported as geometry")
            safe_ref, ok_ref = _safe_reference(item.external_reference)
            state = item.external_state
            if state not in ("found", "missing", "ambiguous", "blocked", "unknown"):
                warn("INVALID_EXTERNAL_STATE", "Unknown external resolution state", error=True)
                state = "blocked"
            if not ok_ref:
                warn("EXTERNAL_PATH_BLOCKED", "Unsafe external path suppressed")
                state = "blocked"
            if role in ("xref", "proxy") and (safe_ref is None or state in ("unknown", "missing", "ambiguous", "blocked")):
                warn("EXTERNAL_UNRESOLVED", "External asset is not verified for import")
            if role in ("mesh", "instance") and item.geometry_id is not None and _valid_id(item.geometry_id):
                existing = geometry.get(item.geometry_id)
                if existing is None:
                    geometry[item.geometry_id] = GeometryResource(
                        item.geometry_id, node.node_id, item.vertex_count, item.face_count)
                elif ((item.vertex_count is not None and existing.vertex_count is not None and
                       item.vertex_count != existing.vertex_count) or
                      (item.face_count is not None and existing.face_count is not None and
                       item.face_count != existing.face_count)):
                    warn("GEOMETRY_ID_COLLISION", "Shared geometry ID has inconsistent statistics", error=True)
            objects.append(ObjectInstance(
                node.node_id, item.native_id, node.name, role, node.parent_id,
                item.source_node_id, item.geometry_id, node.local_matrix, item.world_matrix,
                item.material_ids, item.material_overrides, safe_ref, state))

        # Check both parent and instance-reference edges without recursive DFS.
        # Finished children follow their dependencies, allowing linear resolution.
        color: dict[str, int] = {}
        finish: list[str] = []
        for root in indexed:
            if color.get(root) == 2:
                continue
            stack = [(root, False, 1)]
            while stack:
                key, exiting, depth = stack.pop()
                if exiting:
                    color[key] = 2
                    finish.append(key)
                    continue
                if color.get(key) == 2:
                    continue
                if color.get(key) == 1:
                    warn("REFERENCE_CYCLE", "Cyclic group/instance/parent reference", error=True)
                    continue
                if depth > limits.max_depth:
                    warn("GRAPH_DEPTH", "Group/reference nesting exceeds bound", error=True)
                    continue
                color[key] = 1
                stack.append((key, True, depth))
                it = indexed[key]
                for target in (it.node.parent_id, it.source_node_id):
                    if target is None:
                        continue
                    if target not in indexed:
                        warn("REFERENCE_MISSING", "Linked source or parent is missing")
                    else:
                        stack.append((target, False, depth + 1))

        # Detect long chains even when nodes are presented parent-first and
        # DFS sees their dependencies already complete (dynamic longest path).
        graph_depth: dict[str, int] = {}
        for key in finish:
            it = indexed[key]
            predecessors = (it.node.parent_id, it.source_node_id)
            depth = 1 + max((graph_depth.get(dep, 0) for dep in predecessors
                             if dep is not None), default=0)
            graph_depth[key] = depth
            if depth > limits.max_depth:
                warn("GRAPH_DEPTH", "Group/reference chain exceeds configured depth", error=True)

        # Do not expand instance chains. A resolved instance points at the
        # original GeometryResource key; the object itself owns its materials.
        effective: dict[str, str | None] = {}
        for key in finish:
            item = indexed[key]
            resolved = item.geometry_id
            if item.role == "instance" and item.source_node_id:
                inherited = effective.get(item.source_node_id)
                if resolved and inherited and resolved != inherited:
                    warn("INSTANCE_GEOMETRY_CONFLICT", "Instance geometry differs from referenced source", error=True)
                if resolved is None:
                    resolved = inherited
            effective[key] = resolved
            if item.role == "instance" and resolved is None:
                warn("INSTANCE_UNRESOLVED", "Reference chain has no geometry")

        objects = [ObjectInstance(
            ob.id, ob.native_id, ob.name, ob.role, ob.parent_id,
            ob.source_node_id, effective.get(ob.id, ob.geometry_id),
            ob.local_matrix, ob.world_matrix, ob.material_ids,
            ob.material_overrides, ob.external_reference, ob.external_state)
            for ob in objects]
        counts["objects"] = len(objects)
        counts["geometry_resources"] = len(geometry)
        counts["geometry_references"] = sum(o.geometry_id is not None for o in objects)
        counts["external_objects"] = sum(o.role in ("proxy", "xref") for o in objects)
        counts["unresolved_geometry_objects"] = sum(o.role in ("mesh", "instance") and
                                                      o.geometry_id is None for o in objects)
        refs = Counter(ob.geometry_id for ob in objects if ob.geometry_id is not None)
        counts["shared_geometry_resources"] = sum(n > 1 for n in refs.values())
        if hard_error or limited:
            status: ResultStatus = "failed"
        elif not objects or all(ob.role in ("proxy", "xref", "other") for ob in objects):
            status = "unsupported"
        elif any(code not in ("objects", "geometry_resources", "geometry_references",
                              "external_objects", "unresolved_geometry_objects",
                              "shared_geometry_resources") for code in counts):
            status = "partial"
        else:
            status = "success"
        if len(diagnostics) == limits.max_diagnostics and sum(
            n for code, n in counts.items() if code not in (
                "objects", "geometry_resources", "geometry_references", "external_objects",
                "unresolved_geometry_objects", "shared_geometry_resources")) > len(diagnostics):
            counts["diagnostics_suppressed"] = sum(
                n for code, n in counts.items() if code not in (
                    "objects", "geometry_resources", "geometry_references", "external_objects",
                    "unresolved_geometry_objects", "shared_geometry_resources")) - len(diagnostics)
        return InstanceReport(status, tuple(objects), tuple(geometry.values()),
                              tuple(diagnostics), tuple(sorted(counts.items())), limited)


__all__ = ["Limits", "InstanceInput", "GeometryResource", "ObjectInstance",
           "InstanceReport", "InstanceGraphPlanner"]
