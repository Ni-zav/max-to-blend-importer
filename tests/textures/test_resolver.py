# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "source"))
from maxblend_core.interfaces import TextureReference
from maxblend_core.textures import SafeTextureResolver, classify_channel

PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-not-an-image"
JPG = b"\xff\xd8\xff" + b"synthetic-not-an-image"


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.a = self.root / "assets"
        self.a.mkdir()
        self.resolver = SafeTextureResolver((self.a,))

    def put(self, rel, data=PNG, root=None):
        dest = (root or self.a) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest

    def test_resolve_nested_windows_separators_and_contract(self):
        file = self.put("textures/wood.png")
        result = self.resolver.resolve_detailed(r"textures\wood.png", slot="base_color")
        self.assertEqual(result.state, "found")
        self.assertEqual(result.color_space_role, "color")
        self.assertEqual(result.reference, "textures/wood.png")
        self.assertEqual(result.resolved_path, str(file))
        self.assertEqual(result.manifest_record()["sha256"], result.sha256)
        self.assertNotIn(str(self.root), str(result.manifest_record()))
        contract = self.resolver.resolve(TextureReference("textures/wood.png", "normal", "data"))
        self.assertEqual(contract.state, "found")
        self.assertEqual(contract.resolved_path, str(file))

    def test_missing_folder_and_missing_texture(self):
        self.assertEqual(self.resolver.resolve_detailed("not_here/test.png").state, "missing")
        self.assertEqual(SafeTextureResolver((self.root / "missing",)).resolve_detailed("one.png").state, "blocked")
        self.assertEqual(SafeTextureResolver().resolve_detailed("one.png").state, "blocked")

    def test_blocks_traversal_drive_unc_url_and_zip_entries(self):
        cases = ("../secret.png", "textures/../../secret.png", r"C:\private\secret.png",
                 r"\\server\share\secret.png", "/etc/secret.png", "http://host/img.png",
                 "archive.zip!/secret.png", "a//b.png", "dir/./a.png", "./a.png", "~/.ssh/a.png",
                 "file://private/a.png", "a*.png", "file_${HOME}.png")
        for name in cases:
            with self.subTest(kind="blocked"):
                self.assertEqual(self.resolver.resolve_detailed(name).state, "blocked")
        # Even if a real outside image exists, never open it.
        other = self.root / "secret.png"
        other.write_bytes(PNG)
        self.assertEqual(self.resolver.resolve_detailed("../secret.png").state, "blocked")

    def test_opt_in_basename_only_from_foreign_drive(self):
        self.put("wood.png")
        allowed = SafeTextureResolver((self.a,), allow_absolute_basename=True)
        self.assertEqual(allowed.resolve_detailed(r"Q:\private\wood.png").state, "found")
        self.assertEqual(allowed.resolve_detailed(r"Q:\private\wood.png").reference, "wood.png")
        self.assertEqual(self.resolver.resolve_detailed(r"Q:\private\wood.png").state, "blocked")

    def test_nested_explicit_roots_only(self):
        deep = self.put("nested/wood.png")
        self.assertEqual(self.resolver.resolve_detailed("wood.png").state, "missing")
        explicit = SafeTextureResolver((self.a, deep.parent))
        self.assertEqual(explicit.resolve_detailed("wood.png").state, "found")

    def test_hash_identity_and_ambiguous_same_name(self):
        b = self.root / "more"
        b.mkdir()
        self.put("same.png")
        self.put("same.png", PNG, b)
        unique = SafeTextureResolver((self.a, b))
        self.assertEqual(unique.resolve_detailed("same.png").state, "found")
        self.put("same.png", PNG + b"different", b)
        result = unique.resolve_detailed("same.png")
        self.assertEqual(result.state, "ambiguous")
        self.assertIsNone(result.resolved_path)
        self.assertIn("HASH_COLLISION", [d.code for d in result.diagnostics])

    def test_invalid_content_nonimage_and_bounded_file(self):
        self.put("fake.png", b"not an image")
        self.assertEqual(self.resolver.resolve_detailed("fake.png").state, "blocked")
        self.put("secret.exe", PNG)
        self.assertEqual(self.resolver.resolve_detailed("secret.exe").state, "blocked")
        self.put("big.png", PNG + b"x" * 100)
        limited = SafeTextureResolver((self.a,), max_file_bytes=32)
        self.assertEqual(limited.resolve_detailed("big.png").state, "blocked")
        self.put("photo.jpg", JPG)
        self.assertEqual(self.resolver.resolve_detailed("photo.jpg").state, "found")

    def test_invalid_unicode(self):
        self.assertEqual(self.resolver.resolve_detailed("bad_\udcff.png").state, "blocked")
        self.assertEqual(self.resolver.resolve_detailed("bad\x00.png").state, "blocked")
        self.assertEqual(self.resolver.resolve_detailed("bad\n.png").state, "blocked")

    @unittest.skipUnless(hasattr(os, "symlink"), "OS has no symlink support")
    def test_symlink_escape_and_loop(self):
        secret = self.root / "secret.png"
        secret.write_bytes(PNG)
        try:
            os.symlink(str(secret), str(self.a / "shortcut.png"))
            os.symlink(str(self.root), str(self.a / "escape"), target_is_directory=True)
            os.symlink("loop", str(self.a / "loop"), target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Symlinks unavailable: {type(error).__name__}")
        for test in ("shortcut.png", "escape/secret.png", "loop/secret.png"):
            self.assertEqual(self.resolver.resolve_detailed(test).state, "blocked")

    def test_udim_valid_missing_and_limits(self):
        self.put("char_1001.exr", b"\x76\x2f\x31\x01" + b"one")
        self.put("char_1002.exr", b"\x76\x2f\x31\x01" + b"two")
        result = self.resolver.resolve_detailed("char_<UDIM>.exr", slot="displacement")
        self.assertEqual(result.state, "found")
        self.assertEqual(result.color_space_role, "data")
        self.assertEqual([i for i, _ in result.tile_hashes], [1001, 1002])
        self.assertIsNone(result.resolved_path)
        self.assertEqual(self.resolver.resolve_detailed("char_%(UDIM)d.exr").state, "found")
        limited = SafeTextureResolver((self.a,), max_udim_tiles=1)
        self.assertEqual(limited.resolve_detailed("char_<UDIM>.exr").state, "blocked")
        self.assertEqual(self.resolver.resolve_detailed("no_<UDIM>.png").state, "missing")
        self.assertEqual(self.resolver.resolve_detailed("char_<UDIM>_<UDIM>.exr").state, "blocked")

    def test_udim_incomplete_start(self):
        self.put("tile_1002.png")
        result = self.resolver.resolve_detailed("tile_$UDIM.png")
        self.assertEqual(result.state, "found")
        self.assertIn("UDIM_1001_MISSING", [d.code for d in result.diagnostics])

    def test_many_directory_entries_never_recursively_scanned(self):
        self.put("good.png")
        for i in range(1000):
            self.put(f"noise_{i}.png")
        with mock.patch("os.walk", side_effect=AssertionError("recursive scan called")):
            self.assertEqual(self.resolver.resolve_detailed("good.png").state, "found")
        self.assertEqual(self.resolver.resolve_detailed("noise.png").state, "missing")

    def test_semantic_roles(self):
        for slot in ("base_color", "diffuse", "emission", "specular_color"):
            self.assertEqual(classify_channel(slot)[1], "color")
        for slot in ("normal", "roughness", "metallic", "opacity", "displacement", "bump"):
            self.assertEqual(classify_channel(slot)[1], "data")
        self.assertEqual(classify_channel("unknown_layer")[1], "unknown")
        self.assertIn("GLOSS_INVERSION", [d.code for d in classify_channel("glossiness")[2]])
        self.assertEqual(classify_channel("emission", {"emission": "data"})[1], "data")
        with self.assertRaises(ValueError):
            classify_channel("normal", {"normal": "sRGB"})

    def test_no_path_text_in_diagnostics_or_repr(self):
        secret_path = "private-client-location"
        self.put(secret_path + ".png")
        result = self.resolver.resolve_detailed(secret_path + ".png")
        # filenames are allowed in a LOCAL manifest, never raw absolute roots in diagnostic strings.
        self.assertNotIn(str(self.root), repr(result))
        self.assertNotIn(str(self.root), str(result.diagnostics))
        result = self.resolver.resolve_detailed(r"C:\very_secret\client_2026\final.png")
        self.assertNotIn("very_secret", repr(result))
        self.assertNotIn("very_secret", str(result.manifest_record()))


if __name__ == "__main__":
    unittest.main()
