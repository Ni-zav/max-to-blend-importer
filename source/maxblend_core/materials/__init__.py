# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Offline F3 material plans. Input is already-decoded, untrusted data from F6.

No MAX parser, filesystem, image path lookup, scripts, or bpy imports here.
The seven manifest PBR fields are a strict subset of local shader slots.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Mapping

from maxblend_core.interfaces import Diagnostic, MaterialPlan

PBR_FIELDS = ("base_color", "roughness", "metallic", "normal", "opacity", "ior", "emission")
EXTRA_FIELDS = ("transmission", "coat")
ALL_FIELDS = PBR_FIELDS + EXTRA_FIELDS
_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,95}$")
_CLASS = {
    "standard": "Standard", "standardmtl": "Standard",
    "physical": "Physical", "physicalmtl": "Physical",
    "multisubobject": "Multi/Sub", "multisub": "Multi/Sub",
    "coronaphysical": "CoronaPhysical", "coronaphysicalmtl": "CoronaPhysical",
    "corona": "Corona", "coronamtl": "Corona",
    "vray": "VRay", "vraymtl": "VRay",
    "vray2sided": "VRay2Sided", "vray2sidedmtl": "VRay2Sided",
    "coronalayered": "CoronaLayered", "coronalayeredmtl": "CoronaLayered",
    "shellac": "Shellac", "twosided": "TwoSided", "twosidedmtl": "TwoSided",
}
_COMPOSITES = {"Multi/Sub", "VRay2Sided", "CoronaLayered", "Shellac", "TwoSided"}
_ALIAS = {
    "base_color": ("base_color", "basecolor", "diffuse_color", "diffuse", "color"),
    "roughness": ("roughness", "base_roughness", "refl_roughness"),
    "metallic": ("metallic", "metalness", "metallic_level", "metalness_level"),
    "opacity": ("opacity", "alpha", "opacity_level"),
    "ior": ("ior", "refraction_ior", "refraction", "specular_ior", "refr_ior"),
    "emission": ("emission", "emissive", "emission_color", "self_illum_color"),
    "transmission": ("transmission", "transmission_weight", "refraction_amount"),
    "coat": ("coat", "coat_weight", "clearcoat", "clearcoat_weight"),
}
_TEX = {
    "bitmap": "base_color", "basecolor": "base_color", "base_color": "base_color",
    "diffuse": "base_color", "roughness": "roughness", "shinmap": "roughness",
    "glossmap": "roughness", "glossiness": "roughness",
    "metallic": "metallic", "metalness": "metallic",
    "normalmap": "normal", "normal": "normal", "bump": "normal",
    "opacity": "opacity", "alpha": "opacity", "transmap": "opacity",
    "emission": "emission", "emissive": "emission",
    "transmission": "transmission", "coat": "coat",
}
_DATA = {"roughness", "metallic", "normal", "opacity", "transmission", "coat"}


@dataclass(frozen=True)
class TextureIntent:
    channel: str
    texture_id: str
    role: str
    transform: str = "direct"
    state: str = "unknown"
    use_alpha: bool = False


@dataclass(frozen=True)
class MaterialDetail:
    plan: MaterialPlan
    display_name: str
    assignment_ids: tuple[str, ...] = ()
    submaterial_ids: tuple[tuple[int, str], ...] = ()  # Native IDs, not polygon slot indices
    layer_ids: tuple[str, ...] = ()
    front_id: str | None = None
    back_id: str | None = None
    two_sided: bool = False
    textures: tuple[TextureIntent, ...] = ()
    source_parameters: Mapping[str, object] = field(default_factory=dict)
    unknown_parameters: tuple[tuple[str, object], ...] = ()
    slot_provenance: Mapping[str, str] = field(default_factory=dict)
    warning_counts: Mapping[str, int] = field(default_factory=dict)

    def manifest_pbr(self) -> dict[str, object]:
        return {key: self.plan.pbr_slots.get(key) for key in PBR_FIELDS}


def _diag(code: str, reason: str, evidence: str | None = None, severity: str = "warning") -> Diagnostic:
    return Diagnostic(code, reason, severity, evidence=evidence, status="partial")


def _id(value: object) -> bool:
    return isinstance(value, str) and bool(_IDENT.fullmatch(value))


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _safe(value: object) -> object:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (float, int)):
        return _number(value)
    if isinstance(value, str):
        return value if len(value) <= 512 else None
    if isinstance(value, (tuple, list)) and len(value) in (3, 4):
        nums = tuple(_number(x) for x in value)
        return nums if all(x is not None for x in nums) else None
    return None


