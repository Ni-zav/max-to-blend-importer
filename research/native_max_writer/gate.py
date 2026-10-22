# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Fail-closed research evidence gate. This module does NOT encode .max files.

A PASS represents an operator-supplied test observation, never proof that the
observation is authentic. Manual source/fixture review is mandatory even if all
checks are supplied as PASS. No files, client metadata, or scripts are loaded.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import re

GATES = (
    "reference_provenance",
    "cfb_structure",
    "native_stream_layout",
    "class_registry",
    "mesh_semantics",
    "transform_semantics",
    "material_semantics",
    "independent_open",
    "authorized_native_open",
    "authorized_native_resave",
)
STATES = frozenset(("pass", "fail", "not_run"))
CONSUMERS = frozenset(("independent_reader", "authorized_native_max"))

# Test-case specification ONLY. This is not a native wire schema or writer.
MINIMAL_TARGET = {
    "vertices_local_m": ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    "triangles": ((0, 1, 2),),
    "local_to_world_row_major": (
        (1.0, 0.0, 0.0, 2.0),
        (0.0, 1.0, 0.0, 3.0),
        (0.0, 0.0, 1.0, 4.0),
        (0.0, 0.0, 0.0, 1.0),
    ),
    "expected_world_vertices_m": ((2.0, 3.0, 4.0), (3.0, 3.0, 4.0), (2.0, 4.0, 4.0)),
    "single_material_rgba_linear": (0.8, 0.2, 0.1, 1.0),
}


def assess(observations: Mapping[str, str], *, consumer_kind: str | None = None,
           tested_version: str | None = None) -> dict[str, object]:
    """Evaluate synthetic/externally attested evidence without claiming support.

    Evidence hashes cover normalized claim labels, NOT a native .max artifact.
    Only fixed keys/values are accepted to avoid leaking private paths or names.
    A research-review verdict is NOT authorization to enable a .max exporter.
    """
    if not isinstance(observations, Mapping):
        raise ValueError("observations must be a mapping")
    if set(observations) - set(GATES):
        raise ValueError("unknown evidence gate")
    if any(type(value) is not str or value not in STATES for value in observations.values()):
        raise ValueError("invalid evidence state")
    if consumer_kind is not None and consumer_kind not in CONSUMERS:
        raise ValueError("consumer must be independent of this fork")
    if tested_version is not None and (
        type(tested_version) is not str or
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}", tested_version)
    ):
        raise ValueError("invalid/version-identifying text")
    gates = {name: observations.get(name, "not_run") for name in GATES}
    independent = gates["independent_open"] == "pass"
    native_open = gates["authorized_native_open"] == "pass"
    native_resave = gates["authorized_native_resave"] == "pass"
    if independent and (consumer_kind is None or tested_version is None):
        raise ValueError("independent compatibility claim requires consumer and release")
    if native_open and (consumer_kind != "authorized_native_max" or not tested_version):
        raise ValueError("native open requires identified authorized native consumer")
    if native_resave and not native_open:
        raise ValueError("native resave cannot precede native open")
    if (native_open or native_resave) and not independent:
        raise ValueError("native compatibility needs independently verified open")
    if any(gates[name] == "pass" for name in
           ("mesh_semantics", "transform_semantics", "material_semantics")) and (
        gates["native_stream_layout"] != "pass" or gates["class_registry"] != "pass"
    ):
        raise ValueError("semantic pass requires verified stream and class mappings")
    if consumer_kind == "independent_reader" and (native_open or native_resave):
        raise ValueError("reader is not authorized native Max")

    all_pass = all(state == "pass" for state in gates.values())
    structural_pass = all(gates[name] == "pass" for name in GATES[:8])
    if all_pass and consumer_kind == "authorized_native_max":
        decision = "manual_release_review_required"
    elif structural_pass and not any(state == "fail" for state in gates.values()):
        decision = "authorized_native_validation_required"
    else:
        decision = "no_go"

    digest_input = {
        "consumer_kind": consumer_kind,
        "gates": gates,
        "tested_version": tested_version,
    }
    canonical = json.dumps(digest_input, ensure_ascii=True, sort_keys=True,
                           separators=(",", ":")).encode("ascii")
    return {
        "decision": decision,
        "gates": gates,
        "evidence_sha256": hashlib.sha256(canonical).hexdigest(),
        "checksum_scope": "normalized_claims_only_not_max_file",
        "native_export_enabled": False,
    }
