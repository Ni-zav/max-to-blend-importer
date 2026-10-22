# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Blender-only material construction from F3 plans, never from untrusted paths.

F4 resolves and authorizes images. F2 assigns mesh slots and face IDs.
F6 calls build_material after decoding native chunks, then consumes diagnostics.
"""
from __future__ import annotations

from dataclasses import dataclass

from maxblend_core.interfaces import Diagnostic
from . import MaterialDetail, TextureIntent

# Node socket names changed in Blender 4.0, while materials can be loaded
# from earlier versions. Prefer actual sockets rather than numeric indices.
_SOCKET_NAMES = {
    "base_color": ("Base Color",),
    "metallic": ("Metallic",),
    "roughness": ("Roughness",),
    "ior": ("IOR",),
    "opacity": ("Alpha",),
    "transmission": ("Transmission Weight", "Transmission"),
    "coat": ("Coat Weight", "Clearcoat"),
    "emission": ("Emission Color", "Emission"),
    "normal": ("Normal",),
}


def socket_names(channel: str, version: tuple[int, int, int]) -> tuple[str, ...]:
    names = _SOCKET_NAMES[channel]
    return names if version >= (4, 0, 0) else tuple(reversed(names))


def _warning(code: str, reason: str, evidence: str | None = None) -> Diagnostic:
    return Diagnostic(code, reason, "warning", evidence=evidence, status="partial")


@dataclass(frozen=True)
class MaterialBuildResult:
    material: object
    linked_channels: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]
    status: str  # 'partial', 'unsupported', or 'success'


def _socket(node, channel: str, version: tuple[int, int, int]):
    for name in socket_names(channel, version):
        socket = node.inputs.get(name)
        if socket is not None:
            return socket
    return None


def _scalar_or_rgba(value):
    if isinstance(value, (list, tuple)):
        return (*tuple(value[:3]), 1.0)
    return value


def build_material(detail: MaterialDetail, images=None, *, bpy_module=None) -> MaterialBuildResult:
    """Create a fresh Blender material and link only F4-provided Image objects.

    No name-based cache, image loading/search, or external network calls.
    Pass bpy_module explicitly for isolated hosts; otherwise import bpy lazily.
    Material data are not executed as scripts, node group names, or drivers.
    """
    if bpy_module is None:
        import bpy as bpy_module  # only Blender integration has this dependency
    if images is None:
        images = {}
    material = bpy_module.data.materials.new(detail.display_name)
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    shader = tree.nodes.new("ShaderNodeBsdfPrincipled")
    tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    version = tuple(bpy_module.app.version)
    diagnostics = list(detail.plan.diagnostics)
    linked: list[str] = []
    if detail.plan.coverage in ("unsupported", "unknown"):
        diagnostics.append(_warning("preview_only", "Neutral Blender preview is not recovered shader fidelity"))
    material["maxblend.material_id"] = detail.plan.material_id
    if detail.plan.original_class is not None:
        material["maxblend.original_class"] = detail.plan.original_class

    for channel, record in detail.plan.pbr_slots.items():
        if channel == "normal" or record is None or record["value"] is None:
            continue
        socket = _socket(shader, channel, version)
        if socket is None:
            diagnostics.append(_warning("unavailable_socket", "Blender version has no matching node socket", channel))
            continue
        socket.default_value = _scalar_or_rgba(record["value"])

    role_by_image: dict[str, set[str]] = {}
    for intent in detail.textures:
        role_by_image.setdefault(intent.texture_id, set()).add(intent.role)
    for intent in detail.textures:
        channel = intent.channel
        if intent.state != "found":
            diagnostics.append(_warning("unresolved_image", "Image was not verified by F4", channel))
            continue
        image = images.get(intent.texture_id)
        if image is None:
            diagnostics.append(_warning("missing_image_binding", "F4 did not provide a resolved Blender Image", channel))
            continue
        if len(role_by_image[intent.texture_id]) > 1:
            diagnostics.append(_warning("conflicting_color_space", "Shared Image needs both color/data interpretation",
                                        channel))
            continue
        socket = _socket(shader, channel, version)
        if socket is None:
            diagnostics.append(_warning("unavailable_socket", "Blender version cannot link this channel", channel))
            continue
        try:
            if intent.role == "data":
                image.colorspace_settings.name = "Non-Color"
        except (AttributeError, TypeError, ValueError):
            diagnostics.append(_warning("color_space_unverified", "Cannot confirm Non-Color data interpretation",
                                        channel))
            continue
        image_node = tree.nodes.new("ShaderNodeTexImage")
        image_node.image = image
        source = image_node.outputs.get("Alpha" if intent.use_alpha and channel == "opacity" else "Color")
        if source is None:
            diagnostics.append(_warning("missing_image_output", "Image output socket unavailable", channel))
            tree.nodes.remove(image_node)
            continue
        if channel == "normal":
            normal = tree.nodes.new("ShaderNodeNormalMap")
            tree.links.new(source, normal.inputs["Color"])
            tree.links.new(normal.outputs["Normal"], socket)
        elif intent.transform == "invert":
            # 1 - glossiness -> roughness; requires a real Math node.
            invert = tree.nodes.new("ShaderNodeMath")
            invert.operation = "SUBTRACT"
            invert.inputs[0].default_value = 1.0
            tree.links.new(source, invert.inputs[1])
            tree.links.new(invert.outputs[0], socket)
        else:
            tree.links.new(source, socket)
        linked.append(channel)

    alpha = detail.plan.pbr_slots.get("opacity")
    if (alpha is not None and alpha["value"] is not None and alpha["value"] < 1) or "opacity" in linked:
        if hasattr(material, "surface_render_method"):
            try:
                material.surface_render_method = "DITHERED"
            except (TypeError, ValueError):
                diagnostics.append(_warning("alpha_render_method", "Could not enable transparency rendering"))
        elif hasattr(material, "blend_method"):
            material.blend_method = "HASHED"
        else:
            diagnostics.append(_warning("alpha_render_method", "Transparency rendering API unavailable"))
    if detail.two_sided:
        if hasattr(material, "use_backface_culling"):
            material.use_backface_culling = False
        if detail.front_id and detail.back_id and detail.front_id != detail.back_id:
            diagnostics.append(_warning("backface_not_rebuilt", "Distinct backface material not reconstructed"))
    status = ("unsupported" if detail.plan.coverage == "unsupported" else
              "partial" if diagnostics or detail.plan.coverage != "supported" else "success")
    return MaterialBuildResult(material, tuple(linked), tuple(diagnostics), status)


__all__ = ["MaterialBuildResult", "build_material", "socket_names"]