def _scalar(channel: str, raw: object, key: str, ds: list[Diagnostic]):
    if channel in ("base_color", "emission"):
        if isinstance(raw, (list, tuple)) and len(raw) in (3, 4):
            vals = tuple(_number(x) for x in raw)
            value = vals[:3] if all(x is not None and x >= 0 for x in vals) else None
        else:
            value = None
    else:
        value = _number(raw)
    if value is None:
        ds.append(_diag("invalid_parameter", "Invalid, missing, or nonfinite channel", key))
        return None
    if channel in ("roughness", "metallic", "opacity", "transmission", "coat") and not 0 <= value <= 1:
        ds.append(_diag("out_of_range", "Factor out of physical range; not silently clamped", key))
        return None
    if channel == "ior":
        if not 1 <= value <= 1000:
            ds.append(_diag("invalid_ior", "Invalid IOR omitted; Blender uses a safe default", key))
            return None
        if value > 3:
            ds.append(_diag("unusual_ior", "High IOR preserved, but merits manual review", key))
    return value


def plan_material(material_id: str, attributes: Mapping[str, object]) -> MaterialDetail:
    """Plan synthetic/decoded native parameters, preserving material identity.

    F6 must provide: class, name, params, textures (map-name -> F4 reference
    descriptor with id/kind/state), native-id submaterials, layer_ids,
    assignment_ids and front_id/back_id as available. No file paths are needed.
    """
    if not _id(material_id):
        raise ValueError("Invalid opaque material ID")
    if not isinstance(attributes, Mapping):
        raise TypeError("Decoded attributes must be a mapping")
    ds: list[Diagnostic] = []
    original = attributes.get("class")
    original = original if isinstance(original, str) and 0 < len(original) <= 128 else None
    family = _CLASS.get(re.sub("[^a-z0-9]", "", (original or "").lower()))
    renderer = attributes.get("renderer")
    if not isinstance(renderer, str) or not 0 < len(renderer) <= 128:
        renderer = ("V-Ray" if family in ("VRay", "VRay2Sided") else
                    "Corona" if family in ("Corona", "CoronaPhysical", "CoronaLayered") else None)
    name = attributes.get("name")
    name = name[:128] if isinstance(name, str) and name else material_id
    raw = attributes.get("params", {})
    if not isinstance(raw, Mapping):
        ds.append(_diag("invalid_parameter_block", "Native parameter block is not a mapping"))
        raw = {}
    if len(raw) > 256:
        ds.append(_diag("parameter_limit", "Native parameter limit exceeded", severity="error"))
    params: dict[str, object] = {}
    for k, v in list(raw.items())[:256]:
        if not isinstance(k, str) or not 0 < len(k) <= 128:
            ds.append(_diag("invalid_parameter_name", "Native parameter name invalid"))
            continue
        val = _safe(v)
        if val is None and v is not None:
            ds.append(_diag("unreadable_parameter", "Complex parameter retained as unknown", k))
        params[k] = val
    index = {k.casefold(): (k, v) for k, v in params.items()}
    used: set[str] = set()
    slots: dict[str, object] = {key: None for key in ALL_FIELDS}
    origins: dict[str, str] = {}

    def take(channel: str, aliases: tuple[str, ...], invert: bool = False):
        for alias in aliases:
            if alias not in index:
                continue
            key, raw_value = index[alias]
            used.add(key)
            value = _scalar(channel, raw_value, key, ds)
            if value is not None:
                if invert:
                    value = 1 - value
                slots[channel] = {
                    "value": value, "texture_id": None,
                    "provenance": {"method": "derived" if invert else "native",
                                   "evidence": key},
                }
                origins[channel] = ("1 - " if invert else "") + key
            return

    for channel, aliases in _ALIAS.items():
        take(channel, aliases)
    if slots["roughness"] is None:
        take("roughness", ("glossiness", "refl_glossiness", "glossines", "shininess", "shinines"), True)
    if slots["opacity"] is None:
        take("opacity", ("transparency",), True)

    raw_textures = attributes.get("textures", {})
    if not isinstance(raw_textures, Mapping):
        ds.append(_diag("invalid_texture_block", "Expected F4 texture descriptors"))
        raw_textures = {}
    intents: list[TextureIntent] = []
    if len(raw_textures) > 64:
        ds.append(_diag("texture_limit", "Texture channel limit exceeded"))
    for native_name, descriptor in list(raw_textures.items())[:64]:
        if not isinstance(native_name, str):
            ds.append(_diag("invalid_texture_name", "Invalid native map channel"))
            continue
        channel = _TEX.get(native_name.casefold())
        if channel is None:
            ds.append(_diag("unsupported_texture_channel", "Unmapped texture map", native_name[:128]))
            continue
        if not isinstance(descriptor, Mapping) or not _id(descriptor.get("id")):
            ds.append(_diag("missing_texture_id", "F4 texture reference ID missing", native_name[:128]))
            continue
        if descriptor.get("kind", "bitmap") != "bitmap":
            ds.append(_diag("unsupported_procedural_map", "Non-bitmap shader graph not reproducible",
                            native_name[:128]))
            continue
        state = descriptor.get("state", "unknown")
        if state not in ("found", "missing", "blocked", "ambiguous", "unknown"):
            state = "unknown"
        if state != "found":
            ds.append(_diag("unresolved_texture", "F4 has not verified bitmap presence", native_name[:128]))
        if native_name.casefold() in ("transmap", "bump"):
            ds.append(_diag("ambiguous_map_semantics", "Opacity/bump map semantics require confirmation",
                            native_name[:128]))
        if any(t.channel == channel for t in intents):
            ds.append(_diag("duplicate_map", "Conflicting maps target the same Principled socket",
                            native_name[:128]))
            continue
        intent = TextureIntent(channel, descriptor["id"],
                               "data" if channel in _DATA else "color",
                               "invert" if native_name.casefold() in ("glossmap", "glossiness") else "direct",
                               state, descriptor.get("use_alpha") is True)
        intents.append(intent)
        previous = slots[channel]
        slots[channel] = {
            "value": previous["value"] if previous else None,
            "texture_id": intent.texture_id,
            "provenance": previous["provenance"] if previous else
                          {"method": "native", "evidence": native_name[:128]},
        }

    submaterial_ids: list[tuple[int, str]] = []
    subs = attributes.get("submaterials", {})
    if isinstance(subs, Mapping):
        for native_id, child_id in list(subs.items())[:256]:
            if isinstance(native_id, int) and not isinstance(native_id, bool) and native_id >= 0 \
                    and _id(child_id) and native_id not in dict(submaterial_ids):
                submaterial_ids.append((native_id, child_id))
            else:
                ds.append(_diag("invalid_submaterial", "Invalid native material ID or reference"))
    elif subs:
        ds.append(_diag("invalid_submaterials", "Expected integer native-ID mapping"))
    assignments = attributes.get("assignment_ids", ())
    if not isinstance(assignments, (tuple, list)) or len(assignments) > 10000 \
            or not all(_id(x) for x in assignments):
        ds.append(_diag("invalid_assignments", "Unknown object assignment references"))
        assignments = ()
    layers = attributes.get("layer_ids", ())
    if not isinstance(layers, (tuple, list)) or len(layers) > 64 or not all(_id(x) for x in layers):
        ds.append(_diag("invalid_layers", "Layer material references invalid"))
        layers = ()
    front = attributes.get("front_id") if _id(attributes.get("front_id")) else None
    back = attributes.get("back_id") if _id(attributes.get("back_id")) else None
    two_sided = attributes.get("two_sided") is True or family in ("VRay2Sided", "TwoSided")
    if family is None:
        ds.append(_diag("unsupported_material_class", "Native material family not decoded"))
    elif family == "Standard":
        ds.append(_diag("legacy_shader_approximation", "Legacy specular workflow differs from PBR"))
    elif family in ("VRay", "Corona", "CoronaPhysical"):
        ds.append(_diag("renderer_shader_approximation", "Renderer BSDF is not native Principled"))
    elif family in _COMPOSITES:
        ds.append(_diag("composite_shader_loss", "Layer/submaterial shader graph not flattened"))
    if two_sided and front and back and front != back:
        ds.append(_diag("distinct_backface_shader", "Different front/back shading not reconstructed"))
    if (submaterial_ids or layers) and family not in _COMPOSITES:
        ds.append(_diag("unexpected_child_materials", "Unmapped child-material references"))
    unknown = tuple((k, v) for k, v in params.items() if k not in used)
    for key, _ in unknown[:64]:
        ds.append(_diag("unmapped_parameter", "Native property has no verified mapping", key))
    if len(unknown) > 64:
        ds.append(_diag("unmapped_parameter_count", "Additional unmapped properties recorded"))
    known = any(v is not None for v in slots.values())
    if family is not None and not known and family not in _COMPOSITES:
        ds.append(_diag("no_shader_evidence", "Material name alone is not shader fidelity"))
    coverage = ("unsupported" if family is None else
                "unknown" if not known and family not in _COMPOSITES else
                "partial" if ds or family != "Physical" else "supported")
    counts = {s: sum(d.severity == s for d in ds) for s in ("info", "warning", "error")}
    return MaterialDetail(MaterialPlan(material_id, original, renderer, slots, coverage, tuple(ds)),
                          name, tuple(assignments), tuple(submaterial_ids), tuple(layers),
                          front, back, two_sided, tuple(intents), params, unknown, origins, counts)


class MaterialPlannerV1:
    """Implementation of the Wave 0 MaterialPlanner protocol."""

    def plan(self, material_id: str, attributes: Mapping[str, object]) -> MaterialPlan:
        return plan_material(material_id, attributes).plan


__all__ = ["MaterialDetail", "TextureIntent", "MaterialPlannerV1",
           "plan_material", "PBR_FIELDS", "EXTRA_FIELDS"]
