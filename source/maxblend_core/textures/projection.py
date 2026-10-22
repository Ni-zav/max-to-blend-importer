# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Strict P0 scene-manifest-v1 texture projection for trusted F6 adapters.

Do not send the resulting manifest to public logs: even approved basenames,
identifiers and hashes can be client metadata. Default omits source_ref.
No filesystem reads, Blender imports, binary decoding or network calls.
"""
from __future__ import annotations

import re
from typing import Literal

from .resolver import ResolutionDetail, _reference_components, classify_channel

_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,95}\Z")
_SAFE_EVIDENCE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,95}\Z")
_CHANNEL = re.compile(r"[A-Za-z_][A-Za-z0-9_.:-]{0,79}\Z")
_SHA256 = re.compile(r"[a-fA-F0-9]{64}\Z")
_STATES = frozenset({"found", "missing", "ambiguous", "blocked"})
_ROLES = frozenset({"color", "data", "unknown"})
_PROVENANCE = frozenset({"native", "blender_evaluated", "derived", "user_supplied", "unknown"})

# Messages deliberately originate here, not from untrusted MAX attributes,
# local paths, arbitrary Diagnostic.message/evidence or OS exception text.
_REASONS = {
    "absolute_reference": "An absolute, network, or URL bitmap reference was not authorized",
    "path_traversal": "An unsafe relative path was rejected",
    "unsafe_pattern": "Unsafe bitmap filename or pattern was rejected",
    "invalid_reference": "An invalid bitmap reference was rejected",
    "invalid_unicode": "Invalid bitmap path encoding was rejected",
    "non_image_reference": "Reference did not identify a supported image format",
    "invalid_udim": "Invalid UDIM marker configuration",
    "udim_limit": "UDIM tile count exceeded the configured limit",
    "udim_1001_missing": "UDIM sequence does not contain tile 1001",
    "udim_single_tile": "UDIM reference matched only one tile",
    "hash_collision": "Distinct file contents match the same requested bitmap",
    "missing_texture": "No matching image was found inside the approved roots",
    "blocked_candidate": "Bitmap candidates failed safety or content checks",
    "incomplete_search": "An approved root could not be fully inspected",
    "no_approved_root": "No explicitly approved local asset root was supplied",
    "basename_recovery": "An explicitly permitted basename-only lookup was used",
    "unknown_texture_role": "No verified color-space role is available for this socket",
    "gloss_inversion": "Glossiness requires explicit inversion before roughness use",
    "graph_cycle": "A cyclic source texture graph reference was detected",
    "graph_limit": "Texture graph traversal exceeded a configured budget",
    "unknown_texmap": "Unrecognized source texture node requires separate verification",
    "wrapper_approximation": "Linked bitmap discovery does not reproduce wrapper shader math",
    "multiple_bitmap_paths": "Conflicting source bitmap fields require verification",
    "bitmap_without_path": "No validated bitmap path metadata was recovered",
    "color_space_mismatch": "The selected color-space role differs from the socket default",
}


def project_texture_v1(
    detail: ResolutionDetail,
    *,
    stable_id: str,
    provenance_method: Literal["native", "blender_evaluated", "derived", "user_supplied", "unknown"],
    provenance_evidence: str | None = None,
    publish_basename: bool = False,
) -> dict[str, object]:
    """Return exactly the P0 v1 texture item wire fields, without private paths.

    Identity and provenance are supplied by a trusted F6/P6 caller; never
    manufacture them from filename, path, traversal order or object id.
    Evidence accepts only caller-established non-sensitive identifiers, not
    arbitrary MAX strings or path text. The source_ref basename is opt-in for
    **local** manifests; public reports should keep it null.
    """
    if not isinstance(stable_id, str) or not _ID.fullmatch(stable_id):
        raise ValueError("Invalid P0 texture identifier")
    if provenance_method not in _PROVENANCE:
        raise ValueError("Invalid P0 provenance method")
    if provenance_evidence is not None and (
        not isinstance(provenance_evidence, str) or not _SAFE_EVIDENCE.fullmatch(provenance_evidence)
    ):
        raise ValueError("Provenance evidence must be a path-free identifier")
    if detail.state not in _STATES or detail.color_space_role not in _ROLES:
        raise ValueError("Invalid F0 texture status or color-space role")
    channel = detail.channel
    if channel is not None and (not isinstance(channel, str) or not _CHANNEL.fullmatch(channel)):
        raise ValueError("Unsafe texture channel identifier")

    digest = None
    if detail.state == "found" and detail.sha256 is not None:
        if not isinstance(detail.sha256, str) or not _SHA256.fullmatch(detail.sha256):
            raise ValueError("Invalid authorized SHA-256 fingerprint")
        digest = detail.sha256.lower()

    source_ref = None
    if publish_basename:
        # The resolver's sanitized relative reference is still treated as
        # untrusted here. Never serialize private root paths or full paths.
        if not isinstance(detail.reference, str):
            raise ValueError("Invalid local reference")
        parts, absolute, error = _reference_components(detail.reference)
        if error is not None or absolute:
            raise ValueError("Cannot publish an unvalidated source reference")
        assert parts is not None
        source_ref = parts[-1]
        if len(source_ref) > 512:
            raise ValueError("Source basename exceeds P0 wire bound")

    if len(detail.diagnostics) > 9999:
        raise ValueError("P0 warnings bound exceeded")
    warnings = []
    for diagnostic in detail.diagnostics:
        raw_code = diagnostic.code if isinstance(diagnostic.code, str) else ""
        code = raw_code.casefold()
        if code not in _REASONS:
            code = "unverified_texture_diagnostic"
        severity = diagnostic.severity if diagnostic.severity in ("info", "warning", "error") else "warning"
        warnings.append({
            "code": code, "severity": severity,
            "reason": _REASONS.get(code, "Texture diagnostic requires local inspection"),
            "evidence": None, "attribute": channel, "before": None, "after": None,
        })
    _, expected_role, _ = classify_channel(channel)
    if expected_role != "unknown" and detail.color_space_role != expected_role:
        warnings.append({
            "code": "color_space_mismatch", "severity": "warning",
            "reason": _REASONS["color_space_mismatch"],
            "evidence": None, "attribute": channel, "before": None, "after": None,
        })
    return {
        "id": stable_id,
        "source_ref": source_ref,
        "path_status": detail.state,
        "channel": channel,
        "color_space_role": detail.color_space_role,
        "sha256": digest,
        "provenance": {"method": provenance_method, "evidence": provenance_evidence},
        "warnings": warnings,
    }
