# SPDX-License-Identifier: GPL-2.0-or-later
"""Blender 4.2: a Git-less installed extension cannot parse native inputs.

This is a production-deny test, NOT evidence of a functioning ZIP importer.
CI passes only the separately built+installed public synthetic extension.
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
from unittest import mock

import bpy

assert "--" in sys.argv
args = sys.argv[sys.argv.index("--") + 1:]
assert len(args) == 1
installed = Path(args[0]).resolve()
assert installed.name == "maxblend_importer_fork"
assert (installed / "blender_manifest.toml").is_file()
assert (installed / "__init__.py").is_file()
assert not (installed.parent / ".git").exists()
assert bpy.app.version >= (4, 2, 0)

name = "maxblend_installed_unauthenticated_zip"
spec = importlib.util.spec_from_file_location(
    name, installed / "__init__.py", submodule_search_locations=[str(installed)])
assert spec and spec.loader
addon = importlib.util.module_from_spec(spec)
sys.modules[name] = addon
spec.loader.exec_module(addon)
assert addon.__version__ == "1.9.3"
from maxblend_installed_unauthenticated_zip import maxblend_isolation

for flag, expected in (
    (False, "EXPERIMENTAL_IMPORT_ACK_REQUIRED"),
    (True, "EXPERIMENTAL_GIT_CHECKOUT_REQUIRED"),
):
    try:
        maxblend_isolation.require_experimental_authorization(flag)
    except maxblend_isolation.ImportRejected as exc:
        assert expected in str(exc), str(exc)
    else:
        raise AssertionError("An installed ZIP was treated as approved source")

addon.register()
try:
    baseline = {obj.as_pointer() for obj in bpy.data.objects}
    with tempfile.TemporaryDirectory(prefix="maxblend-zip-gate-") as directory:
        file_path = Path(directory) / "invalid.max"
        file_path.write_bytes(b"NOT_A_VALID_MAX" + bytes(1024))
        with mock.patch.object(maxblend_isolation, "run_worker") as worker:
            for ack, expected in (
                (False, "EXPERIMENTAL_IMPORT_ACK_REQUIRED"),
                (True, "EXPERIMENTAL_GIT_CHECKOUT_REQUIRED"),
            ):
                try:
                    result = bpy.ops.import_scene.maxblend(
                        filepath=str(file_path), experimental_ack=ack,
                        use_image_search=False, approved_texture_root="")
                    assert result == {"CANCELLED"}, (ack, result)
                except RuntimeError as exc:
                    assert expected in str(exc), str(exc)
                assert addon.get_last_import_session() is None
                assert "maxblend_scene_v1" not in bpy.context.scene
                assert {obj.as_pointer() for obj in bpy.data.objects} == baseline
            worker.assert_not_called()
finally:
    addon.unregister()
print("ZIP_INSTALL_DENY_PASS: installed addon registered; no provenance, no parser, no scene")
