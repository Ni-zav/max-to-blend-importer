# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure scene graph/animation validation and loss reporting for the F0 interface.

This module accepts *already decoded* facts. It does not interpret undocumented
MAX controller bytes, sample MAX animation, execute scripts, or apply transforms.
All numeric transforms handed to it must already be Blender RH Z-up/metres;
F1 owns conversion and must supply affirmative evidence for that precondition.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Literal

from ..interfaces import Diagnostic, SceneNode, SceneNodePlan

_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,95}$")
_SUPPORTED = frozenset({"translation", "rotation_quaternion", "scale"})
_CLASS_HINTS = {
    0x1002: "CAMERA",       # Legacy SKIPPABLE camera
    0x1020: "OTHER",        # Camera target, not a camera
    0x1011: "LIGHT",        # Omni
    0x1013: "LIGHT",        # Free Direct
    0x5FD602DF3C5575A1: "LIGHT",  # VRayLight; parameters unsupported
}


def class_hint(native_guid: int | None) -> str:
    """Only a class *hint* from upstream's SKIPPABLE table; not a decoder."""
    return _CLASS_HINTS.get(native_guid, "UNKNOWN")


def _finite(value: object) -> bool:
    return type(value) in (float, int) and math.isfinite(value)


def _positive(value: object) -> bool:
    return _finite(value) and value > 0


def _diag(code: str, reason: str, evidence: "Evidence | None", *, error: bool = False) -> Diagnostic:
    return Diagnostic(code, reason, "error" if error else "warning",
                      evidence.token() if evidence else None,
                      "failed" if error else "partial")


@dataclass(frozen=True)
class Evidence:
    """Bounded non-identifying source locator. No file paths or object names."""
    stream: Literal["Scene", "Config", "ClassDirectory", "ClassDirectory3"]
    chunk_type: int | None = None
    record_index: int | None = None

    def __post_init__(self) -> None:
        if self.stream not in {"Scene", "Config", "ClassDirectory", "ClassDirectory3"}:
            raise ValueError("stream must be a known MAX stream, not an input path")
        if self.chunk_type is not None and (type(self.chunk_type) is not int or
                                            not 0 <= self.chunk_type <= 0xffff):
            raise ValueError("invalid native chunk id")
        if self.record_index is not None and (type(self.record_index) is not int or
                                              not 0 <= self.record_index <= 1_000_000):
            raise ValueError("invalid bounded record index")

    def token(self) -> str:
        return (self.stream +
                (f":0x{self.chunk_type:04x}" if self.chunk_type is not None else "") +
                (f":record={self.record_index}" if self.record_index is not None else ""))


@dataclass(frozen=True)
class Timeline:
    start_frame: int | None = None
    end_frame: int | None = None
    fps: float | None = None
    evidence: Evidence | None = None


@dataclass(frozen=True)
class Camera:
    projection: Literal["PERSPECTIVE", "ORTHOGRAPHIC", "UNKNOWN"] = "UNKNOWN"
    horizontal_fov_rad: float | None = None
    focal_length_mm: float | None = None
    filmback_width_mm: float | None = None
    filmback_height_mm: float | None = None
    shift_x: float | None = None
    shift_y: float | None = None
    ortho_width_m: float | None = None
    clip_near_m: float | None = None
    clip_far_m: float | None = None


@dataclass(frozen=True)
class Light:
    kind: Literal["POINT", "SUN", "SPOT", "AREA", "UNKNOWN"] = "UNKNOWN"
    intensity: float | None = None
    intensity_unit: Literal["SOURCE_UNVERIFIED", "WATTS", "LUMENS", "CANDELA"] = "SOURCE_UNVERIFIED"
    color_linear_rgb: tuple[float, float, float] | None = None
    area_size_m: tuple[float, float] | None = None
    renderer_photometry_unsupported: bool = False


@dataclass(frozen=True)
class Layer:
    layer_id: str
    evidence: Evidence
    name: str
    parent_layer_id: str | None = None
    visible: bool | None = None


