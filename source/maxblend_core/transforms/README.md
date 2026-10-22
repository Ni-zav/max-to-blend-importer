# F1 — pure affine transform module (Wave 1)

This GPL-compatible module adds a **pure Python, offline planning layer**, not a replacement for the current Blender importer. No `bpy`, Autodesk dependencies, dynamic scene evaluation or external calls.

## Contracts and usage

- F0 interface: `maxblend_core.interfaces.TransformPlanner.plan(node, *, meters_per_source_unit)` returns `TransformPlan`; `TransformEngine.plan_scene(nodes)` also returns an audit record per stable ID.
- P0 scene schema: `TransformRecord.manifest_matrices()` provides `local_matrix`, `world_matrix` and `source_raw_matrix` as row-major 16-number lists or `null`.
- Explicit source-space convention: affine 4×4, column vectors, RH Z-up meters after conversion; `world = parent_world @ local`.
- Geometry coordinates should be converted with `coordinate_basis()` **once**. Convert local/object-offset matrices with `change_basis()` **once**; do not apply a second scale through Blender display units.
- `AxisConvention(up, forward, handedness)` describes *source* axes; default corresponds to canonical Blender RH Z-up/-Y forward, **not evidence** of a particular MAX file's axes. F6 must pass verified metadata/operator-selected mapping if different.
- `SourceUnits(name, meters_per_unit, operator_assumption)` models physical MAX *system* units. Unknown metadata yields `unknown_system_units` and no transformed matrix until the operator supplies an assumption. Conflicting metadata raises an error. `BlenderDisplay` never alters physical transformations.
- Use `source_metadata['matrix_space']='normalized'` only for independently proven, already-normalized local matrices. Default is `source`. Static controller formats supported for evaluated matrices: `matrix4`, `static_affine`, `prs_static`; other stated formats report unsupported.
- Use `source_metadata['geometry_offset_matrix']` for an independently decoded source mesh-to-node object-offset/pivot matrix. The record retains source and normalized offsets separately. A legacy `0x96A/0x96B/0x96C` triplet must not be silently presumed to have mesh/object/pivot semantics.
- `parent_local_preserving_world()` computes `parent_inverse @ existing_world`; reject singular parent matrices. `bake_points()` is optional and non-mutating. Do not decompose sheared matrices into Blender location/rotation/scale blindly.
- `TransformEvidence` and `MatrixProperties` retain raw source matrices, conversion flags, mirrored determinants and shear diagnostics for reversible audit.

## Precise F6 integration port (not edited here)

At `source/import_max.py::_dispatch_scene_import()`, after F5 hostile-file limits and audited parser extraction, provide stable node IDs/parent IDs, evaluated full *local* matrices and audited geometry offsets to `SceneNode`. Parse/verify source units and axes once (or require operator assumption); call `TransformEngine.plan_scene()` before creating/parenting Blender objects. Set parent first and assign returned normalized **local** matrix or preserve evaluated world via `parent_local_preserving_world`; do not combine with the legacy `mscale` physical conversion. Mesh vertices need exactly one `coordinate_basis` conversion; preserve shared mesh instances. Populate P0 object `source_raw_matrix` and `transforms.unit_conversion_applied`/`axis_conversion_applied` from actual evidence, **never** assume all objects are converted if any is unresolved. Preserve the legacy fallback and regression tests.

Required adapter enhancement: the F0 `TransformPlan` has no fields for offset/evidence/flags and P0 object schema only stores raw node matrix. F6 should keep richer `TransformRecord` in a private audit sidecar or submit a separate contract change if wire-level original offset/controller evidence is needed. Do **not** inject additional properties into the frozen JSON schema.

## Verification

```sh
python -m compileall -q source/maxblend_core/transforms tests/transforms
python -m unittest discover -s tests/transforms -v
python -m unittest discover -s tests/baseline -v
```

Tests use synthetic, generated numeric matrices only. They verify no native .max import, private studio-file conversion, Blender object creation, real-world fidelity, native MAX writing, or compatibility with arbitrary animated/constraint controllers. Genuine Blender headless smoke, real import checks and release packaging belong to F6/G1/G2. No customer data belongs in CI.