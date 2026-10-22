# F2 geometry reconstruction — F6 integration handoff

SPDX-License-Identifier: GPL-2.0-or-later

Wave 1 implements Blender-free synthetic decoding only. No runtime import hook, native .max roundtrip, or measured scene fidelity is claimed.

## Required F6 integration port

F0 provides `source/import_max.py::_dispatch_scene_import()`; **only F6** may modify this shared importer. After F5 has bounded and validated the container, collect the existing raw child payloads and call:

- Editable Mesh: `reconstruct_editable_mesh(node_id, vertex_data=chunk_0x0914.data, face_data=chunk_0x0912.data, maps=...)`. Map channel ids come from `0x0924`/`0x0959`, XYZ from `0x0916`/`0x2394`, and per-triangle map indices from `0x0918`/`0x2396`. Pair maps by channel identity rather than assuming parallel list positions.
- Editable Poly: `reconstruct_editable_poly(node_id, vertex_data=chunk_0x0100.data, face_chunks=[PolyFaceChunk(indices=child_0x0110.data, material=optional_child_0x0130.data), ...], maps=...)`. Poly map points are `0x0128`, per-face UV corner indices `0x012B`, and channel `0x0124`.
- The `0x011A` point-record path and `0x0108`/`0x010A`/`0x0310` fallback topology require separately verified formats; do not render silently empty geometry.
- F2 returns immutable `MeshBuffer` and F0-compatible `GeometryPlan` and `Diagnostic` records. On `failed` or `unsupported`, do not construct a mesh. For `partial`, visibly report why (e.g. invalid UV map, missing normals, modifier unknown). Preserve original face order, winding, separate UV corner indices and provenance in downstream results.
- **G1 contract fix:** raw per-face MAX material IDs are **never** F0/P0 zero-based Blender material slots. `MeshBuffer.face_material_ids` contains only raw native IDs; `GeometryPlan.face_material_indices` is initially `None` with `material_slot_mapping_unresolved` diagnostic, even when every source face has a native ID.
- **Exact F3 -> F6 port:** F3 supplies independently validated native Multi/Sub material-ID -> Blender *ordered object material-slot index* mapping and the actual object `slot_count`. After material slots have been allocated in that order, F6 invokes `project_material_slots(result, native_id_to_slot, slot_count=number_of_object_slots)`. Only a complete, type/range-valid map populates F0 `GeometryPlan.face_material_indices`; F6 then maps that tuple to P0 `objects[].face_material_ids`. Missing source IDs / missing map entries / invalid slots keep the **entire projection `None`**, with a partial diagnostic. Do not insert default slot zero, use modulo, reorder faces, or infer positions from numeric IDs. Native source IDs remain unchanged in `MeshBuffer`. Object material slots and an actual mapping cannot be fabricated by F2.
- Allocate distinct mutable Blender datablocks per instance. Source arrays may share immutable F2 buffers. F1 alone applies unit/axis/mirror transforms; F2 does not alter local coordinates or winding.
- Absent hard/soft normal data stays unknown; triangle visibility flags do not prove split normals. The manifest's F0 `GeometryPlan` lacks UV/provenance fields: F6 must retain `MeshBuffer` separately or request an approved schema extension rather than discarding these attributes.

## Validation

```sh
python -m compileall -q source/maxblend_core/geometry tests/geometry
PYTHONPATH=source python -m unittest discover -s tests/geometry -v
PYTHONPATH=source python -m unittest discover -s tests/baseline -v
```

These synthetic fixtures cover supported payloads and corruption. F2's pure decoding does not require Blender; an optional real Blender 4.2 mesh-construction smoke test, private `.max` import, evaluated modifiers, procedural objects and verified dimensions require separate offline validation. Never upload private customer materials to public repositories or CI.