@dataclass(frozen=True)
class NodeDetails:
    node: SceneNode
    evidence: Evidence
    camera: Camera | None = None
    light: Light | None = None
    layer_ids: tuple[str, ...] = ()
    visible: bool | None = None
    # Set by F1 only after both axis AND unit normalization were verified.
    normalized_transform: bool | None = None
    native_guid: int | None = None


@dataclass(frozen=True)
class Keyframe:
    frame: float
    value: tuple[float, ...]


@dataclass(frozen=True)
class TransformTrack:
    target_id: str | None
    channel: str
    mode: Literal["KEYED", "SAMPLED"]
    keys: tuple[Keyframe, ...]
    evidence: Evidence
    interpolation: Literal["UNKNOWN", "LINEAR", "CONSTANT"] = "UNKNOWN"
    interpolation_verified: bool = False
    normalized_values: bool | None = None
    # A controller kind is a provenance label, never executed as source code.
    controller_supported: bool = True


@dataclass(frozen=True)
class ScenePlan:
    nodes: tuple[SceneNodePlan, ...]
    details: tuple[NodeDetails, ...]
    layers: tuple[Layer, ...]
    timeline: Timeline
    tracks: tuple[TransformTrack, ...]
    diagnostics: tuple[Diagnostic, ...]
    status: Literal["success", "partial", "failed"]
    # This is validation of decoded plans, NOT native .max fidelity.


class NodePlanner:
    """Satisfies the F0 SceneNodePlanner.plan(SceneNode) protocol."""

    def plan(self, node: SceneNode) -> SceneNodePlan:
        issues: list[Diagnostic] = []
        if not _ID.fullmatch(node.node_id):
            issues.append(_diag("invalid_node_id", "Invalid manifest object id", None, error=True))
        if node.parent_id is not None and not _ID.fullmatch(node.parent_id):
            issues.append(_diag("invalid_parent_id", "Invalid parent object id", None, error=True))
        if not node.name or len(node.name) > 256:
            issues.append(_diag("invalid_node_name", "Object name missing or too long", None, error=True))
        if node.local_matrix is not None:
            try:
                valid = len(node.local_matrix) == 4 and all(
                    len(row) == 4 and all(_finite(v) for v in row) for row in node.local_matrix)
            except (TypeError, ValueError):
                valid = False
            if not valid:
                issues.append(_diag("invalid_local_matrix", "Expected finite 4x4 matrix", None, error=True))
        return SceneNodePlan(node, tuple(issues))


def _camera_issues(cam: Camera, ev: Evidence) -> list[Diagnostic]:
    problems: list[Diagnostic] = []
    if cam.projection == "UNKNOWN":
        problems.append(_diag("camera_projection_unknown", "Camera projection not verified", ev))
    for name in ("horizontal_fov_rad", "focal_length_mm", "filmback_width_mm",
                 "filmback_height_mm", "ortho_width_m", "clip_near_m", "clip_far_m"):
        v = getattr(cam, name)
        if v is not None and not _positive(v):
            problems.append(_diag("invalid_camera_parameter", f"Invalid {name}", ev, error=True))
    if cam.horizontal_fov_rad is not None and _finite(cam.horizontal_fov_rad) and not 0 < cam.horizontal_fov_rad < math.pi:
        problems.append(_diag("invalid_camera_fov", "Horizontal FOV outside (0, pi)", ev, error=True))
    for name in ("shift_x", "shift_y"):
        v = getattr(cam, name)
        if v is not None and not _finite(v):
            problems.append(_diag("invalid_camera_shift", f"Nonfinite {name}", ev, error=True))
    if (cam.clip_far_m is not None and cam.clip_near_m is not None and
        _finite(cam.clip_far_m) and _finite(cam.clip_near_m) and cam.clip_far_m <= cam.clip_near_m):
        problems.append(_diag("invalid_camera_clip", "Far clipping must exceed near", ev, error=True))
    if cam.projection == "PERSPECTIVE" and cam.horizontal_fov_rad is None and cam.focal_length_mm is None:
        problems.append(_diag("camera_lens_missing", "Perspective lens/FOV unavailable", ev))
    if cam.projection == "ORTHOGRAPHIC" and cam.ortho_width_m is None:
        problems.append(_diag("camera_ortho_size_missing", "Orthographic width unavailable", ev))
    if (cam.horizontal_fov_rad is not None and _positive(cam.focal_length_mm) and
        _positive(cam.filmback_width_mm) and 0 < cam.horizontal_fov_rad < math.pi and
        abs(2 * math.atan(cam.filmback_width_mm / (2 * cam.focal_length_mm)) - cam.horizontal_fov_rad) > 1e-3):
        problems.append(_diag("camera_lens_inconsistent", "FOV contradicts focal length and filmback", ev))
    return problems


