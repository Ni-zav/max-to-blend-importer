# F6 / I0 importer follow-up — security and P6 handoff

SPDX-License-Identifier: GPL-2.0-or-later

**Status: synthetic-tested integration candidate, NOT production release.**
No authorized redistributable genuine MAX binary fixture exists in public CI;
native MAX fidelity, source-unit conversion and renderer graph recovery are unverified.

## Namespace / supported host

- Blender 4.2+ extension ID: `maxblend_importer_fork`; version: `1.9.3`.
- Runtime operator: `bpy.ops.import_scene.maxblend`; file handler:
  `IO_FH_maxblend`. No `export_scene.max` and no native MAX writer.
- This fork **never registers** the old `import_scene.max` alias. That
  identifier belongs to the official `io_scene_max`. Legacy operator
  scripts must explicitly migrate to `maxblend`. Shared option/property
  names remain when meaningful; potentially unsafe legacy switches fail closed.
- Official-first and fork-first registration smoke tests verify both operator
  identifiers persist independently, and uninstalling the fork leaves the
  official namespace intact.
- Strict worker runs **only on Linux** with POSIX O_NOFOLLOW/openat,
  rlimit, process group cancellation. Windows and macOS fail closed.
  This is NOT an OS namespace, seccomp or VM sandbox: advanced adversarial
  isolation remains an independent I0 requirement.

## Architecture / process isolation

1. The interactive Blender operator prepares a strict, private, mode-0600
   request and launches a separate factory-startup Blender process.
   Command uses argv, no shell, `--disable-autoexec`, `--python-exit-code 1`,
   no user startup script directories and no required network service.
2. Child Linux process has `RLIMIT_AS=8 GiB`, `RLIMIT_CPU=20s`
   (hard 22s), `RLIMIT_FSIZE=32 MiB`, `RLIMIT_CORE=0`. Parent enforces
   a 30-second wall-time, kills the entire process group on expiry and
   accepts only exit code zero.
3. Inside child, F5 structurally preflights an approved no-follow regular
   local file and parses identical immutable input bytes (max 128 MiB)
   using bounded legacy chunks. This is **not** semantic proof of a valid
   native MAX. Compressed/unsupported containers are rejected.
4. Only validated mesh coordinates, per-face topology, UV loops, opaque
   document-local source-node IDs, parent relationships and finite Blender
   world matrices are transferred through a separate max-24-MiB private
   JSON payload. Each result is capped at 512 objects, 200k vertices,
   300k faces, 600k loops. The parent revalidates schema, limits, finite
   matrices, face indices, duplicate IDs and parent cycles before constructing
   fresh Blender mesh datablocks. It never loads a Blender scene file from
   the child, registers client scripts or trusts child Blender code.
5. Native bitmap decoding, renderer-specific materials, animations, cameras,
   external proxies and source scripts are **not replayed** into the parent.
   No native texture path is used. Raw face MAX material IDs may be exposed
   only as an internal evidentiary sidecar; they are **not** zero-based
   Blender material slots.
6. On failure, worker nonzero/timeout/resource overrun always returns a
   path-free error with no successful import status. No client input or
   derived geometry is uploaded to public CI.

This is bounded resource isolation, not a proof against malicious parser
memory corruption, container escapes, kernel vulnerabilities, or operating
system attack surface. A disposable machine/VM and explicit trust boundary
remain appropriate for hostile inputs.

## Frozen P0 `maxblend.scene/v1` bridge

In the *same Blender process* after successful partial import:

```python
import bpy
# Blender Extensions installation path varies by configured repository.
# Resolve the enabled extension by the manifest ID, not the old operator.
import bl_ext.user_default.maxblend_importer_fork as addon
session = addon.get_last_import_session()
assert session is not None
scene = session.scene_manifest
object_map = session.objects_by_id
assert scene["schema_version"] == "maxblend.scene/v1"
assert scene["status"] == "partial"
assert scene["source"]["extension"] == "maxblend_importer_fork"
assert scene["source"]["version"] == "1.9.3"
assert scene["source"]["commit"] is not None  # clean checked-out HEAD
```

For P6, `session.resolve(node_id)` returns an actual `bpy.types.Object`
reference and not a serialized pointer. `objects_by_id` uses unique
`node_N` *document-local parsed scene-chunk indexes*, not Max's independently
authenticated permanent native object handles. The local parent receives
`source_sha256` computed from the exact verified input snapshot. Source
paths and private client object metadata are never printed to CI.

The canonical scene source identity now consists of the verified importer
extension ID `maxblend_importer_fork`, Python/manifest version `1.9.3`,
and the **actual clean Git HEAD** of the checked-out code that was imported.
`source.extension` is the **importer extension ID** and not the input file
suffix `.max`. `source.sha256` still refers to the verified input byte
snapshot and must not be confused with a source code checksum.

