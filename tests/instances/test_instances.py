# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic topology-only fixtures. Not native MAX/Blender fidelity tests."""
import sys
from pathlib import Path
import tracemalloc
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "source"))
from maxblend_core.interfaces import InstancePlan, SceneNode  # noqa: E402
from maxblend_core.instances import InstanceGraphPlanner, InstanceInput, Limits  # noqa: E402

IDENTITY = ((1.0, 0., 0., 0.), (0., 1., 0., 0.),
            (0., 0., 1., 0.), (0., 0., 0., 1.))


def mat(x=0., y=0., z=0., scale=1.):
    return ((scale, 0., 0., x), (0., scale, 0., y),
            (0., 0., scale, z), (0., 0., 0., 1.))


def item(key, role="mesh", *, parent=None, source=None, geo=None,
         local=IDENTITY, world=IDENTITY, materials=(), overrides=(),
         name="Repeated", external=None, state="unknown", vertices=None):
    return InstanceInput(node=SceneNode(key, name, role.upper(), parent, local),
                         role=role, geometry_id=geo, source_node_id=source,
                         world_matrix=world, material_ids=materials,
                         material_overrides=overrides,
                         external_reference=external, external_state=state,
                         vertex_count=vertices)


class InstanceTests(unittest.TestCase):
    def setUp(self):
        self.plan = InstanceGraphPlanner().plan_scene

    def test_shared_geometry_one_of_many_without_array_clones(self):
        nodes = [item("Obj0", geo="Geo1", vertices=200000)]
        nodes.extend(item(f"Obj{i}", "instance", source="Obj0", world=mat(float(i)))
                     for i in range(1, 1000))
        result = self.plan(nodes)
        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.geometries), 1)
        self.assertEqual(result.count("geometry_references"), 1000)
        self.assertEqual(result.count("shared_geometry_resources"), 1)
        self.assertEqual(result.objects[500].world_matrix[0][3], 500.)
        self.assertNotEqual(result.objects[500].world_matrix, result.objects[600].world_matrix)

    def test_group_with_scale_keeps_local_and_world_unmodified(self):
        parent = item("Group0", "group", local=mat(scale=2), world=mat(scale=2))
        child = item("Obj0", parent="Group0", geo="Geo0", local=mat(2), world=mat(4, scale=2))
        r = self.plan([child, parent])
        self.assertEqual(r.status, "success")
        self.assertEqual(r.objects[0].local_matrix, mat(2))
        self.assertEqual(r.objects[0].world_matrix, mat(4, scale=2))
        self.assertEqual(r.objects[0].parent_id, "Group0")

    def test_per_instance_materials_independent_and_same_mesh(self):
        r = self.plan([item("A", geo="G", materials=("Red",)),
                       item("B", "instance", source="A", overrides=((0, "Blue"),))])
        self.assertEqual(r.status, "success")
        self.assertEqual(r.objects[0].geometry_id, r.objects[1].geometry_id)
        self.assertEqual(r.objects[0].material_overrides, ())
        self.assertEqual(r.objects[1].material_overrides, ((0, "Blue"),))

    def test_nested_instances_under_group_reuse_single_geometry(self):
        r = self.plan([item("Root", "group"),
                       item("Group1", "group", parent="Root", local=mat(scale=3)),
                       item("Chair", "mesh", parent="Group1", geo="ChairMesh"),
                       item("ChairCopy", "instance", source="Chair", parent="Group1"),
                       item("ChairCopy2", "instance", source="ChairCopy", parent="Root")])
        self.assertEqual(r.status, "success")
        self.assertEqual(r.count("geometry_resources"), 1)
        self.assertEqual(r.count("geometry_references"), 3)
        self.assertEqual(r.objects[4].parent_id, "Root")
        self.assertEqual(r.objects[4].source_node_id, "ChairCopy")

    def test_child_world_unknown_is_not_invented(self):
        r = self.plan([item("Group", "group"),
                       item("Child", parent="Group", geo="G", world=None)])
        self.assertEqual(r.status, "failed")
        self.assertIsNone(r.objects[1].world_matrix)
        self.assertEqual(r.count("WORLD_UNRESOLVED"), 1)

    def test_missing_proxy_path_and_absolute_path_suppressed(self):
        r = self.plan([item("P", "proxy", external="C:\\secret\\asset.vrmesh", state="missing")])
        self.assertEqual(r.status, "unsupported")
        self.assertEqual(r.objects[0].external_state, "blocked")
        self.assertIsNone(r.objects[0].external_reference)
        self.assertGreaterEqual(r.count("EXTERNAL_UNRESOLVED"), 1)
        self.assertNotIn("secret", repr(r))

    def test_unresolved_relative_proxy_never_becomes_blank_mesh(self):
        r = self.plan([item("P", "proxy", external="assets/tree.vrmesh", state="missing")])
        self.assertEqual(r.objects[0].external_reference, "assets/tree.vrmesh")
        self.assertEqual(r.objects[0].external_state, "missing")
        self.assertIsNone(r.objects[0].geometry_id)
        self.assertEqual(r.count("geometry_resources"), 0)

    def test_direct_parent_cycle_and_self_ref(self):
        for nodes in ([item("A", "group", parent="B"), item("B", "group", parent="A")],
                      [item("A", "instance", source="A")],
                      [item("A", "instance", source="B"), item("B", "instance", source="A")]):
            with self.subTest(nodes=nodes):
                r = self.plan(nodes)
                self.assertEqual(r.status, "failed")
                self.assertGreater(r.count("REFERENCE_CYCLE"), 0)

    def test_deep_hierarchy_bounded_without_recursion(self):
        r = InstanceGraphPlanner(Limits(max_depth=16)).plan_scene(
            item(f"N{i}", "group", parent=f"N{i-1}" if i else None) for i in range(1000))
        self.assertEqual(r.status, "failed")
        self.assertGreater(r.count("GRAPH_DEPTH"), 0)

    def test_duplicate_ids_fail_but_duplicate_names_survive(self):
        self.assertEqual(self.plan([item("A"), item("A")]).status, "failed")
        r = self.plan([item("A", geo="GA"), item("B", geo="GB")])
        self.assertEqual(r.status, "success")
        self.assertEqual(r.objects[0].name, r.objects[1].name)

    def test_unsupported_empty_and_unknown_no_fabricated_geometry(self):
        r = self.plan([item("E", "empty"), item("U", "other")])
        self.assertEqual(r.status, "partial")
        self.assertEqual(r.count("geometry_resources"), 0)
        self.assertGreater(r.count("UNSUPPORTED_COMPONENT"), 0)

    def test_missing_reference_and_geometry_unknown_not_zero(self):
        r = self.plan([item("X", "instance", source="Gone")])
        self.assertEqual(r.status, "failed")
        self.assertIsNone(r.objects[0].geometry_id)
        self.assertGreater(r.count("REFERENCE_MISSING"), 0)

    def test_invalid_matrix_never_coerced_to_origin(self):
        bad = ((float("nan"), 0., 0., 0.),) * 4
        r = self.plan([item("B", geo="G", world=bad)])
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.objects[0].world_matrix, bad)

    def test_conflicting_geometry_evidence_rejected(self):
        r = self.plan([item("A", geo="Shared", vertices=3),
                       item("B", geo="Shared", vertices=8)])
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.count("GEOMETRY_ID_COLLISION"), 1)

    def test_cap_consumes_only_one_extra_element(self):
        counter = []
        def infinite():
            i = 0
            while True:
                counter.append(i)
                yield item(f"N{i}", "empty")
                i += 1
        r = InstanceGraphPlanner(Limits(max_nodes=10)).plan_scene(infinite())
        self.assertEqual(len(counter), 11)
        self.assertEqual(r.status, "failed")
        self.assertTrue(r.truncated)

    def test_linear_memory_for_many_instances(self):
        nodes = (item("N0", geo="G0", vertices=1000000) if i == 0 else
                 item(f"N{i}", "instance", source="N0") for i in range(12000))
        tracemalloc.start()
        try:
            r = self.plan(nodes)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(r.status, "success")
        self.assertEqual(len(r.geometries), 1)
        self.assertLess(peak, 40_000_000)  # deterministic synthetic budget, not MAX memory


    def test_source_ids_survive_duplicate_names_and_explicit_provenance(self):
        from dataclasses import replace
        first = replace(item("Node01", geo="Geometry01", vertices=8),
                        native_id="Native01")
        second = replace(item("Node02", "instance", source="Node01"),
                         native_id="Native02")
        r = self.plan([first, second])
        self.assertEqual(r.status, "success")
        self.assertEqual(tuple(x.id for x in r.objects), ("Node01", "Node02"))
        self.assertEqual(tuple(x.native_id for x in r.objects), ("Native01", "Native02"))
        self.assertEqual(tuple(x.name for x in r.objects), ("Repeated", "Repeated"))
        self.assertEqual(len(r.geometries), 1)
        self.assertEqual(r.geometries[0].owner_node_id, "Node01")
        self.assertEqual(r.geometries[0].geometry_id, "Geometry01")

    def test_duplicate_native_source_id_is_fatal(self):
        from dataclasses import replace
        r = self.plan([replace(item("A", geo="G"), native_id="Native"),
                       replace(item("B", geo="G"), native_id="Native")])
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.count("DUPLICATE_NATIVE_ID"), 1)

    def test_missing_parent_is_fatal(self):
        r = self.plan([item("Child", parent="UnknownParent", geo="G")])
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.count("REFERENCE_MISSING"), 1)

    def test_reference_and_parent_same_node_is_not_false_cycle(self):
        r = self.plan([item("Source", geo="SharedG"),
                       item("Copy", "instance", source="Source", parent="Source")])
        self.assertEqual(r.status, "success")
        self.assertEqual(r.count("REFERENCE_CYCLE"), 0)
        self.assertEqual(r.objects[1].geometry_id, "SharedG")

    def test_missing_root_world_matrix_is_fatal_without_origin_default(self):
        r = self.plan([item("A", geo="G", world=None)])
        self.assertEqual(r.status, "failed")
        self.assertIsNone(r.objects[0].world_matrix)
        self.assertEqual(r.count("WORLD_UNRESOLVED"), 1)

    def test_mirrored_nonuniform_nested_transform_evidence_preserved(self):
        # F1 provides and validates these exact matrices; F8 must not compose
        # or re-normalize them. Negative determinant is intentionally retained.
        nonuniform = ((2., 0., 0., 9.), (0., -3., 0., -4.),
                      (0., 0., 0.5, 1.), (0., 0., 0., 1.))
        child_local = mat(3., -2., 1., scale=0.5)
        child_world = ((1., 0., 0., 15.), (0., -1.5, 0., 2.),
                       (0., 0., 0.25, 1.5), (0., 0., 0., 1.))
        r = self.plan([item("Root", "group", local=nonuniform, world=nonuniform),
                       item("Nested", "group", parent="Root", local=IDENTITY, world=nonuniform),
                       item("Mesh", parent="Nested", geo="G", local=child_local, world=child_world),
                       item("Copy", "instance", parent="Nested", source="Mesh",
                            local=mat(-2.), world=mat(-10., scale=-1.))])
        self.assertEqual(r.status, "success")
        self.assertEqual(r.objects[0].world_matrix, nonuniform)
        self.assertEqual(r.objects[2].local_matrix, child_local)
        self.assertEqual(r.objects[2].world_matrix, child_world)
        self.assertEqual(r.objects[3].world_matrix, mat(-10., scale=-1.))
        self.assertEqual(r.objects[3].geometry_id, "G")

    def test_converging_reference_dag_is_linear_and_not_cyclic(self):
        # ~3,000 nodes, two edges per instance, repeated source reuse.
        records = [item("Source", geo="G")]
        for i in range(1, 3000):
            records.append(item(f"N{i}", "instance", source="Source",
                                parent=f"N{i-1}" if i > 1 else None))
        r = InstanceGraphPlanner(Limits(max_depth=512)).plan_scene(records)
        self.assertEqual(r.status, "failed")  # graph depth correctly bounded
        self.assertEqual(r.count("REFERENCE_CYCLE"), 0)
        self.assertGreater(r.count("GRAPH_DEPTH"), 0)

    def test_nested_material_overrides_remain_object_local(self):
        a = item("A", geo="G", materials=("Mat0", "Mat1"))
        b = item("B", "instance", source="A", overrides=((0, "MatBlue"),))
        c = item("C", "instance", source="B", overrides=((1, "MatRed"),))
        r = self.plan([a, b, c])
        self.assertEqual(r.status, "success")
        self.assertEqual(tuple(x.geometry_id for x in r.objects), ("G", "G", "G"))
        self.assertEqual(r.objects[0].material_ids, ("Mat0", "Mat1"))
        self.assertEqual(r.objects[1].material_overrides, ((0, "MatBlue"),))
        self.assertEqual(r.objects[2].material_overrides, ((1, "MatRed"),))
        self.assertEqual(r.objects[1].material_ids, ())  # no cross-object mutation


    def test_malformed_source_key_is_fatal_not_unhandled_exception(self):
        from dataclasses import replace
        malicious = replace(item("X", "instance", source=None),
                            source_node_id=["not", "hashable"])
        r = self.plan([malicious])
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.count("INVALID_SOURCE_ID"), 1)
        self.assertIsNone(r.objects[0].source_node_id)

    def test_malformed_geometry_key_is_fatal_not_unhandled_exception(self):
        from dataclasses import replace
        malicious = replace(item("X", geo="G"), geometry_id=["not", "hashable"])
        r = self.plan([malicious])
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.count("INVALID_GEOMETRY_ID"), 1)
        self.assertIsNone(r.objects[0].geometry_id)

    def test_malformed_material_inputs_are_bounded_and_failed(self):
        from dataclasses import replace
        malicious = replace(item("X", geo="G"), material_ids=None,
                            material_overrides=(("bad",),))
        r = self.plan([malicious])
        self.assertEqual(r.status, "failed")
        self.assertGreater(r.count("MATERIAL_LIMIT"), 0)
        self.assertGreater(r.count("INVALID_MATERIAL_OVERRIDE"), 0)

    def test_f0_plan_returns_actual_instance_plan(self):
        node = SceneNode("Test", "Duplicate", "INSTANCE",
                         source_metadata={"instance_source_id": "Original",
                                          "world_matrix": mat(8.)})
        planned = InstanceGraphPlanner().plan(node)
        self.assertIsInstance(planned, InstancePlan)
        self.assertEqual(planned.node_id, "Test")
        self.assertEqual(planned.source_node_id, "Original")

    def test_f0_plan_port_accepts_safe_source_metadata(self):
        n = SceneNode("Id0", "source", "MESH", source_metadata={
            "instance_source_id": "Id1", "world_matrix": mat(5)})
        r = InstanceGraphPlanner().plan(n)
        self.assertEqual(r.source_node_id, "Id1")
        self.assertEqual(r.world_matrix, mat(5))


if __name__ == "__main__":
    unittest.main()
