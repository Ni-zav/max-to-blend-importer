# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "source"))
from maxblend_core.textures import SafeTextureResolver, extract_bitmap_sources, resolve_graph


class GraphTests(unittest.TestCase):
    def test_regular_vray_corona_and_guid(self):
        graph = {"class": "Mix", "maps": [
            {"class": "BitmapTexture", "filename": "a.png"},
            {"class": "VRayBitmap", "file_name": "b.exr"},
            {"class": "CoronaBitmap", "filepath": "c.jpg"},
            {"class": "0x2c1017d6769144b", "path": "d.tif"},
        ]}
        result = extract_bitmap_sources(graph, slot="base_color")
        self.assertEqual([s.raw_reference for s in result.sources], ["a.png", "b.exr", "c.jpg", "d.tif"])
        self.assertEqual(len({s.source_id for s in result.sources}), 4)
        self.assertTrue(all(s.approximated for s in result.sources))
        self.assertIn("WRAPPER_APPROXIMATION", [d.code for d in result.diagnostics])

    def test_color_correct_mix_falloff_are_only_approximated(self):
        graph = {"class": "ColorCorrection", "input": {"class": "Falloff", "map1":
                 {"class": "Mix", "map1": {"class": "Bitmap", "filename": "test.png"}}}}
        result = extract_bitmap_sources(graph, slot="normal")
        self.assertEqual(len(result.sources), 1)
        self.assertTrue(result.sources[0].approximated)
        self.assertEqual(result.sources[0].slot, "normal")
        self.assertEqual(len([d for d in result.diagnostics if d.code == "WRAPPER_APPROXIMATION"]), 3)

    def test_unknown_class_does_not_claim_bitmap(self):
        graph = {"class": "UnknownProcedural", "filename": "not-an-image.png", "map":
                 {"class": "Bitmap", "filename": "yes.png"}}
        result = extract_bitmap_sources(graph)
        self.assertEqual([s.raw_reference for s in result.sources], ["yes.png"])
        self.assertIn("UNKNOWN_TEXMAP", [d.code for d in result.diagnostics])

    def test_cycle_and_budget(self):
        loop = {"class": "ColorCorrection"}
        loop["map"] = loop
        result = extract_bitmap_sources(loop)
        self.assertIn("GRAPH_CYCLE", [d.code for d in result.diagnostics])
        limited = extract_bitmap_sources({"class": "Mix", "maps": [{"class": "Bitmap", "filename": "a.png"}]}, max_nodes=1)
        self.assertIn("GRAPH_LIMIT", [d.code for d in limited.diagnostics])

    def test_duplicate_paths_flagged_and_unknown_metadata(self):
        graph = {"class": "CoronaBitmap", "path": "one.png", "filename": "two.png"}
        result = extract_bitmap_sources(graph)
        self.assertEqual(len(result.sources), 1)
        self.assertIn("MULTIPLE_BITMAP_PATHS", [d.code for d in result.diagnostics])
        result = extract_bitmap_sources({"class": "VRayBitmap", "filename": 13})
        self.assertEqual(len(result.sources), 0)
        self.assertIn("BITMAP_WITHOUT_PATH", [d.code for d in result.diagnostics])

    def test_end_to_end_without_blender_or_max(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "color.png"
            p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"synthetic-only")
            graph, resolutions = resolve_graph({"class": "VRayBitmap", "filename": "color.png"}, SafeTextureResolver((tmp,)), slot="emission")
            self.assertEqual(len(graph.sources), 1)
            self.assertEqual(resolutions[0].state, "found")
            self.assertEqual(resolutions[0].color_space_role, "color")


if __name__ == "__main__":
    unittest.main()