def _light_issues(light: Light, ev: Evidence) -> list[Diagnostic]:
    issues: list[Diagnostic] = []
    if light.kind == "UNKNOWN":
        issues.append(_diag("light_kind_unsupported", "Unknown/unsupported light class", ev))
    if light.intensity is not None and (not _finite(light.intensity) or light.intensity < 0):
        issues.append(_diag("invalid_light_intensity", "Intensity must be finite and nonnegative", ev, error=True))
    if light.intensity is not None and light.intensity_unit == "SOURCE_UNVERIFIED":
        issues.append(_diag("light_intensity_units_unknown", "MAX/renderer intensity units not verified", ev))
    if light.color_linear_rgb is not None and (len(light.color_linear_rgb) != 3 or
                                                any(not _finite(v) or v < 0 for v in light.color_linear_rgb)):
        issues.append(_diag("invalid_light_color", "Expected finite, nonnegative linear RGB", ev, error=True))
    if light.area_size_m is not None and (len(light.area_size_m) != 2 or
                                          any(not _positive(v) for v in light.area_size_m)):
        issues.append(_diag("invalid_light_area", "Expected positive rectangular dimensions", ev, error=True))
    if light.kind == "AREA" and light.area_size_m is None:
        issues.append(_diag("light_area_unknown", "Area-light dimensions not decoded", ev))
    if light.renderer_photometry_unsupported:
        issues.append(_diag("renderer_photometry_unsupported", "Renderer-specific photometry unsupported", ev))
    return issues


def _track_issues(track: TransformTrack, ids: set[str], timeline: Timeline) -> list[Diagnostic]:
    issues: list[Diagnostic] = []
    ev = track.evidence
    if track.target_id is None or track.target_id not in ids:
        issues.append(_diag("animation_target_missing", "Animation target not found", ev, error=True))
    if track.channel not in _SUPPORTED or not track.controller_supported:
        issues.append(_diag("unsupported_controller", "Controller/channel is not supported", ev))
    if not track.keys:
        issues.append(_diag("animation_source_missing", "No decoded animation keys/samples", ev))
    if track.normalized_values is not True:
        issues.append(_diag("animation_axes_unverified", "F1 normalized axes/metres not verified", ev))
    if track.interpolation != "UNKNOWN" and not track.interpolation_verified:
        issues.append(_diag("interpolation_unverified", "Interpolation lacks verified source semantics", ev))
    if track.mode == "SAMPLED" and track.interpolation != "UNKNOWN":
        issues.append(_diag("sample_interpolation_unsupported", "Samples cannot assert native interpolation", ev))
    length = 4 if track.channel == "rotation_quaternion" else 3
    prev = -math.inf
    for key in track.keys:
        if not _finite(key.frame) or key.frame <= prev or len(key.value) != length or any(
                not _finite(v) for v in key.value):
            issues.append(_diag("invalid_animation_keys", "Invalid frame order or track values", ev, error=True))
            break
        if (track.channel == "rotation_quaternion" and
                abs(sum(v * v for v in key.value) - 1.0) > 1e-3):
            issues.append(_diag("invalid_rotation_quaternion", "Quaternion is not normalized (w,x,y,z)", ev, error=True))
            break
        if (timeline.start_frame is not None and timeline.end_frame is not None and
                (key.frame < timeline.start_frame or key.frame > timeline.end_frame)):
            issues.append(_diag("key_outside_timeline", "Keyframe outside source timeline", ev))
        prev = key.frame
    return issues


