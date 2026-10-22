# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Project an F3 MaterialDetail into the frozen platform material wire shape.

The top-level scene manifest still belongs to F6/P6; these records MUST be
validated there, where object assignments and texture IDs can be cross-checked.
"""
from __future__ import annotations

import math
from . import MaterialDetail


def _unknown_entry(name: str, value: object) -> dict[str, object]:
    if isinstance(value, bool):
        kind = "boolean"
    elif isinstance(value, (int, float)) and math.isfinite(value):
        kind = "number"
    elif isinstance(value, str):
        kind = "string"
        # Public reports and manifests never emit private paths by default.
        if "/" in value or "\\" in value or value.startswith("~") or "://" in value:
            value = None
    else:
        kind = "unknown"
        value = None
    return {"name": name, "value_type": kind, "value": value}


def as_manifest_material(detail: MaterialDetail) -> dict[str, object]:
    """Schema-v1-shaped material, with no extra non-wire coat/layer fields."""
    warnings = [
        {
            "code": diagnostic.code,
            "severity": diagnostic.severity,
            "reason": diagnostic.message,
            "evidence": diagnostic.evidence,
            "attribute": None,
            "before": None,
            "after": None,
        }
        for diagnostic in detail.plan.diagnostics
    ]
    pbr = detail.manifest_pbr()
    for key, record in pbr.items():
        if record is not None and isinstance(record["value"], tuple):
            pbr[key] = {**record, "value": list(record["value"])}
    return {
        "id": detail.plan.material_id,
        "original_class": detail.plan.original_class,
        "renderer": detail.plan.renderer,
        "assignment_ids": list(detail.assignment_ids),
        "pbr": pbr,
        "unknown_parameters": [
            _unknown_entry(key, value) for key, value in detail.unknown_parameters[:1000]
        ],
        "coverage": detail.plan.coverage,
        "warnings": warnings,
    }


__all__ = ["as_manifest_material"]
