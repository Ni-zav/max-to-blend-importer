# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Headless smoke test for Blender 4.2+; run with --factory-startup.

No private files are used; full .max import is intentionally skipped without
a legally redistributable fixture. This script does NOT validate fidelity.
"""
import importlib.util
import io
import json
from pathlib import Path
import sys
import time
import bpy

assert bpy.app.version >= (4, 2, 0), "Blender 4.2+ required"
root = Path(__file__).resolve().parents[2]
package_name = "maxblend_wave0_smoke"
spec = importlib.util.spec_from_file_location(
    package_name, root / "source/__init__.py",
    submodule_search_locations=[str(root / "source")],
)
assert spec is not None and spec.loader is not None
addon = importlib.util.module_from_spec(spec)
sys.modules[package_name] = addon
spec.loader.exec_module(addon)

start = time.perf_counter()
registered = False
try:
    addon.register()
    registered = True
    self_rna = bpy.ops.import_scene.max.get_rna_type()
    assert self_rna.identifier == "IMPORT_SCENE_OT_max", self_rna.identifier
    from maxblend_wave0_smoke import import_max
    assert import_max.is_maxfile(io.BytesIO(import_max.MAGIC + bytes(1528)))
    assert not import_max.is_maxfile(io.BytesIO(b"INVALID!" + bytes(1528)))
finally:
    if registered:
        addon.unregister()
print(json.dumps({
    "blender": bpy.app.version_string, "operator": "import_scene.max",
    "register_unregister": "pass",
    "synthetic_header_probe": "pass",
    "actual_max_scene_import": "skipped_no_redistributable_fixture",
    "elapsed_seconds": round(time.perf_counter() - start, 3),
}, sort_keys=True))