def build_scene(nodes: tuple[NodeDetails, ...], *, timeline: Timeline | None = None,
                tracks: tuple[TransformTrack, ...] = (), layers: tuple[Layer, ...] = ()) -> ScenePlan:
    """Validate decoded facts; do not perform source decoding or claim fidelity."""
    if len(nodes) > 100_000 or len(layers) > 100_000 or len(tracks) > 100_000 or sum(len(t.keys) for t in tracks) > 1_000_000:
        raise ValueError("scene description exceeds fixed resource budget")
    timeline = timeline or Timeline()
    issues: list[Diagnostic] = []
    if timeline.fps is None:
        issues.append(_diag("fps_unknown", "Scene timebase is not decoded", timeline.evidence))
    elif not _positive(timeline.fps) or timeline.fps > 1000:
        issues.append(_diag("invalid_fps", "Scene FPS must be finite and positive", timeline.evidence, error=True))
    if timeline.start_frame is None or timeline.end_frame is None:
        issues.append(_diag("frame_range_unknown", "Scene frame range is not decoded", timeline.evidence))
    elif (type(timeline.start_frame) is not int or type(timeline.end_frame) is not int or
          timeline.end_frame < timeline.start_frame):
        issues.append(_diag("invalid_frame_range", "Invalid scene frame range", timeline.evidence, error=True))
    planner = NodePlanner()
    planned: list[SceneNodePlan] = []
    by_id: dict[str, NodeDetails] = {}
    for item in nodes:
        base = planner.plan(item.node)
        detail_issues: list[Diagnostic] = list(base.diagnostics)
        if item.node.node_id in by_id:
            detail_issues.append(_diag("duplicate_node_id", "Duplicate scene id", item.evidence, error=True))
        by_id[item.node.node_id] = item
        if item.camera and item.node.kind != "CAMERA":
            detail_issues.append(_diag("camera_type_mismatch", "Camera properties on non-camera", item.evidence, error=True))
        if item.light and item.node.kind != "LIGHT":
            detail_issues.append(_diag("light_type_mismatch", "Light properties on non-light", item.evidence, error=True))
        if item.camera:
            detail_issues.extend(_camera_issues(item.camera, item.evidence))
        if item.light:
            detail_issues.extend(_light_issues(item.light, item.evidence))
        if item.node.kind == "CAMERA" and not item.camera:
            detail_issues.append(_diag("camera_parameters_missing", "No camera projection decoded", item.evidence))
        if item.node.kind == "LIGHT" and not item.light:
            detail_issues.append(_diag("light_parameters_missing", "No light attributes decoded", item.evidence))
        if item.native_guid is not None and class_hint(item.native_guid) == "UNKNOWN":
            detail_issues.append(_diag("native_class_unknown", "No verified MAX class mapping", item.evidence))
        if item.visible is not None and type(item.visible) is not bool:
            detail_issues.append(_diag("invalid_visibility", "Visibility must be bool or unknown", item.evidence, error=True))
        if item.layer_ids and (len(item.layer_ids) > 128 or any(not _ID.fullmatch(x) for x in item.layer_ids)):
            detail_issues.append(_diag("invalid_layer_refs", "Invalid or excessive layer references", item.evidence, error=True))
        if item.normalized_transform is not True and item.node.local_matrix is not None:
            detail_issues.append(_diag("node_axes_unverified", "Local matrix axis/unit normalization unverified", item.evidence))
        planned.append(SceneNodePlan(item.node, tuple(detail_issues)))
        issues.extend(detail_issues)
    layer_by_id: dict[str, Layer] = {}
    for layer in layers:
        if not _ID.fullmatch(layer.layer_id) or not layer.name or len(layer.name) > 256:
            issues.append(_diag("invalid_layer", "Invalid layer id or name", layer.evidence, error=True))
        if layer.visible is not None and type(layer.visible) is not bool:
            issues.append(_diag("invalid_layer_visibility", "Layer visibility must be bool or unknown", layer.evidence, error=True))
        if layer.layer_id in layer_by_id:
            issues.append(_diag("duplicate_layer", "Duplicate layer id", layer.evidence, error=True))
        layer_by_id[layer.layer_id] = layer
    for layer in layers:
        if layer.parent_layer_id is not None and layer.parent_layer_id not in layer_by_id:
            issues.append(_diag("layer_parent_missing", "Missing parent layer", layer.evidence, error=True))
    # Iterative cycle check for layer graph, independent from object parenting.
    walked: set[str] = set()
    for first in layer_by_id:
        chain: set[str] = set()
        current: str | None = first
        while current in layer_by_id and current not in walked:
            if current in chain:
                issues.append(_diag("layer_cycle", "Cycle in layer hierarchy", layer_by_id[current].evidence, error=True))
                break
            chain.add(current)
            current = layer_by_id[current].parent_layer_id
        walked.update(chain)
    ids = set(by_id)
    for item in nodes:
        parent = item.node.parent_id
        if parent is not None and parent not in ids:
            issues.append(_diag("parent_missing", "Missing parent object", item.evidence, error=True))
        if parent == item.node.node_id:
            issues.append(_diag("parent_self", "Scene node parents itself", item.evidence, error=True))
    # Iterative linear-time cycle detection: no recursion on hostile hierarchies.
    visited: set[str] = set()
    for initial in ids:
        path: set[str] = set()
        current: str | None = initial
        while current in ids and current not in visited:
            if current in path:
                issues.append(_diag("parent_cycle", "Cycle in scene hierarchy", by_id[current].evidence, error=True))
                break
            path.add(current)
            current = by_id[current].node.parent_id
        visited.update(path)
    for item in nodes:
        for layer in item.layer_ids:
            if layer not in layer_by_id:
                issues.append(_diag("layer_target_missing", "Assigned layer has no decoded layer record", item.evidence))
    for track in tracks:
        issues.extend(_track_issues(track, ids, timeline))
    status = "failed" if any(d.status == "failed" for d in issues) else "partial" if issues else "success"
    return ScenePlan(tuple(planned), nodes, layers, timeline, tracks, tuple(issues), status)


