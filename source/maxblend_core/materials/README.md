# F3 material recovery — isolated Wave 1 API

GPL-2.0-or-later. This code inherits the fork's upstream license obligations.
No native binary parser or Blender extension handler is changed by F3.

## Inputs and boundary

F6 decodes a native material chunk without executing embedded MAX scripts.
It calls:

    from maxblend_core.materials import plan_material, MaterialPlannerV1
    detail = plan_material("mat:opaque-unique", {
        "class": "CoronaPhysicalMtl", "renderer": "Corona",
        "name": "Generic Studio Surface",
        "params": {"base_color": (0.4, 0.5, 0.6),
                   "roughness": 0.35, "ior": 1.5},
        "assignment_ids": ["obj:opaque-unique"],
        "textures": {
            "bitmap": {"id": "tex:opaque-unique", "kind": "bitmap",
                       "state": "found"},
        },
    })

No claim is made about version-stable native parameter indices. F6 must map
native chunk properties to the decoded, named parameters above, retain
provenance, and validate IDs before invoking the planner. F3 does not read
.max files, register operators, traverse disks, download shaders, load images,
or run scripts.

MaterialDetail includes:
- plan: frozen F0 MaterialPlan, with coverage and Diagnostic records;
- unique material ID, display name, renderer/class, bounded data-only source
  parameters, unknown parameter records and per-channel value evidence;
- native Multi/Sub integer submaterial ID mapping and opaque assignment IDs;
- composite layer refs, front/back refs, two-sided intent;
- F4 texture IDs, resolution state, color/data role and inversion intent.

Unknown is NOT equivalent to supported. Standard shading and Corona/V-Ray
native closure behavior are necessarily approximations; genuine procedural and
layer graphs are not reconstructed. A missing or ambiguous bitmap is a loss.
The source material name is not an identity key.

## Wire handoff

    from maxblend_core.materials.manifest import as_manifest_material
    record = as_manifest_material(detail)

The returned record matches the shape of the frozen interchange-v1 material
schema. The seven core PBR slots are included. Extra native transmission/coat
intent stays in the local plan (the wire schema has no such slots);
therefore P0 projection emits p0_extra_channel_loss and marks such records
partial even if the Blender shader can reconstruct those local inputs. Native
submaterial IDs remain in MaterialDetail; F2/F6 must map them to real ordered
Blender material slots and material indices. The full manifest must be
cross-reference-validated by P0/P6, including texture IDs and assignments.

As requested by the schema, unknown source parameters are represented as
typed data only. String path-like values are redacted in wire projection.
F6 must never publish client scene names, source paths, material IDs,
manifest records, textures, or screenshots to GitHub.

## Blender node handoff

    from maxblend_core.materials.blender_nodes import build_material
    result = build_material(detail, {"tex:opaque-unique": authorized_bpy_image})

F4 alone supplies previously authorized and resolved bpy.types.Image objects.
No resolution logic, recursive texture search, or file IO occurs here.
The function always creates a NEW Blender material, even for repeated names,
and builds version-sensitive Principled sockets by name. Known bitmap maps
link through actual nodes. Glossiness maps invert with Math SUBTRACT.
Normals use Normal Map + Non-Color, alpha uses Alpha and a transparency
render method when available, high/invalid IOR is audited.
Ambiguous bump and transmap conventions are NOT linked without F6 evidence.
Different front/back BSDFs, procedural graphs, multilayer blends, and other
renderer features are explicitly reported as partial/lossy rather than faked.

F6 must attach the created material to object mesh slots only after resolving
native assignments and must aggregate BOTH planning and building diagnostics
into scene status/warnings. Rendering the neutral preview does not mean
successful material conversion.

## Validation commands (offline)

    python -m compileall -q source/maxblend_core/materials tests/materials
    python -m unittest discover -s tests/materials -p 'test_*.py' -v
    python -m unittest discover -s tests/baseline -v

If Blender 4.2+ is locally installed:

    blender --background --factory-startup --python tests/materials/blender_smoke.py

The optional Blender script uses in-memory, synthetic images only. Even if
every check passes, native .max material fidelity is unverified until Wave 2
wires F3 to the parser and tests authorized local scenes.

## Gate 1 follow-up test matrix (G1 issuecomment-6334980119)

Run from the latest F3 HEAD in a trusted full fork checkout containing
the real F0 interfaces (no shims). The optional P0 cross-repository test
requires a real schema path; otherwise unittest reports SKIP, not PASS.

```sh
PYTHONPATH=source python -m unittest discover -s tests/materials -p 'test_*.py' -v
python -m compileall -q source/maxblend_core/materials tests/materials
PYTHONPATH=source python -m unittest discover -s tests/baseline -v
MAXBLEND_P0_SCHEMA=/trusted/3dsmax-to-blender/schemas/scene-manifest-v1.schema.json \
  PYTHONPATH=source python -m unittest discover -s tests/materials -p 'test_*.py' -v
blender --background --factory-startup --disable-autoexec --python tests/materials/blender_smoke.py
```

The synthetic Blender test checks Base Color from an image, Alpha from
the same image's Alpha output, glossiness inversion through Math
SUBTRACT, a Normal Map with Non-Color bitmap, distinct materials sharing
names, missing-image diagnostics, IOR/coat/transmission socket values and
unknown material class warnings. No external image or MAX file is opened.

Even when F4 marks a texture found, F3 records shader_links_unverified
until a Blender node builder returns actual link evidence. P0 record
schema validation does not validate scene cross-references; P6 owns that.

Native Multi/Sub IDs (including gaps/nonzero IDs) remain diagnostic
references, not zero-based Blender polygon indices. F2/F6 must construct
the ordered slot map and map raw per-face native IDs to those indices.
P0 v1 has no native coat/transmission slots; F3 reports p0_extra_channel_loss and partial coverage whenever these fields are decoded.
