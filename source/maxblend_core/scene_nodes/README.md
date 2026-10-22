# F7 scene-node plans: status and integration handoff

This subtree is a Blender-independent **description/validator**, not a MAX binary
decoder or an importer. It relies only on the frozen F0 interfaces and standard
library. It does not load scripts, resources, external files, or call the network.
Upstream GPL-2.0-or-later notices remain untouched.

## Current upstream native coverage (main as of Wave 0)

Findings from `source/import_max.py` (v1.9.2 fork):

- `SKIPPABLE` identifies camera (`0x1002`), camera target (`0x1020`),
  Omni (`0x1011`), Free Direct (`0x1013`), VRayLight
  (`0x5FD602DF3C5575A1`) but `create_mesh` routes them to
  `create_skipable`: **no Blender camera/light objects are created**.
  A GUID hint here is not a validated decoder for renderer parameters.
- Scene chunks already decode names (`0x0962`), parent index
  (`0x0960`) and mapped reference slots (`0x2035`):
  transform slot 0, mesh slot 1, material slot 3, layer slot 6.
  `make_scene` assigns parents by object **name**, without a validated
  unique graph, and it doesn't preserve the referenced layer as a collection.
  Visibility is not reliably extracted/applied.
- `get_position/get_rotation/get_scale` handle specific *single static values*
  from controller classes (`0x2008`, `0x442312`, `0x2012`,
  `0x442313`, `0x2010`, `0x442315`, and list/wire variants).
  They do **not** decode a full frame-indexed keyframe sequence, native
  interpolation, constraint graph or simulation; `create_matrix` applies
  one transform.
- `read_scene` reads the Scene stream and optional metadata; it does not
  establish a verified frame range or scene FPS from Config/timebase chunks.
  The `0x2501/0x2503/0x2504/0x2505` payloads must not be inferred to
  contain reliable track timing solely from the upstream static value readers.

This is a source audit, not empirical MAX-class fidelity evidence.

## Typed plan and safe interpretation

- `Evidence` locators contain only approved stream names and bounded chunk
  identifiers/indexes. **Never** place client source paths or names in evidence.
- `NodeDetails`, `Layer`, `Camera`, `Light`, `Timeline`, `Keyframe`
  and `TransformTrack` retain facts only when an authorized decoder provided
  them. Unknown fields remain `None`. Track values explicitly distinguish
  `KEYED` from `SAMPLED`; interpolation is `UNKNOWN` unless verified.
- F1 must normalize axis/units exactly once before setting
  `normalized_transform=True` or `normalized_values=True`. Quaternion
  values are `(w,x,y,z)`; translations in meters, angles in radians,
  frame values in the explicit timeline FPS. This module **does not**
  apply conversion matrices itself.
- Cameras cover perspective FOV/focal length/filmback/lens shifts, orthographic
  width and near/far clipping. Light source units are ambiguous unless
  documented and are never silently converted to watts. Unsupported
  renderer photometry is reported as partial.
- Validation checks missing/duplicate parent references, parent/layer cycles,
  missing layers/targets, incomplete tracks, inconsistent camera parameters,
  invalid quaternion/key ordering, hostile nonfinite values and fixed record
  ceilings. No Blender scene is modified.

## Frozen v1 wire-contract gap: MUST be addressed by F6/P6

`schemas/scene-manifest-v1.schema.json` supports only animation summaries:
`id`, `target_object_id`, `start_frame`, `end_frame`, `fps`,
`supported_tracks`, `unsupported_tracks`, `coverage`, `warnings`.
There are **no** fields for track keyframe `frame/value`, semantic mode,
interpolation provenance, camera-specific parameters, light parameters or
layer membership/visibility. Do **not** smuggle these into arbitrary
metadata or claim a complete interchange roundtrip. The only v1 serializer
here, `manifest_animation_summaries`, emits a `partial` coverage
warning `keyframe_payload_not_in_v1` even for valid internal tracks.

**Exact integration port request:** F6 should add an explicit
`source/import_max.py` decoded-scene-to-`NodeDetails/Layer/Timeline/TransformTrack`
adapter via the Wave 0 `_dispatch_scene_import` seam. It must map stable
object IDs (not names), create Blender cameras/lights/collections, assign
visibility/hierarchy, and sample only verified native controllers at explicit
FPS (no script evaluation). Coordinate with F1 on a normalized matrix/TRS
adapter and with F5 on hostile chunk bounds. P6/contract owner should
propose a **separately reviewed versioned schema/adapter change** to carry
keyframe samples and camera/light/layer details, plus authoritative timeline
provenance. No shared files are edited in this F7 PR.

## Validation

```sh
python -m compileall -q source/maxblend_core/scene_nodes tests/scene_nodes
python -m unittest discover -s tests/scene_nodes -v
python -m unittest discover -s tests/baseline -v
```

Synthetic fixtures validate typed plans, error reporting and schema summaries
only. Not tested here: real MAX file decoding, animation playback, camera
projection in Blender, light photometry, parent transforms after unit/axis
conversion, headless real-scene import, or any native MAX exporter.
