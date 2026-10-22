# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic affine invariants; never claims native .max import fidelity."""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "source"))
from maxblend_core.interfaces import SceneNode  # noqa: E402
from maxblend_core.transforms import (  # noqa: E402
    AxisConvention, BlenderDisplay, SourceUnits, TransformEngine, TransformError,
    IDENTITY, multiply, inverse, classify, change_basis, coordinate_basis,
    parent_local_preserving_world, point, bake_points, bounds,
)


def translate(x=0, y=0, z=0):
    return ((1, 0, 0, x), (0, 1, 0, y), (0, 0, 1, z), (0, 0, 0, 1))


def scale(x=1, y=1, z=1):
    return ((x, 0, 0, 0), (0, y, 0, 0), (0, 0, z, 0), (0, 0, 0, 1))


def rotate_z(radians):
    s, c = math.sin(radians), math.cos(radians)
    return ((c, -s, 0, 0), (s, c, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))


def assert_matrix(test, a, b, places=8):
    for i in range(4):
        for j in range(4):
            test.assertAlmostEqual(a[i][j], b[i][j], places=places, msg=(i, j))


class MatrixTests(unittest.TestCase):
    def test_mm_cm_m_physical_source_units(self):
        for name, ratio in (("mm", .001), ("cm", .01), ("m", 1.)):
            with self.subTest(unit=name):
                r = TransformEngine(axes=AxisConvention(), source_units=SourceUnits(name)).plan_scene([
                    SceneNode("a", "Box", "MESH", local_matrix=translate(100, 0, 0))])["a"]
                self.assertAlmostEqual(r.plan.world_matrix[0][3], 100*ratio)
                self.assertAlmostEqual(r.plan.meters_per_source_unit, ratio)
                self.assertEqual(r.evidence.source_raw_matrix[0][3], 100)
                self.assertEqual(r.manifest_matrices()["world_matrix"][3], 100*ratio)
                self.assertTrue(r.evidence.conversion_applied)

    def test_unknown_units_requires_explicit_operator_assumption(self):
        n = SceneNode("a", "N", "MESH", local_matrix=translate(123, 0, 0))
        fail = TransformEngine(axes=AxisConvention()).plan_scene([n])["a"]
        self.assertIsNone(fail.plan.world_matrix)
        self.assertIn("unknown_system_units", [d.code for d in fail.plan.diagnostics])
        selected = TransformEngine(axes=AxisConvention(), source_units=SourceUnits(operator_assumption=.001)).plan_scene([n])["a"]
        self.assertAlmostEqual(selected.plan.world_matrix[0][3], .123)
        self.assertIn("assumed_system_units", [d.code for d in selected.plan.diagnostics])

    def test_display_not_physical_units(self):
        n = SceneNode("a", "N", "MESH", local_matrix=translate(20, 0, 0))
        a = TransformEngine(axes=AxisConvention(), source_units=SourceUnits("cm"), display=BlenderDisplay("METRIC", .001, "MILLIMETERS"))
        b = TransformEngine(axes=AxisConvention(), source_units=SourceUnits("cm"), display=BlenderDisplay("IMPERIAL", 1., "INCHES"))
        self.assertEqual(a.plan_scene([n])["a"].plan.world_matrix, b.plan_scene([n])["a"].plan.world_matrix)
        with self.assertRaises(TransformError):
            SourceUnits("cm", .001).resolve()

    def test_axis_permutation_and_handedness(self):
        perm = AxisConvention(up="Y", forward="Z", handedness="RIGHT")
        self.assertEqual(point(perm.basis(), (0, 1, 0)), (0., 0., 1.))
        self.assertEqual(point(perm.basis(), (0, 0, 1)), (0., -1., 0.))
        self.assertEqual(AxisConvention().basis(), IDENTITY)
        lh = AxisConvention("Z", "-Y", "LEFT")
        self.assertTrue(classify(lh.basis()).mirrored)
        self.assertEqual(point(lh.basis(), (1, 0, 0)), (-1., 0., 0.))
        with self.assertRaises(TransformError):
            AxisConvention("Z", "-Z").basis()
        with self.assertRaises(TransformError):
            AxisConvention("UNKNOWN", "Y").basis()

    def test_nonuniform_units_not_scale(self):
        m = multiply(translate(200, 0, 0), scale(2, 3, -4))
        normalized = change_basis(m, axes=AxisConvention(), meters_per_unit=.01)
        self.assertAlmostEqual(normalized[0][3], 2.)
        self.assertEqual(normalized[0][0], 2.)
        self.assertEqual(normalized[1][1], 3.)
        self.assertEqual(normalized[2][2], -4.)
        p = classify(normalized)
        self.assertTrue(p.mirrored)
        self.assertTrue(p.nonuniform_scale)
        self.assertFalse(p.shear)

    def test_nested_transform_order_and_shear(self):
        a = SceneNode("a", "A", "EMPTY", local_matrix=multiply(translate(2, 0, 0), rotate_z(math.pi/4)))
        b = SceneNode("b", "B", "EMPTY", parent_id="a", local_matrix=multiply(translate(0, 3, 0), scale(2, 1, 1)))
        c = SceneNode("c", "C", "MESH", parent_id="b", local_matrix=rotate_z(math.pi/3))
        r = TransformEngine(axes=AxisConvention(), source_units=SourceUnits("m")).plan_scene([c, b, a])
        expected = multiply(multiply(a.local_matrix, b.local_matrix), c.local_matrix)
        assert_matrix(self, r["c"].plan.world_matrix, expected)
        self.assertTrue(r["c"].world_properties.shear)
        self.assertFalse(r["c"].local_properties.shear)

    def test_negative_nonuniform_parent(self):
        p = SceneNode("p", "Parent", "EMPTY", local_matrix=multiply(scale(-2, 3, 1), rotate_z(.3)))
        n = SceneNode("n", "Child", "MESH", "p", rotate_z(.7))
        r = TransformEngine(axes=AxisConvention(), source_units=SourceUnits("m")).plan_scene([n, p])
        self.assertTrue(r["n"].world_properties.mirrored)
        self.assertTrue(r["n"].world_properties.shear)
        assert_matrix(self, r["n"].plan.world_matrix, multiply(p.local_matrix, n.local_matrix))

    def test_pivot_geometry_offset_keeps_node_pose(self):
        raw = translate(8, 0, 0)
        offset = multiply(translate(-2, 0, 0), rotate_z(math.pi))
        n = SceneNode("x", "X", "MESH", local_matrix=raw,
                      source_metadata={"geometry_offset_matrix": offset})
        r = TransformEngine(axes=AxisConvention(), source_units=SourceUnits("cm")).plan_scene([n])["x"]
        self.assertAlmostEqual(r.plan.world_matrix[0][3], .08)
        self.assertAlmostEqual(point(r.geometry_world_matrix, (0, 0, 0))[0], .06)
        self.assertEqual(r.evidence.source_geometry_offset, offset)
        self.assertEqual(raw[0][3], 8)  # immutable evidence, untouched input
        # Raw geometry must first be normalized exactly once.
        normalized_vertex = point(coordinate_basis(axes=AxisConvention(), meters_per_unit=.01), (100, 0, 0))
        self.assertAlmostEqual(point(r.geometry_world_matrix, normalized_vertex)[0], -.94)

    def test_reparent_preserves_world(self):
        original = multiply(translate(2, 3, 4), rotate_z(.12))
        parent = multiply(translate(10, 20, 30), multiply(rotate_z(.47), scale(-2, 3, 1)))
        local = parent_local_preserving_world(original, parent)
        assert_matrix(self, multiply(parent, local), original)
        self.assertEqual(classify(scale(1, 1, 0)).singular, True)
        with self.assertRaises(TransformError):
            parent_local_preserving_world(original, scale(1, 1, 0))

    def test_instanced_parents_independent(self):
        # Different parents share one immutable vertex reference; neither mutates it.
        mesh = ((0, 0, 0), (1, 0, 0))
        a = SceneNode("a", "P1", "EMPTY", local_matrix=translate(3, 0, 0))
        b = SceneNode("b", "P2", "EMPTY", local_matrix=translate(-4, 0, 0))
        x = SceneNode("x", "I1", "MESH", "a", IDENTITY)
        y = SceneNode("y", "I2", "MESH", "b", IDENTITY)
        r = TransformEngine(axes=AxisConvention(), source_units=SourceUnits("m")).plan_scene([y, b, x, a])
        self.assertEqual(bake_points(mesh, r["x"].plan.world_matrix)[0], (3., 0., 0.))
        self.assertEqual(bake_points(mesh, r["y"].plan.world_matrix)[0], (-4., 0., 0.))
        self.assertEqual(mesh, ((0, 0, 0), (1, 0, 0),)))

    def test_bbox_invariants_and_empty(self):
        corners = [(x, y, z) for x in (-1, 1) for y in (-2, 2) for z in (-3, 3)]
        m = multiply(translate(4, 0, 0), scale(-2, 3, 1))
        self.assertEqual(bounds(corners, m), ((2., -6., -3.), (6., 6., 3.)))
        self.assertIsNone(bounds([], m))
        self.assertEqual(bounds(corners, m), bounds(bake_points(corners, m)))

    def test_cycle_missing_parent_duplicate_and_deep_tree(self):
        engine = TransformEngine(axes=AxisConvention(), source_units=SourceUnits("m"), max_depth=3)
        with self.assertRaisesRegex(TransformError, "cycle"):
            engine.plan_scene([SceneNode("a", "A", "EMPTY", "b", IDENTITY),
                               SceneNode("b", "B", "EMPTY", "a", IDENTITY)])
        with self.assertRaisesRegex(TransformError, "Missing parent"):
            engine.plan_scene([SceneNode("a", "A", "EMPTY", "missing", IDENTITY)])
        with self.assertRaisesRegex(TransformError, "duplicate"):
            engine.plan_scene([SceneNode("a", "A", "EMPTY"), SceneNode("a", "B", "EMPTY")])
        deep = [SceneNode(str(i), "N", "EMPTY", str(i-1) if i else None, IDENTITY) for i in range(5)]
        with self.assertRaisesRegex(TransformError, "depth"):
            engine.plan_scene(deep)
        self.assertEqual(len(TransformEngine(axes=AxisConvention(), source_units=SourceUnits("m"), max_depth=6000).plan_scene(
            [SceneNode(str(i), "N", "EMPTY", str(i-1) if i else None, IDENTITY) for i in range(1500)])), 1500)

    def test_reject_unsupported_controller_and_non_affine(self):
        dynamic = SceneNode("d", "D", "EMPTY", local_matrix=IDENTITY,
                            source_metadata={"controller_format": "list_unknown"})
        r = TransformEngine(axes=AxisConvention(), source_units=SourceUnits("m")).plan_scene([dynamic])["d"]
        self.assertIsNone(r.plan.world_matrix)
        self.assertIn("unsupported_controller", [d.code for d in r.plan.diagnostics])
        skew = ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (1, 0, 0, 1))
        invalid = SceneNode("s", "S", "EMPTY", local_matrix=skew)
        r = TransformEngine(axes=AxisConvention(), source_units=SourceUnits("m")).plan_scene([invalid])["s"]
        self.assertIsNone(r.plan.world_matrix)
        self.assertIn("invalid_matrix", [d.code for d in r.plan.diagnostics])
        with self.assertRaises(TransformError):
            inverse(skew)

    def test_double_conversion_prevention(self):
        node = SceneNode("one", "One", "MESH", local_matrix=translate(2, 0, 0),
                         source_metadata={"matrix_space": "normalized"})
        r = TransformEngine(axes=AxisConvention(), source_units=SourceUnits("mm")).plan_scene([node])["one"]
        self.assertEqual(r.plan.world_matrix[0][3], 2)
        self.assertFalse(r.evidence.conversion_applied)

    def test_axis_provenance_required_for_source_space(self):
        node = SceneNode("n", "N", "EMPTY", local_matrix=translate(10, 20, 30))
        # Physically known units do not make unknown MAX axes safe to guess.
        missing = TransformEngine(source_units=SourceUnits("cm")).plan_scene([node])["n"]
        self.assertIsNone(missing.plan.world_matrix)
        self.assertIn("unknown_source_axes", [d.code for d in missing.plan.diagnostics])
        self.assertIsNone(missing.evidence.axis_basis)
        # A malformed axis mapping is an unsupported result, not a crash.
        bad = TransformEngine(axes=AxisConvention("Z", "Z"),
                              source_units=SourceUnits("cm")).plan_scene([node])["n"]
        self.assertIsNone(bad.plan.world_matrix)
        self.assertIn("unknown_source_axes", [d.code for d in bad.plan.diagnostics])

    def test_normalized_matrix_no_source_axis_or_unit_reconversion(self):
        node = SceneNode("n", "N", "EMPTY", local_matrix=translate(2, 0, 0),
                         source_metadata={"matrix_space": "normalized"})
        out = TransformEngine().plan_scene([node])["n"]
        self.assertEqual(out.plan.world_matrix[0][3], 2.)
        self.assertFalse(out.evidence.conversion_applied)
        self.assertIsNone(out.evidence.axis_basis)
        self.assertEqual(out.manifest_matrices()["world_matrix"][3], 2.)

    def test_manifest_flatten_row_major_finite_v1_fields_only(self):
        import math
        node = SceneNode("n", "N", "MESH", local_matrix=multiply(
            translate(3, 4, 5), rotate_z(.2)))
        rec = TransformEngine(axes=AxisConvention(), source_units=SourceUnits("m")).plan_scene([node])["n"]
        matrices = rec.manifest_matrices()
        self.assertEqual(set(matrices), {"local_matrix", "world_matrix", "source_raw_matrix"})
        for item in matrices.values():
            self.assertEqual(len(item), 16)
            self.assertTrue(all(math.isfinite(value) for value in item))
        self.assertEqual(matrices["world_matrix"][3], 3.)
        self.assertEqual(matrices["world_matrix"][7], 4.)
        self.assertEqual(matrices["world_matrix"][11], 5.)
        invalid = SceneNode("x", "X", "MESH", local_matrix=(
            (1., 0., 0., float("nan")), (0., 1., 0., 0.), (0., 0., 1., 0.), (0., 0., 0., 1.)))
        failed = TransformEngine(axes=AxisConvention(), source_units=SourceUnits("m")).plan_scene([invalid])["x"]
        self.assertIsNone(failed.plan.world_matrix)
        self.assertEqual(failed.manifest_matrices(),
                         {"local_matrix": None, "world_matrix": None, "source_raw_matrix": None})

    def test_axis_mirror_nested_conversion_once(self):
        axes = AxisConvention(up="Y", forward="Z", handedness="LEFT")
        p = SceneNode("a", "A", "EMPTY", local_matrix=translate(100, 0, 0))
        c = SceneNode("b", "B", "MESH", parent_id="a", local_matrix=translate(0, 25, 0))
        out = TransformEngine(axes=axes, source_units=SourceUnits("cm")).plan_scene([c, p])
        # Source X -> normalized negative X for this explicit LH basis.
        self.assertAlmostEqual(out["b"].plan.world_matrix[0][3], -1.)
        self.assertAlmostEqual(out["b"].plan.world_matrix[2][3], .25)
        self.assertFalse(out["b"].world_properties.mirrored)
        # Axis reflection is a coordinate-system conversion, not a mesh mirror.
        self.assertEqual(out["b"].evidence.axis_basis, axes.basis())
        vertex = point(coordinate_basis(axes=axes, meters_per_unit=.01), (100, 0, 0))
        self.assertAlmostEqual(vertex[0], -1.)

    def test_dependency_free(self):
        self.assertNotIn("bpy", sys.modules)


if __name__ == "__main__":
    unittest.main()
