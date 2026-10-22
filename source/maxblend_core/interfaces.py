# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Blender-independent Wave 0 interfaces for isolated MAX import components.

These are data-transfer plans, NOT a native .max wire-format description.
All fields absent from evidence remain None/unknown. Implementations must
not evaluate scene scripts or load untrusted extension code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Protocol, TypeAlias

ResultStatus: TypeAlias = Literal["success", "partial", "failed", "unsupported"]
Severity: TypeAlias = Literal["info", "warning", "error"]
Coverage: TypeAlias = Literal["supported", "partial", "unsupported", "unknown"]
PathState: TypeAlias = Literal["found", "missing", "ambiguous", "blocked"]
Matrix4: TypeAlias = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    severity: Severity
    evidence: str | None = None
    status: ResultStatus = "partial"


@dataclass(frozen=True)
class SceneNode:
    node_id: str
    name: str
    kind: str
    parent_id: str | None = None
    local_matrix: Matrix4 | None = None
    # Source metadata is diagnostic only; it is not executable data.
    source_metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TransformPlan:
    # Normalized matrix convention: RH Z-up, row-major, column vectors.
    # parent_world @ local yields world; unit and axes conversion once.
    local_matrix: Matrix4 | None = None
    world_matrix: Matrix4 | None = None
    meters_per_source_unit: float | None = None
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class GeometryPlan:
    node_id: str
    vertex_count: int | None = None
    face_count: int | None = None
    uv_channel_count: int | None = None
    face_material_indices: tuple[int, ...] | None = None
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class MaterialPlan:
    material_id: str
    original_class: str | None = None
    renderer: str | None = None
    pbr_slots: Mapping[str, object] = field(default_factory=dict)
    coverage: Coverage = "unknown"
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class TextureReference:
    # Sanitized relative path or basename only. Never trust an arbitrary
    # absolute client path or use this as a filesystem authorization.
    reference: str
    channel: str | None = None
    color_space_role: Literal["color", "data", "unknown"] = "unknown"


@dataclass(frozen=True)
class TextureResolution:
    state: PathState
    # Path is strictly internal; never serialize a private absolute path.
    resolved_path: str | None = None
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class ContainerReport:
    status: ResultStatus
    bytes_examined: int
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class SceneNodePlan:
    node: SceneNode
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class InstancePlan:
    node_id: str
    source_node_id: str | None = None
    world_matrix: Matrix4 | None = None
    diagnostics: tuple[Diagnostic, ...] = ()


class TransformPlanner(Protocol):
    def plan(self, node: SceneNode, *, meters_per_source_unit: float | None) -> TransformPlan: ...


class GeometryPlanner(Protocol):
    def plan(self, node: SceneNode) -> GeometryPlan: ...


class MaterialPlanner(Protocol):
    def plan(self, material_id: str, attributes: Mapping[str, object]) -> MaterialPlan: ...


class TextureResolver(Protocol):
    def resolve(self, reference: TextureReference, *, approved_root: str | None) -> TextureResolution: ...


class ContainerProbe(Protocol):
    def probe(self, data: bytes, *, max_input_bytes: int) -> ContainerReport: ...


class SceneNodePlanner(Protocol):
    def plan(self, node: SceneNode) -> SceneNodePlan: ...


class InstancePlanner(Protocol):
    def plan(self, node: SceneNode) -> InstancePlan: ...


__all__ = [
    "ResultStatus", "Severity", "Coverage", "PathState", "Matrix4",
    "Diagnostic", "SceneNode", "TransformPlan", "GeometryPlan",
    "MaterialPlan", "TextureReference", "TextureResolution",
    "ContainerReport", "SceneNodePlan", "InstancePlan",
    "TransformPlanner", "GeometryPlanner", "MaterialPlanner",
    "TextureResolver", "ContainerProbe", "SceneNodePlanner", "InstancePlanner",
]