The F6 bridge obtains `source.commit` using `git rev-parse --verify HEAD^{commit}`
from the parent of the loaded `source/maxblend_bridge.py`, checks that the
Git top-level directory matches that source checkout, verifies Python and
Blender-manifest identities, and rejects dirty/untracked `source/**` paths.
A caller-provided SHA is an **expected pin to compare**, never a value to copy
into the manifest. A missing Git checkout, mismatched expected pin, dirty
checkout or manifest-version mismatch all cause an error and rollback.
A compiled ZIP-only extension **cannot** assert a trusted commit by reading
its own version string: it fails closed until an independently approved,
versioned release-build attestation mechanism is established. This strict
mechanism is appropriate for I0/P6's explicit, independently verified Git
checkout in Blender 4.2 CI and does not pretend that arbitrary local Git
metadata is a signed release. P6 must independently inspect and approve the
specific source checkout and require the same commit in its canonical receipt.
The reviewed candidate SHA must **not** populate P6's production-approved
*merge SHA* field until an independent, authorized merge.

The canonical scene item meets strict P0 v1 field requirements as a **partial
observational manifest**. It describes measured created Blender
object/mesh/face/triangle/UV counts with `provenance.method="derived"`
and bounded Scene record indexes. Because source physical units, source axis
convention, pivot and MAX shader mappings are unknown, `source_units`
is null, `axes` is unknown, physical world/local matrices and
`bounds_m` are null, and `face_material_ids` is null. The
`transforms.values_in_meters` v1 contract remains true because **no
unverified metric values are emitted**. This avoids relabeling assumed
Blender world coordinates as verified real-world meters. P6 must not
infer scene fidelity or native geometry placement from an object count.

The `maxblend.import/v1` scene custom property is a **separate**
operator status/report, not the strict scene manifest. The same host
also stores local `maxblend_scene_v1`, but P6 should prefer live session
references and separately validate the v1 schema before any export.

If a user closes/unregisters the extension, session references expire.
P6 must pin an exact trusted fork commit independently; the schema's
`source.commit` may remain null when the addon cannot attest its exact
installed repository commit. Never guess a SHA.

## Independently unverified native semantics / I0 gate

- No legally distributable native `.max` fixture and no independently
  measured Max-to-Blender dimensions, renderer material parity or version matrix.
- No authenticated source system units, native axis basis, per-face native
  Multi/Sub material-ID-to-slot table, advanced provenance, real camera/light
  parameter decoding, animation tracks, procedural modifiers or renderer proxies.
- F2/Blender synthesized geometry tests, F1 mirrored parent transforms,
  synthetic F3 shader-node smoke, official-first/fork-first registration,
  Linux worker timeout/resource tests, invalid container/replay tests,
  Blender 4.2 extension build and packaging are **tests of the implementation**
  and not genuine native MAX conversion verification.
- Worker subprocess uses POSIX resource limits but not a kernel syscall-deny
  sandbox. Harden with VM/seccomp/landlock, process monitoring and authorized
  genuine test cases before production security claims.
- P6 must implement trusted ConversionPort in the same owning Blender host,
  pin the merged fork SHA, incorporate F6 partial warnings into P1/P2 audit,
  refrain from repairs without independent evidence and validate later
  export reimports. Platform USD output packaging currently remains a
  separately reviewed problem; F6 does not alter platform export policy.
- Native MAX writing is neither implemented nor advertised.

## Regression commands

```sh
python -m compileall -q source tests
for suite in baseline transforms geometry materials textures container scene_nodes instances integration; do
  PYTHONPATH=source python -m unittest discover -s "tests/$suite" -p 'test_*.py' -v
done
blender --command extension build --source-dir=source --output-dir=dist
blender --command extension validate dist/maxblend_importer_fork-1.9.3.zip
blender --background --factory-startup --disable-autoexec --python-exit-code 1 --python tests/baseline/blender_smoke.py
blender --background --factory-startup --disable-autoexec --python-exit-code 1 --python tests/materials/blender_smoke.py
blender --background --factory-startup --disable-autoexec --python-exit-code 1 --python tests/integration/blender_smoke.py
blender --background --factory-startup --disable-autoexec --python-exit-code 1 --python tests/integration/blender_namespace_smoke.py
```

Upstream attribution and license: Sebastian Schrand, Jens M. Plonka,
Philippe Lagadec and their original code provenance remain in source
headers. The extension manifest declares GPL-3.0-or-later; the importer
source retains GPL-2.0-or-later. No customer MAX files, texture data,
screenshots or derived assets may be uploaded to public repositories or CI.
