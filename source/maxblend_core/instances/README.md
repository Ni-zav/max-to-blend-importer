# F8 — architectural instances, source references and external placeholders

Pure-Python planning module; deliberately **not active during normal MAX import** until F6
wires the existing source/import_max.py::_dispatch_scene_import seam. This is
not a native format decoder or evidence of MAX/Blender fidelity. No Blender,
Autodesk, networking or filesystem calls are made by this module.

## Upstream mapping for F6 (must verify against real, authorized samples)

- Importer's SCENE_LIST[0].children and get_node(index) use per-file chunk
  indices, while get_node_name is only a display label. Assign validated
  unique SceneNode.node_id from scene indices; do not use object names as IDs.
- get_node_parent reads parent index from 0x0960; get_matrix_mesh_material
  follows 0x2034 positional / 0x2035 keyed references and returns geometry
  in slot 1 and material in slot 3. Derive InstanceInput.geometry_id from a
  **stable source chunk identity**, not from geometry contents or class names.
  A repeated geometry chunk means one geometry resource, many node instances.
- make_scene/create_object currently key hierarchy dictionaries by object
  names and create_mesh reconstructs geometry each time. F6 needs ID-keyed
  hierarchy and Blender mesh datablock cache; this module does not patch them.
- create_object performs a mesh/pivot adjustment while F1 owns matrix/units
  semantics. Pass its normalized local/world matrices through unchanged; never
  synthesize identity/world-at-origin for missing transforms. Confirm that
  group hierarchy with nonuniform scale, negative determinants and pivots
  remains correct before exposing these as production claims.
- Renderer-specific VRayProxy/CoronaProxy, XRef and object references need
  F6 class-GUID classification before marking proxy / xref. Their format
  is not automatically reconstructed. No renderer-specific asset scanning;
  F4 owns authorized texture/path resolution. Unsafe paths are suppressed.
- Do not inspect/execute embedded MAX scripts or expand reference recursion.

## Integration contract / exact remaining F6 port

1. At existing _dispatch_scene_import, construct a sequence of InstanceInput
   objects holding SceneNode IDs, role, source_node_id, geometry_id,
   material_ids and F1 world_matrix from vetted parser metadata. Preserve
   scene-index to chunk mapping.
2. Run InstanceGraphPlanner().plan_scene(inputs) **before** Blender object
   creation. Refuse materialization when status == "failed" or truncated.
   Missing parent/source references, geometry-bearing objects without an
   evidenced F1 world transform, incompatible geometry identities, cycles, and
   excessive depth are hard failures. For partial/unsupported objects, keep
   meaningful, visible diagnostics; never silently replace an unresolved
   geometry or proxy with an empty mesh.
3. Map each GeometryResource.geometry_id to one Blender mesh datablock. Each
   ObjectInstance becomes its own Blender object; source_node_id is *not*
   recursively expanded. Use per-object material slots when possible; use
   copy-on-write mesh variants only when per-face/material-slot layouts demand
   it. Never mutate shared mesh geometry/material arrays across instances.
4. Wire geometry topology/UV to F2, transforms to F1, shading to F3, external
   asset lookup to F4, and parser hardening to F5. F7 owns nonmesh scene kinds.
5. The frozen v1 schema **does not contain** explicit geometry_id,
   instance_of, proxy resolution or per-instance override fields. P6/F6 must
   either preserve these in a separately versioned internal sidecar and export
   ordinary v1 object geometry statistics/material assignments, or propose a
   **separate** contract revision before transmitting those values. Do not add
   undeclared manifest keys or infer identity from repeated names.

## Tests

Run: python -m unittest discover -s tests/instances -v

Synthetic hierarchies, 1/N geometry identity, nested instances, independent
transforms (including negative determinant and nonuniform scale), per-object
material overrides, missing proxies/blocked paths, repeated names with distinct
IDs, native-ID collisions, missing parents, malformed references, cycles,
wide/deep graphs, a 12,000-object memory bound and deterministic caps. These
tests do **not** exercise Blender or import real MAX. F0 baseline CI currently
does not discover this subtree; G1/F6 should wire full-suite CI under shared
file authority.

G1 requests three exact commands on an actual checkout:

```sh
PYTHONPATH=source python -m unittest discover -s tests/instances -v
python -m compileall -q source/maxblend_core/instances tests/instances
PYTHONPATH=source python -m unittest discover -s tests/baseline -v
```

Do not substitute the Wave 0 baseline green check for an execution of the
F8 suite. This worker does not edit root workflows or platform schemas.
Real Blender registration smoke in baseline CI does not establish that F8 is
wired into actual .max scene import; renderer proxy decoding and Blender
datablock sharing remain F6 integration tasks.
