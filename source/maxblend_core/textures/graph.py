# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Conservative traversal of validated, normalized MAX texmap graph records.

F6 must translate binary chunks/metadata IDs to ordinary mappings; this module
never invokes the legacy parser on untrusted bytes or guesses GUID offsets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ..interfaces import Diagnostic
from .resolver import SafeTextureResolver, ResolutionDetail

_BITMAP_CLASSES = frozenset(("bitmap", "bitmaptexture", "bitmaptex", "bitmaptexturemap",
                             "vraybitmap", "vraybitmaptexture", "coronabitmap", "coronabitmaptexture"))
_WRAPPER_CLASSES = frozenset(("colorcorrection", "colorcorrect", "coronacolorcorrect", "vraycolor", "vraycolorcorrection",
                              "mix", "mixmap", "composite", "falloff", "falloffmap", "normalbump", "vraynormalmap", "coronanormal"))
_PATH_KEYS = ("filename", "file_name", "filepath", "bitmap_path", "texture_path", "path", "file")
_CHILD_KEYS = ("input", "map", "texture", "texmap", "source", "bitmap", "submap", "subtexmap",
               "color1", "color2", "map1", "map2", "mask", "maps", "children", "inputs", "layers")
_GUID_ALIASES = {"0x240": "bitmap", "0x2c1017d6769144b": "vraybitmap"}


@dataclass(frozen=True)
class BitmapSource:
    source_id: str
    class_name: str
    slot: str | None
    raw_reference: str = field(repr=False)  # never serialize or print
    graph_trace: tuple[str, ...] = ()
    approximated: bool = False


@dataclass(frozen=True)
class TextureGraphResult:
    sources: tuple[BitmapSource, ...]
    diagnostics: tuple[Diagnostic, ...]


def _kind(node: Mapping[str, object]) -> str:
    cls = node.get("class", node.get("class_name", node.get("type", node.get("guid", ""))))
    if not isinstance(cls, (str, int)):
        return "unknown"
    key = (hex(cls) if isinstance(cls, int) else cls).strip().casefold().replace("_", "").replace(" ", "")
    return _GUID_ALIASES.get(key, key)


def _safe_diag(code: str, message: str) -> Diagnostic:
    return Diagnostic(code, message, "warning", evidence="texmap graph structure")


def extract_bitmap_sources(graph: object, *, slot: str | None = None,
                           max_nodes: int = 512, max_depth: int = 32) -> TextureGraphResult:
    """Find explicit file-backed leaves; wrapper math is never reconstructed.

    Data contract: graph is nested mappings/lists. Non-graph parser references
    must be normalized by F6; arbitrary Python objects are never introspected.
    Cyclic Python containers are detected by identity with depth/node budgets.
    """
    if not (1 <= max_nodes <= 10000 and 1 <= max_depth <= 128):
        raise ValueError("Invalid graph limits")
    found: list[BitmapSource] = []
    diagnostics: list[Diagnostic] = []
    active: set[int] = set()
    count = 0

    def visit(node: object, trace: tuple[str, ...], depth: int, current_slot: str | None,
              approximated: bool) -> None:
        nonlocal count
        if not isinstance(node, (Mapping, list, tuple)):
            return
        if count >= max_nodes or depth > max_depth:
            diagnostics.append(_safe_diag("GRAPH_LIMIT", "Graph depth or node count budget exhausted"))
            return
        ident = id(node)
        if ident in active:
            diagnostics.append(_safe_diag("GRAPH_CYCLE", "Cyclic texmap reference detected"))
            return
        count += 1
        active.add(ident)
        try:
            if isinstance(node, Mapping):
                kind = _kind(node)
                known = kind in _BITMAP_CLASSES or kind in _WRAPPER_CLASSES
                if kind in _WRAPPER_CLASSES:
                    approximated = True
                    diagnostics.append(_safe_diag("WRAPPER_APPROXIMATION", "Texmap wrapper evaluated only as linked bitmap references, not renderer shader math"))
                elif not known:
                    diagnostics.append(_safe_diag("UNKNOWN_TEXMAP", "Unrecognized texmap class; any child links are speculative"))
                trace_next = trace + ((kind if known else "unknown"),)
                next_slot = current_slot
                node_slot = node.get("slot")
                if isinstance(node_slot, str) and not current_slot:
                    next_slot = node_slot
                if kind in _BITMAP_CLASSES:
                    refs = [node[key] for key in _PATH_KEYS if key in node and isinstance(node[key], str) and node[key]]
                    if len(set(refs)) > 1:
                        diagnostics.append(_safe_diag("MULTIPLE_BITMAP_PATHS", "Bitmap node carries inconsistent linked file fields"))
                    if refs:
                        found.append(BitmapSource(f"bitmap-{len(found)+1:04d}", kind, next_slot, refs[0], trace_next, approximated))
                    else:
                        diagnostics.append(_safe_diag("BITMAP_WITHOUT_PATH", "Bitmap node has no validated file metadata"))
                for key in _CHILD_KEYS:
                    if key in node:
                        visit(node[key], trace_next, depth + 1, next_slot, approximated)
            else:
                for item in node[:max_nodes]:
                    visit(item, trace, depth + 1, current_slot, approximated)
        finally:
            active.remove(ident)
    visit(graph, (), 0, slot, False)
    return TextureGraphResult(tuple(found), tuple(diagnostics))


def resolve_graph(graph: object, resolver: SafeTextureResolver, *, slot: str | None = None) -> tuple[TextureGraphResult, tuple[ResolutionDetail, ...]]:
    nodes = extract_bitmap_sources(graph, slot=slot)
    resolutions = tuple(resolver.resolve_detailed(source.raw_reference, slot=source.slot) for source in nodes.sources)
    return nodes, resolutions
