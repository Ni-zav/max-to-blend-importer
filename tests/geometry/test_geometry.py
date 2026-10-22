# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic chunk payloads only. No client data or real .max fidelity claim."""
from pathlib import Path
import math
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'source'))
from maxblend_core.geometry import (  # noqa: E402
    Limits, MapChunk, PolyFaceChunk, reconstruct_editable_mesh,
    reconstruct_editable_poly, unsupported_geometry, project_material_slots,
)


def pack_mesh_verts(vertices):
    return struct.pack('<I', len(vertices)) + b''.join(struct.pack('<3f', *v) for v in vertices)


def pack_poly_verts(vertices):
    return struct.pack('<I', len(vertices)) + b''.join(
        struct.pack('<I3f', i + 42, *v) for i, v in enumerate(vertices))


def pack_mesh_faces(faces, materials=None):
    materials = materials if materials is not None else [0] * len(faces)
    return struct.pack('<I', len(faces)) + b''.join(
        struct.pack('<3IIHH', *f, 7, 3, m) for f, m in zip(faces, materials))


def face(ids, mat=0, element=None):
    return PolyFaceChunk(struct.pack(f'<I{len(ids)}I', len(ids), *ids),
                         struct.pack('<H', mat) if mat is not None else None,
                         source_element=element)


def uvmap(channel, points, faces, encoding='triangles'):
    coords = pack_mesh_verts(points)
    if encoding == 'triangles':
        ids = struct.pack('<I', len(faces)) + b''.join(struct.pack('<3I', *f) for f in faces)
    else:
        ids = b''.join(struct.pack(f'<I{len(f)}I', len(f), *f) for f in faces)
    return MapChunk(channel, coords, ids, encoding)


V = ((0, 0, 0), (2, 0, 0), (2, 3, 0), (0, 3, 0))


