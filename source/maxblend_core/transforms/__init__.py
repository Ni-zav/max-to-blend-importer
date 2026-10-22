# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure, offline affine MAX-to-Blender transform plans (no bpy or parser calls).

Conventions: row-major 4x4, column vectors, world=parent_world @ local;
normalized positions and geometry are Blender RH Z-up **meters**. MAX system
units are physical quantities, NOT Blender's unit-display preferences.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Iterable, Mapping, Sequence

from maxblend_core.interfaces import Diagnostic, Matrix4, SceneNode, TransformPlan

TOL = 1e-10
IDENTITY: Matrix4 = ((1., 0., 0., 0.), (0., 1., 0., 0.),
                     (0., 0., 1., 0.), (0., 0., 0., 1.))
_UNIT_METERS = {"mm": .001, "millimeter": .001, "millimetre": .001,
                "cm": .01, "centimeter": .01, "centimetre": .01,
                "m": 1., "meter": 1., "metre": 1.,
                "km": 1000., "in": .0254, "inch": .0254,
                "ft": .3048, "foot": .3048}
_AXIS = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1),
         "-X": (-1, 0, 0), "-Y": (0, -1, 0), "-Z": (0, 0, -1)}


class TransformError(ValueError):
    """Invalid or unsupported affine input; never silently repair it."""


def _matrix(value: object) -> Matrix4:
    """Copy and validate finite, affine 4x4 matrices. No project data logged."""
    try:
        if len(value) != 4:  # type: ignore[arg-type]
            raise TransformError("Expected 4x4 affine matrix")
        rows = tuple(tuple(float(x) for x in row) for row in value)  # type: ignore[union-attr]
    except (TypeError, ValueError, OverflowError) as exc:
        raise TransformError("Expected finite 4x4 affine matrix") from exc
    if any(len(row) != 4 or any(not isfinite(x) for x in row) for row in rows):
        raise TransformError("Expected finite 4x4 affine matrix")
    if any(abs(rows[3][i] - IDENTITY[3][i]) > TOL for i in range(4)):
        raise TransformError("Perspective/non-affine matrix unsupported")
    return rows  # type: ignore[return-value]


def multiply(a: Matrix4, b: Matrix4) -> Matrix4:
    a, b = _matrix(a), _matrix(b)
    out = tuple(tuple(sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4))
                for i in range(4))
    return _matrix(out)


def determinant(m: Matrix4) -> float:
    m = _matrix(m)
    a, b, c = m[0][:3], m[1][:3], m[2][:3]
    return (a[0] * (b[1]*c[2] - b[2]*c[1])
            - a[1] * (b[0]*c[2] - b[2]*c[0])
            + a[2] * (b[0]*c[1] - b[1]*c[0]))


def inverse(m: Matrix4, *, tolerance: float = TOL) -> Matrix4:
    """Affine inverse via scaled partial-pivot Gauss-Jordan, rejecting ill-conditioning."""
    m = _matrix(m)
    if not (0 < tolerance < 1 and isfinite(tolerance)):
        raise TransformError("Invalid tolerance")
    a = [list(m[i][:3]) + [float(i == j) for j in range(3)] for i in range(3)]
    scales = [max(abs(v) for v in row[:3]) for row in a]
    if any(s == 0 for s in scales):
        raise TransformError("Singular affine matrix")
    for k in range(3):
        pivot = max(range(k, 3), key=lambda i: abs(a[i][k]) / scales[i])
        if abs(a[pivot][k]) <= tolerance * scales[pivot]:
            raise TransformError("Singular or ill-conditioned affine matrix")
        a[k], a[pivot] = a[pivot], a[k]
        scales[k], scales[pivot] = scales[pivot], scales[k]
        p = a[k][k]
        a[k] = [x / p for x in a[k]]
        for i in range(3):
            if i != k:
                factor = a[i][k]
                a[i] = [a[i][j] - factor * a[k][j] for j in range(6)]
    r = tuple(tuple(a[i][j+3] for j in range(3)) for i in range(3))
    t = tuple(-sum(r[i][k] * m[k][3] for k in range(3)) for i in range(3))
    result = _matrix(tuple(r[i] + (t[i],) for i in range(3)) + (IDENTITY[3],))
    if any(abs(multiply(m, result)[i][j] - IDENTITY[i][j]) > 1e-7 for i in range(4) for j in range(4)):
        raise TransformError("Ill-conditioned inverse residual")
    return result


def point(m: Matrix4, xyz: Sequence[float]) -> tuple[float, float, float]:
    m = _matrix(m)
    if len(xyz) != 3 or any(not isfinite(float(x)) for x in xyz):
        raise TransformError("Expected finite 3D point")
    return tuple(sum(m[i][j] * float(xyz[j]) for j in range(3)) + m[i][3]
                 for i in range(3))  # type: ignore[return-value]


