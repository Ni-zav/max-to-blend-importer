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

## F6/P6 manifest mapping (authoritative Wave 0 v1 shape)

The source and target of every mapping below must be backed by a verified F0
decoder; a field present in the schema does **not** mean MAX parsing exists.

| F7 decoded plan fact | P0 `maxblend.scene/v1` destination | Wire status / integration owner |
| --- | --- | --- |
| `SceneNode.node_id/name/kind/parent_id` | `objects[].id/name/kind/parent_id` | **v1 exists**; F6 stable object-ID mapping; P6 schema validation |
| normalized `SceneNode.local_matrix` | `objects[].local_matrix` (flatten 16 values) | **v1 exists**; F1 confirms axis/unit conversion once, F6 projects |
| `NodeDetails.evidence` | `objects[].provenance.evidence` and `objects[].warnings[].evidence` | **v1 exists**, evidence tokens only (no paths); F6/P6 project valid record |
| missing parents, layer links, camera targets | `objects[].warnings[]`, global `warnings[]` | **v1 exists** for deterministic loss diagnostics |
| `Timeline.start_frame/end_frame/fps` | `animations[].start_frame/end_frame/fps` | **v1 exists**, only per-animation summary; global timeline is **internal-only** |
| track `target_id/channel` | `animations[].target_object_id/supported_tracks/unsupported_tracks` | **v1 exists**, coverage is **partial**, not playable |
| `TransformTrack.keys[].frame/value`, `mode`, verified interpolation | none | **internal only**; requires separately reviewed **versioned schema PR** for faithful interchange |
| camera projection/FOV/focal/filmback/shift/ortho/clip and `target_id` | `objects[].kind=CAMERA` + warnings only | camera attributes are **internal only**, future **versioned schema PR** |
| light kind/intensity/unit/color/area/photometry warning | `objects[].kind=LIGHT` + warnings only | light attributes are **internal only**, future **versioned schema PR** |
| layer names, layer hierarchy, assigned layers, visibility | no typed v1 layer/visibility fields; `objects[].warnings[]` may record known loss | **internal only**, future **versioned schema PR** |
| unsupported controllers/constraints/rigs/particles | `animations[].unsupported_tracks` and `warnings[]` | **v1 exists as loss reporting**, not supported playback |

F6 should capture a verified camera-target reference only if a native reference
index was decoded. For a non-NULL `Camera.target_id`, `build_scene`
rejects an unknown target; `None` remains unknown and must not infer no
target exists. F6 must not manufacture camera projection, frame rate, light
intensity or physical-unit conversion. P6 must not add unknown JSON keys to
the frozen schema to carry the internal plans.

## Gate 1 regression commands (full F0 checkout required)

```sh
PYTHONPATH=source python -m unittest discover -s tests/scene_nodes -v
python -m compileall -q source/maxblend_core/scene_nodes tests/scene_nodes
PYTHONPATH=source python -m unittest discover -s tests/baseline -v
```

The existing GitHub Wave 0 workflow **does not** run the new
`tests/scene_nodes` suite. A green extension registration check is not a
MAX camera/light/animation playback smoke test. No synthetic fixture proves
binary chunk timings or native MAX controller fidelity.