class EditableMeshTests(unittest.TestCase):
    def recon(self, verts=V, faces=((0, 1, 2), (0, 2, 3)), materials=(1, 12), **kw):
        return reconstruct_editable_mesh('synthetic', pack_mesh_verts(verts),
                                         pack_mesh_faces(faces, materials), **kw)

    def test_triangle_faces_and_material_ids_and_provenance(self):
        result = self.recon()
        self.assertEqual(result.status, 'partial')  # Normals unknown, not invented.
        self.assertEqual(result.mesh.faces, ((0, 1, 2), (0, 2, 3)))
        self.assertIsNone(result.plan.face_material_indices)
        self.assertEqual(result.mesh.face_origins[1].source_face, 1)
        self.assertEqual(result.mesh.face_origins[0].edge_flags, 7)
        self.assertEqual(result.mesh.vertices[2], (2, 3, 0))

    def test_uv_seam_reuses_geometry_vertex_but_not_map_index(self):
        # Shared geometry vertex 0 has UV ids 0 and 3 across its two faces.
        uv = uvmap(1, [(0, 0, 0), (1, 0, 0), (1, 1, 0), (.4, .4, 0), (0, 1, 0)],
                   [(0, 1, 2), (3, 2, 4)])
        result = self.recon(maps=[uv])
        self.assertEqual(result.mesh.faces[0][0], result.mesh.faces[1][0])
        self.assertNotEqual(result.mesh.maps[0].loop_uv[0], result.mesh.maps[0].loop_uv[3])
        self.assertEqual(len(result.mesh.vertices), 4)

    def test_multiple_uv_channels_keep_numeric_ids_and_w(self):
        a = uvmap(7, [(0, 0, .75)] * 3, [(0, 1, 2)] * 2)
        b = uvmap(2, [(1, 1, .25)] * 3, [(0, 1, 2)] * 2)
        result = self.recon(maps=[a, b])
        self.assertEqual([m.channel for m in result.mesh.maps], [7, 2])
        self.assertEqual(result.mesh.maps[0].points[0][2], .75)
        self.assertEqual(result.plan.uv_channel_count, 2)

    def test_clockwise_and_counterclockwise_winding_preserved(self):
        result = self.recon(faces=[(0, 1, 2), (2, 1, 0)], materials=[0, 0])
        self.assertEqual(result.mesh.faces[0], (0, 1, 2))
        self.assertEqual(result.mesh.faces[1], (2, 1, 0))

    def test_negative_transform_does_not_flip_vertices_or_faces(self):
        result = self.recon(mirrored_transform=True)
        self.assertEqual(result.mesh.faces[0], (0, 1, 2))
        self.assertIn('mirrored_transform_unapplied', [d.code for d in result.diagnostics])

    def test_empty_and_oversize_vertex_header_rejected(self):
        result = reconstruct_editable_mesh('id', struct.pack('<I', 1_000_001), pack_mesh_faces([]))
        self.assertEqual(result.status, 'failed')
        self.assertEqual(result.diagnostics[0].code, 'allocation_limit')
        self.assertIsNone(result.mesh)

    def test_truncated_vertex_payload_rejected(self):
        result = reconstruct_editable_mesh('id', struct.pack('<I', 4) + b'\0' * 12,
                                           pack_mesh_faces([(0, 1, 2)]))
        self.assertEqual(result.diagnostics[0].code, 'invalid_length')

    def test_truncated_face_payload_rejected(self):
        result = reconstruct_editable_mesh('id', pack_mesh_verts(V),
                                           pack_mesh_faces([(0, 1, 2)])[:-1])
        self.assertEqual(result.diagnostics[0].code, 'invalid_length')

    def test_invalid_face_indices_and_repeated_indices(self):
        for face_indices in [(0, 1, 55), (0, 0, 1)]:
            with self.subTest(face=face_indices):
                self.assertEqual(self.recon(faces=[face_indices], materials=[1]).status, 'failed')

    def test_nonfinite_coordinates_are_rejected(self):
        for v in (math.nan, math.inf, -math.inf):
            with self.subTest(value=v):
                result = self.recon(verts=[(v, 0, 0), (1, 0, 0), (1, 1, 0)])
                self.assertEqual(result.diagnostics[0].code, 'nonfinite_coordinate')

    def test_malformed_uv_reports_partial_base_mesh(self):
        uv = uvmap(3, [(0, 0, 0)], [(4, 4, 4), (4, 4, 4)])
        result = self.recon(maps=[uv])
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.mesh.maps, ())
        self.assertEqual(result.plan.face_count, 2)
        self.assertIn('invalid_uv_topology', [d.code for d in result.diagnostics])

    def test_oversize_uv_count_does_not_allocate(self):
        uv = MapChunk(1, struct.pack('<I', 2 ** 32 - 1), struct.pack('<I', 2), 'triangles')
        result = self.recon(maps=[uv])
        self.assertEqual(result.mesh.maps, ())
        self.assertIn('allocation_limit', [d.code for d in result.diagnostics])

    def test_partial_import_reports_unknown_modifier_stack(self):
        result = self.recon(unknown_modifiers=True)
        self.assertEqual(result.status, 'partial')
        self.assertIn('unknown_modifier_stack', [d.code for d in result.diagnostics])

    def test_normals_and_explicit_sharp_edges(self):
        normals = [(0, 0, 2)] * 6
        result = self.recon(sharp_edges=[(2, 0)], corner_normals=normals)
        self.assertEqual(result.status, 'partial')  # Material slots unresolved.
        self.assertEqual(result.mesh.corner_normals, ((0, 0, 1),) * 6)
        self.assertEqual(result.mesh.sharp_edges, ((0, 2),))

    def test_bad_sharp_edges_or_normal_count_failed(self):
        self.assertEqual(self.recon(sharp_edges=[(1, 3)]).diagnostics[0].code,
                         'invalid_sharp_edge')
        self.assertEqual(self.recon(corner_normals=[(0, 0, 1)]).diagnostics[0].code,
                         'invalid_normals')

    def test_raw_face_material_id_not_remapped_to_blender_slot(self):
        result = self.recon(materials=[65535, 0])
        self.assertEqual(result.mesh.face_material_ids, (65535, 0))