def bake_points(points: Iterable[Sequence[float]], transform: Matrix4) -> tuple[tuple[float, float, float], ...]:
    """Pure opt-in geometry transform. Never mutate mesh/instances in-place."""
    return tuple(point(transform, vertex) for vertex in points)


def bounds(points: Iterable[Sequence[float]], transform: Matrix4 = IDENTITY):
    """World-space AABB from transformed vertices; empty input is unknown (None)."""
    transformed = bake_points(points, transform)
    if not transformed:
        return None
    return (tuple(min(p[i] for p in transformed) for i in range(3)),
            tuple(max(p[i] for p in transformed) for i in range(3)))


@dataclass(frozen=True)
class AxisConvention:
    up: str = "Z"
    forward: str = "-Y"
    handedness: str = "RIGHT"

    def basis(self) -> Matrix4:
        """Source coordinates -> Blender coordinates; includes reflection if LH."""
        if self.up not in _AXIS or self.forward not in _AXIS or self.handedness not in ("RIGHT", "LEFT"):
            raise TransformError("Unknown axis/handedness metadata; operator mapping required")
        u, f = _AXIS[self.up], _AXIS[self.forward]
        dot = sum(u[i] * f[i] for i in range(3))
        if dot:
            raise TransformError("Source up/forward axes must be perpendicular")
        cross = (u[1]*f[2]-u[2]*f[1], u[2]*f[0]-u[0]*f[2], u[0]*f[1]-u[1]*f[0])
        right = cross if self.handedness == "RIGHT" else tuple(-v for v in cross)
        return _matrix(((*right, 0.), (*(-v for v in f), 0.), (*u, 0.), IDENTITY[3]))


@dataclass(frozen=True)
class SourceUnits:
    """Physical 3ds Max system units; unit-display settings never change this."""
    name: str | None = None
    meters_per_unit: float | None = None
    operator_assumption: float | None = None

    def resolve(self) -> tuple[float | None, tuple[Diagnostic, ...]]:
        standard = _UNIT_METERS.get(self.name.lower().strip()) if isinstance(self.name, str) else None
        value = self.meters_per_unit
        if value is not None and (not isinstance(value, (int, float)) or not isfinite(value) or value <= 0):
            raise TransformError("Invalid explicit system-unit ratio")
        if standard is not None and value is not None and abs(value / standard - 1) > 1e-8:
            raise TransformError("Conflicting system-unit metadata; operator resolution required")
        if value is not None or standard is not None:
            return float(value if value is not None else standard), ()
        if self.operator_assumption is None:
            return None, (Diagnostic("unknown_system_units", "Physical MAX system units unknown; explicit assumption required", "error"),)
        a = self.operator_assumption
        if not isinstance(a, (int, float)) or not isfinite(a) or a <= 0:
            raise TransformError("Invalid operator unit assumption")
        return float(a), (Diagnostic("assumed_system_units", "Operator supplied unverified physical unit ratio", "warning",
                                      evidence="operator_assumption"),)


@dataclass(frozen=True)
class BlenderDisplay:
    system: str = "METRIC"
    scale_length: float = 1.
    length_unit: str = "METERS"

    def __post_init__(self):
        if self.system not in ("NONE", "METRIC", "IMPERIAL") or not isfinite(self.scale_length) or self.scale_length <= 0:
            raise TransformError("Invalid Blender display units")
        if self.length_unit not in ("DEFAULT", "METERS", "CENTIMETERS", "MILLIMETERS", "KILOMETERS", "FEET", "INCHES", "MILES"):
            raise TransformError("Invalid Blender display unit")


@dataclass(frozen=True)
class MatrixProperties:
    determinant: float
    mirrored: bool
    singular: bool
    nonuniform_scale: bool
    shear: bool
    axis_lengths: tuple[float, float, float]


def classify(m: Matrix4, *, tolerance: float = 1e-9) -> MatrixProperties:
    m = _matrix(m)
    if not (0 < tolerance < 1 and isfinite(tolerance)):
        raise TransformError("Invalid tolerance")
    cols = [tuple(m[i][j] for i in range(3)) for j in range(3)]
    lengths = tuple(sqrt(sum(x*x for x in c)) for c in cols)
    maximum = max(lengths)
    det = determinant(m)
    singular = maximum == 0 or abs(det) <= tolerance * maximum**3 or any(l <= maximum * tolerance for l in lengths)
    nonuniform = maximum > 0 and (max(lengths) - min(lengths)) > tolerance * maximum
    shear = any(abs(sum(cols[i][k]*cols[j][k] for k in range(3))) > tolerance * lengths[i]*lengths[j]
                for i in range(3) for j in range(i+1, 3) if lengths[i] and lengths[j])
    return MatrixProperties(det, det < -tolerance * maximum**3, singular, nonuniform, shear, lengths)