def manifest_animation_summaries(plan: ScenePlan) -> list[dict[str, object]]:
    """Produce v1 *coverage summaries only*: schema v1 has no keyframe payload.

    F6 must negotiate a versioned schema/adapter track payload to persist keys.
    Never mark playback as faithfully reproduced by these summaries.
    """
    summaries: list[dict[str, object]] = []
    for index, track in enumerate(plan.tracks):
        issues = _track_issues(track, {x.node.node_id for x in plan.details}, plan.timeline)
        supported = (track.channel in _SUPPORTED and track.controller_supported and
                     bool(track.keys) and track.normalized_values is True and
                     track.target_id is not None and not issues)
        warnings = [
            {"code": d.code, "severity": d.severity, "reason": d.message,
             "evidence": d.evidence, "attribute": track.channel[:128],
             "before": None, "after": None} for d in issues
        ]
        # Even a validated track is only a plan until F6 integrates a payload.
        warnings.append({"code": "keyframe_payload_not_in_v1", "severity": "warning",
                         "reason": "Manifest v1 has no keyframe values or interpolation field",
                         "evidence": track.evidence.token(), "attribute": track.channel[:128],
                         "before": None, "after": None})
        summaries.append({
            "id": f"Animation{index}", "target_object_id": track.target_id if track.target_id and _ID.fullmatch(track.target_id) else None,
            "start_frame": plan.timeline.start_frame, "end_frame": plan.timeline.end_frame,
            "fps": plan.timeline.fps if _positive(plan.timeline.fps) else None,
            "supported_tracks": [track.channel] if supported else [],
            "unsupported_tracks": [] if supported else [track.channel[:80]],
            "coverage": "partial" if supported else "unsupported",
            "warnings": warnings,
        })
    return summaries
