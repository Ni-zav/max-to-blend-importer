# SPDX-License-Identifier: GPL-2.0-or-later
"""I0 real pinned official/fork dual registration, not a fake operator."""
import importlib.util
from pathlib import Path
import sys
import tomllib

import bpy

root = Path(__file__).resolve().parents[2]
sources = {
    "official": root / "upstream-official/source",
    "fork": root / "source",
}
assert all((p / "__init__.py").is_file() for p in sources.values())
assert tomllib.loads((sources["official"] / "blender_manifest.toml").read_text())["id"] == "io_scene_max"
assert tomllib.loads((sources["fork"] / "blender_manifest.toml").read_text())["id"] == "maxblend_importer_fork"


def load_package(alias, directory):
    spec = importlib.util.spec_from_file_location(
        alias, directory / "__init__.py",
        submodule_search_locations=[str(directory)])
    assert spec and spec.loader
    addon = importlib.util.module_from_spec(spec)
    sys.modules[alias] = addon
    spec.loader.exec_module(addon)
    return addon


# Import fork first to initialize its private Wave 1 core alias once.
fork = load_package("maxblend_fork_pinned_coexist", sources["fork"])
official = load_package("maxblend_official_pinned_coexist", sources["official"])

for order in (("official", "fork"), ("fork", "official")):
    registry = {"official": official, "fork": fork}
    registered = []
    try:
        for name in order:
            registry[name].register()
            registered.append(name)
        assert bpy.ops.import_scene.max.get_rna_type().identifier == "IMPORT_SCENE_OT_max"
        assert bpy.ops.import_scene.maxblend.get_rna_type().identifier == "IMPORT_SCENE_OT_maxblend"
        assert official.ImportMax.bl_idname == "import_scene.max"
        assert fork.ImportMax.bl_idname == "import_scene.maxblend"
        assert official.IO_FH_max.bl_idname != fork.IO_FH_max.bl_idname
    finally:
        for name in reversed(registered):
            registry[name].unregister()
    for operator in (bpy.ops.import_scene.max, bpy.ops.import_scene.maxblend):
        try:
            operator.get_rna_type()
        except (KeyError, RuntimeError):
            pass
        else:
            raise AssertionError("Operator leaked registration after unload")
print("F6 Blender 4.2 dual-real-official smoke PASS: pinned upstream source official-first/fork-first")