def change_basis(local: Matrix4, *, axes: AxisConvention, meters_per_unit: float) -> Matrix4:
    """Similarity N @ local @ N^-1 scales translations, not dimensionless linear scale."""
    if not isfinite(meters_per_unit) or meters_per_unit <= 0:
        raise TransformError("Unknown or invalid physical source-unit ratio")
    c = axes.basis()
    n = _matrix(tuple(tuple(c[i][j] * meters_per_unit if j < 3 else c[i][j] for j in range(4))
                      for i in range(3)) + (IDENTITY[3],))
    return multiply(multiply(n, _matrix(local)), inverse(n))


def coordinate_basis(*, axes: AxisConvention, meters_per_unit: float) -> Matrix4:
    """For raw mesh vertex coordinates, unlike change_basis for transforms."""
    if not isfinite(meters_per_unit) or meters_per_unit <= 0:
        raise TransformError("Unknown or invalid physical source-unit ratio")
    c = axes.basis()
    return _matrix(tuple(tuple(c[i][j]*meters_per_unit if j < 3 else c[i][j] for j in range(4))
                         for i in range(3)) + (IDENTITY[3],))


def parent_local_preserving_world(world: Matrix4, parent_world: Matrix4) -> Matrix4:
    """The matrix_local to assign when parenting a previously world-placed object."""
    return multiply(inverse(parent_world), world)


@dataclass(frozen=True)
class TransformEvidence:
    source_raw_matrix: Matrix4 | None
    source_geometry_offset: Matrix4 | None
    normalized_geometry_offset: Matrix4 | None
    source_matrix_space: str
    source_unit_ratio: float | None
    axis_basis: Matrix4 | None
    conversion_applied: bool


@dataclass(frozen=True)
class TransformRecord:
    plan: TransformPlan
    evidence: TransformEvidence
    local_properties: MatrixProperties | None = None
    world_properties: MatrixProperties | None = None
    geometry_world_matrix: Matrix4 | None = None

    def manifest_matrices(self) -> Mapping[str, list[float] | None]:
        """Exact P0 object fields; independent of parser-specific node metadata."""
        flatten = lambda m: [v for row in m for v in row] if m is not None else None
        return {"local_matrix": flatten(self.plan.local_matrix),
                "world_matrix": flatten(self.plan.world_matrix),
                "source_raw_matrix": flatten(self.evidence.source_raw_matrix)}