class EditablePolyTests(unittest.TestCase):
    def recon(self, verts=V, faces=None, **kw):
        if faces is None:
            faces = [face((0, 1, 2, 3), 3, 91)]
        return reconstruct_editable_poly('poly', pack_poly_verts(verts), faces, **kw)

    def test_quad_ngon_and_vertex_source_ids(self):
        v = V + ((-1, 1, 0),)
        result = self.recon(verts=v, faces=[face((0, 1, 2, 3, 4), 2, 99), face((0, 1, 2), 7, 100)])
        self.assertEqual(list(map(len, result.mesh.faces)), [5, 3])
        self.assertEqual(result.mesh.source_point_ids, (42, 43, 44, 45, 46))
        self.assertEqual(result.mesh.face_origins[0].source_element, 99)
        self.assertIsNone(result.plan.face_material_indices)

    def test_poly_uv_multiple_maps_and_winding(self):
        m = uvmap(2, [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)], [(3, 2, 1, 0)],
                  encoding='polygons')
        result = self.recon(faces=[face((3, 2, 1, 0))], maps=[m],
                            corner_normals=[(0, 0, 1)] * 4)
        self.assertEqual(result.status, 'partial')  # Material slots unresolved.
        self.assertEqual(result.mesh.faces, ((3, 2, 1, 0),))
        self.assertEqual(result.mesh.maps[0].corner_indices, ((3, 2, 1, 0),))

    def test_missing_material_id_is_unknown_not_zero(self):
        result = self.recon(faces=[face((0, 1, 2), None)])
        self.assertEqual(result.status, 'partial')
        self.assertIsNone(result.plan.face_material_indices)
        self.assertEqual(result.mesh.face_material_ids, (None,))

    def test_truncated_poly_face_and_bad_face_arity(self):
        self.assertEqual(self.recon(faces=[PolyFaceChunk(b'\x04\x00\x00\x00\x01')]).status, 'failed')
        self.assertEqual(self.recon(faces=[face((0, 1))]).diagnostics[0].code,
                         'invalid_topology')

    def test_bad_poly_uv_face_corner_count(self):
        m = uvmap(1, [(0, 0, 0)] * 3, [(0, 1, 2)], encoding='polygons')
        result = self.recon(maps=[m])
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.mesh.maps, ())

    def test_missing_faces_report_failure_not_empty_mesh(self):
        self.assertEqual(self.recon(faces=[]).diagnostics[0].code, 'missing_topology')

    def test_duplicate_map_channel_rejected_as_partial(self):
        m = uvmap(1, [(0, 0, 0)] * 4, [(0, 1, 2, 3)], encoding='polygons')
        result = self.recon(maps=[m, m])
        self.assertEqual(len(result.mesh.maps), 1)
        self.assertIn('duplicate_map_channel', [d.code for d in result.diagnostics])

    def test_limited_face_size(self):
        f = face(tuple(range(5)))
        result = self.recon(verts=V + ((1, 1, 0),), faces=[f],
                            limits=Limits(max_face_corners=4))
        self.assertEqual(result.diagnostics[0].code, 'allocation_limit')

    def test_unsupported_objects_report_explicitly(self):
        result = unsupported_geometry('other', 'UnknownProcedural')
        self.assertEqual(result.status, 'unsupported')
        self.assertIsNone(result.mesh)
        self.assertEqual(result.plan.vertex_count, None)



