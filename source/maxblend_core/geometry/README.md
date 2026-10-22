# F2 geometry reconstruction — F6 integration handoff

SPDX-License-Identifier: GPL-2.0-or-later

Wave 1 implements Blender-free synthetic decoding only. No runtime import hook, native .max roundtrip, or measured scene fidelity is claimed.

## Required F6 integration port

F0 provides `source/import_max.py::_dispatch_scene_import()`; **only F6** may modify this shared importer. After F5 has bounded and validated the container, collect the existing raw child payloads and call:

- Editable Mesh: `reconstruct_editable_mesh(node_id, vertex_data=chunk_0x0914.data, face_data=chunk_0x0912.data, maps=...)`. Map channel ids come from `0x0924`/`0x0959`, XYZ from `0x0916`/`0x2394`, and per-triangle map indices from `0x0918`/`0x2396`. Pair maps by channel identity rather than assuming parallel list positions.
- Editable Poly: `reconstruct_editable_poly(node_id, vertex_data=chunk_0x0100.data, face_chunks=[PolyFaceChunk(indices=child_0x0110.data, material=optional_child_0x0130.data), ...], maps=...)`. Poly map points are `0x0128`, per-face UV corner indices `0x012B`, and channel `0x0124`.
- The `0x011A` point-record path and `0x0108`/`0x010A`/`0x0310` fallback topology require separately verified formats; do not render silently empty geometry.
- F2 returns immutable `MeshBuffer` and F0-compatible `GeometryPlan` and `Diagnostic` records. On `failed` or `unsupported`, do not construct a mesh. For `partial`, visibly report why (e.g. invalid UV map, missing normals, modifier unknown). Preserve original face order, winding, separate UV corner indices and provenance in downstream results.
- Raw per-face MAX material IDs are **not necessarily zero-based Blender material slots**. Wait for F3's Multi/Sub mapping before binding polygon indices; never remap unknown IDs to zero.
- Allocate distinct mutable Blender datablocks per instance. Source arrays may share immutable F2 buffers. F1 alone applies unit/axis/mirror transforms; F2 does not alter local coordinates or winding.
- Absent hard/soft normal data stays unknown; triangle visibility flags do not prove split normals. The manifest's F0 `GeometryPlan` lacks UV/provenance fields: F6 must retain `MeshBuffer` separately or request an approved schema extension rather than discarding these attributes.

## Validation

```sh
python -m compileall -q source/maxblend_core/geometry tests/geometry
python -m unittest discover -s tests/geometry -v
```

These synthetic fixtures cover supported payloads and corruption. A real Blender 4.2 smoke test, private `.max` import, evaluated modifiers, procedural objects and verified dimensions require separate offline validation. Never upload private customer materials to public repositories or CI.