class TransformEngine:
    """F0 TransformPlanner plus stable-id, topologically ordered scene planning.

    matrix_space is explicitly source (default) or normalized. Normalized
    data is never run through the axis/unit conversion twice. controller_format
    must be static and audited, not a script or time-varying controller.
    """
    def __init__(self, axes: AxisConvention = AxisConvention(), *,
                 source_units: SourceUnits = SourceUnits(),
                 display: BlenderDisplay = BlenderDisplay(), max_depth: int = 256):
        if not isinstance(max_depth, int) or not (1 <= max_depth <= 10000):
            raise TransformError("Invalid maximum hierarchy depth")
        self.axes, self.source_units, self.display, self.max_depth = axes, source_units, display, max_depth

    def plan(self, node: SceneNode, *, meters_per_source_unit: float | None) -> TransformPlan:
        """F0 single-node compatibility; parented nodes require plan_scene()."""
        if node.parent_id is not None:
            return TransformPlan(diagnostics=(Diagnostic("requires_parent", "Parented node requires scene plan", "error", status="unsupported"),))
        source = SourceUnits(self.source_units.name, meters_per_source_unit, self.source_units.operator_assumption)
        return self.plan_scene([node], source_units=source)[node.node_id].plan

    def plan_scene(self, nodes: Sequence[SceneNode], *, source_units: SourceUnits | None = None) -> dict[str, TransformRecord]:
        units = source_units if source_units is not None else self.source_units
        ratio, unit_diags = units.resolve()
        lookup: dict[str, SceneNode] = {}
        for node in nodes:
            if not node.node_id or node.node_id in lookup:
                raise TransformError("Missing or duplicate node identifier")
            lookup[node.node_id] = node
        for node in nodes:
            if node.parent_id is not None and node.parent_id not in lookup:
                raise TransformError("Missing parent identifier")
        order: list[str] = []
        states: dict[str, int] = {}
        depths: dict[str, int] = {}
        # Nonrecursive DFS: bounded depth, detects parent cycles without recursion limits.
        for root in lookup:
            if states.get(root) == 2:
                continue
            stack: list[tuple[str, bool, int]] = [(root, False, 0)]
            while stack:
                key, done, depth = stack.pop()
                if done:
                    parent_key = lookup[key].parent_id
                    depths[key] = (depths[parent_key] + 1) if parent_key is not None else 0
                    if depths[key] > self.max_depth:
                        raise TransformError("Hierarchy exceeds configured depth")
                    states[key] = 2
                    order.append(key)
                    continue
                if states.get(key) == 2:
                    continue
                if states.get(key) == 1:
                    raise TransformError("Parent cycle detected")
                if depth > self.max_depth:
                    raise TransformError("Hierarchy exceeds configured depth")
                states[key] = 1
                stack.append((key, True, depth))
                parent = lookup[key].parent_id
                if parent is not None:
                    stack.append((parent, False, depth+1))
        result: dict[str, TransformRecord] = {}
        for node_id in order:
            node = lookup[node_id]
            meta = node.source_metadata
            fmt = meta.get("controller_format")
            space = meta.get("matrix_space", "source")
            local = None
            world = None
            offset = None
            normalized_offset = None
            diag = list(unit_diags) if space == "source" else []
            raw = None
            if node.local_matrix is not None:
                try:
                    raw = _matrix(node.local_matrix)
                except TransformError:
                    diag.append(Diagnostic("invalid_matrix", "Invalid or non-affine source matrix", "error", status="unsupported"))
            if fmt not in (None, "matrix4", "static_affine", "prs_static"):
                diag.append(Diagnostic("unsupported_controller", "Controller requires independently evaluated matrix", "error",
                                       evidence="controller_format", status="unsupported"))
            if space not in ("source", "normalized"):
                diag.append(Diagnostic("unsupported_space", "Matrix coordinate space not recognized", "error", status="unsupported"))
            if raw is None and node.local_matrix is None:
                diag.append(Diagnostic("missing_matrix", "No evaluated local matrix", "error", status="unsupported"))
            try:
                if meta.get("geometry_offset_matrix") is not None:
                    offset = _matrix(meta["geometry_offset_matrix"])
            except TransformError:
                diag.append(Diagnostic("invalid_offset", "Geometry/pivot offset matrix invalid", "error", status="unsupported"))
            # Ratios are needed only for raw source-space matrices.
            usable = raw is not None and (space == "normalized" or ratio is not None) and not any(
                d.status == "unsupported" for d in diag)
            if usable:
                try:
                    local = (raw if space == "normalized" else change_basis(raw, axes=self.axes, meters_per_unit=ratio))
                    if offset is not None:
                        normalized_offset = (offset if space == "normalized" else
                                             change_basis(offset, axes=self.axes, meters_per_unit=ratio))
                    parent = result[node.parent_id].plan.world_matrix if node.parent_id is not None else IDENTITY
                    if parent is None:
                        diag.append(Diagnostic("parent_unresolved", "Parent transform could not be evaluated", "error", status="unsupported"))
                        local = None
                    else:
                        world = multiply(parent, local)
                except TransformError:
                    diag.append(Diagnostic("invalid_conversion", "Unsafe or ill-conditioned transform", "error", status="unsupported"))
                    local = world = None
            # No successful plan can be constructed with unresolved units.
            if space == "source" and ratio is None:
                local = world = None
            lp, wp = (classify(local) if local is not None else None), (classify(world) if world is not None else None)
            for label, props in (("local", lp), ("world", wp)):
                if props is not None:
                    if props.singular:
                        diag.append(Diagnostic("singular_"+label, "Affine matrix is singular/near singular", "warning"))
                    if props.shear:
                        diag.append(Diagnostic("shear_"+label, "Shear present; do not decompose to TRS", "warning"))
                    if props.mirrored:
                        diag.append(Diagnostic("mirrored_"+label, "Negative determinant/mirrored geometry", "info", status="success"))
            geometry_world = multiply(world, normalized_offset) if world is not None and normalized_offset is not None else world
            plan = TransformPlan(local, world, ratio, tuple(diag))
            evidence = TransformEvidence(raw, offset, normalized_offset, str(space), ratio,
                                         self.axes.basis() if ratio is not None else None,
                                         world is not None and space == "source")
            result[node_id] = TransformRecord(plan, evidence, lp, wp, geometry_world)
        return {node.node_id: result[node.node_id] for node in nodes}


__all__ = ["AxisConvention", "BlenderDisplay", "SourceUnits", "TransformEngine", "TransformError",
           "TransformEvidence", "TransformRecord", "MatrixProperties", "IDENTITY", "multiply", "inverse",
           "determinant", "classify", "change_basis", "coordinate_basis", "point", "bake_points", "bounds",
           "parent_local_preserving_world"]