class MaterialSlotProjectionTests(unittest.TestCase):
    """Raw MAX IDs and Blender/P0 zero-based slot indices are distinct."""

    def native_three(self, **kw):
        verts = ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0))
        faces = ((0, 1, 2), (0, 2, 3), (1, 2, 3))
        return reconstruct_editable_mesh('mat', pack_mesh_verts(verts),
                                         pack_mesh_faces(faces, (2, 7, 65535)), **kw)

    def test_native_noncontiguous_ids_cannot_silently_become_slots(self):
        result = self.native_three()
        self.assertEqual(result.mesh.face_material_ids, (2, 7, 65535))
        self.assertIsNone(result.plan.face_material_indices)
        self.assertEqual(result.status, 'partial')
        self.assertIn('material_slot_mapping_unresolved', [d.code for d in result.diagnostics])

    def test_complete_explicit_map_produces_ordered_zero_based_slots(self):
        # The native IDs have no positional relation to the three material slots.
        original = self.native_three(corner_normals=[(0, 0, 1)] * 9)
        projected = project_material_slots(original, {2: 0, 7: 2, 65535: 1}, slot_count=3)
        self.assertEqual(projected.status, 'success')
        self.assertEqual(projected.plan.face_material_indices, (0, 2, 1))
        self.assertEqual(projected.mesh.face_material_ids, (2, 7, 65535))
        self.assertIs(projected.mesh, original.mesh)  # Instancing-safe immutable buffer.
        self.assertIsNone(original.plan.face_material_indices)
        self.assertFalse([d for d in projected.diagnostics if d.code == 'material_slot_mapping_unresolved'])

    def test_missing_map_fails_closed_without_partial_projection(self):
        result = self.native_three()
        projected = project_material_slots(result, {2: 0, 7: 2}, slot_count=3)
        self.assertIsNone(projected.plan.face_material_indices)
        self.assertEqual(projected.status, 'partial')
        self.assertEqual(projected.mesh.face_material_ids, (2, 7, 65535))
        self.assertIn('material_slot_mapping_incomplete', [d.code for d in projected.diagnostics])

    def test_invalid_slot_and_mapping_types_are_rejected(self):
        result = self.native_three()
        for slots, mapping in (
            (2, {2: 0, 7: 1, 65535: 2}),
            (3, {2: 0, 7: -1, 65535: 2}),
            (3, {2: 0, 7: True, 65535: 2}),
            (3, {-1: 0, 7: 2, 65535: 1}),
            (True, {2: 0, 7: 2, 65535: 1}),
            (3, None),
        ):
            with self.subTest(slots=slots, mapping=mapping):
                projected = project_material_slots(result, mapping, slot_count=slots)
                self.assertIsNone(projected.plan.face_material_indices)
                self.assertEqual(projected.status, 'partial')
                self.assertIn('invalid_material_slot_mapping', [d.code for d in projected.diagnostics])

    def test_unknown_native_face_id_remains_unknown_even_with_map(self):
        original = reconstruct_editable_poly('poly', pack_poly_verts(V),
                                              [face((0, 1, 2), None)])
        projected = project_material_slots(original, {2: 0}, slot_count=1)
        self.assertEqual(projected.mesh.face_material_ids, (None,))
        self.assertIsNone(projected.plan.face_material_indices)
        self.assertIn('material_slot_mapping_incomplete', [d.code for d in projected.diagnostics])

    def test_uv_corruption_remains_partial_after_valid_material_projection(self):
        bad = uvmap(1, [(0, 0, 0)], [(9, 9, 9)] * 3)
        original = self.native_three(maps=[bad], corner_normals=[(0, 0, 1)] * 9)
        projected = project_material_slots(original, {2: 0, 7: 2, 65535: 1}, slot_count=3)
        self.assertEqual(projected.plan.face_material_indices, (0, 2, 1))
        self.assertEqual(projected.status, 'partial')
        self.assertIn('invalid_uv_topology', [d.code for d in projected.diagnostics])



if __name__ == '__main__':
    unittest.main()
