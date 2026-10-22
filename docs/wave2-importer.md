# F6 — Wave 2 guarded importer integration

SPDX-License-Identifier: GPL-2.0-or-later

Status: integration candidate, **not** a certified .max conversion pipeline.

## What the fork actually does

1. The existing Blender 4.2+ File > Import operator import_scene.max selects a local MAX file. A POSIX descriptor-relative no-follow open checks a regular file and F5 probes its CFB container before any legacy MAX parser executes. A bounded (128 MiB) immutable snapshot is preflighted again and passed as bytes to the legacy parser, avoiding reopening the source path.
2. The chunk dispatcher enforces 48 levels, 250,000 decoded chunks and valid frame boundaries before recursive chunk creation. Compressed native scenes and unsupported CFB/ZIP wrappers fail closed; a passed CFB structural preflight is **not** validated native MAX semantics.
3. F2 reconstructs decoded Editable Mesh and Editable Poly topology and complete indexed UV-map payloads, preserving raw per-face MAX material IDs. It will not invent a native Multi/Sub material-ID to Blender slot mapping.
4. F3 translates a restricted set of legacy decoded Standard, Physical, V-Ray and Corona parameter values to explicit preview Principled nodes; coverage for unknown renderer material graphs is partial. F4 locates images **only** when the user explicitly approves a local texture folder. No search over arbitrary absolute native paths, no automatic external download or cloud conversion.
5. F1 checks finite affine transforms and composes hierarchies by stable document-local node indices; physical source units, axes, pivot-offset semantics and evaluated modifiers remain independently unverified. F7 validates decoded graph hints and reports unverified camera, light, layers and animation semantics instead of fabricating data. F8 validates and plans source-index geometry references, reusing Blender mesh data only where material override uncertainty allows.
6. Results are stored locally on the active scene at maxblend_last_import_report as JSON schema maxblend.import/v1, with success|partial|failed|unsupported status, created-object/material/link counts, and path-free trusted warning codes. These are counts created by this importer, **not** original MAX scene-fidelity claims. Native MAX export is always false.

## Critical limitations and independent I0 gates

- There is no redistributable approved native MAX file fixture in CI. **Real native .max import, baseline parity on genuine scenes, measurements against 3ds Max, full camera/light/animation support and material fidelity are NOT TESTED.** Blender-built synthetic scene and bounded F5 CFB probes cannot establish native conversion fidelity.
- Strict secure-open relies on POSIX O_NOFOLLOW and O_DIRECTORY. This implementation fails closed on Windows (SECURE_OPEN_UNAVAILABLE) instead of claiming an unimplemented secure Windows descriptor path. An independently tested native Windows safe-open capability is required before a Windows release.
- The upstream manifest ID io_scene_max and operator ID import_scene.max remain unchanged for Wave 0 backwards-compatibility assertions. **This extension cannot be enabled alongside the official io_scene_max extension.** A separately reviewed namespaced addon/registration migration and conditional compatibility alias is required for official-first and fork-first coexistence.
- MAX system units and source axes are not independently decoded and verified. F1 cannot manufacture normalization; displayed geometry sizes and world bounds must be independently checked before reporting physical correctness.
- Native per-face Multi/Sub IDs are never assumed to be zero-based Blender indices; final slot assignment requires a vetted native ID -> ordered F3 material-slot mapping. Renderer graph fidelity, UV variants, texture color-space rules and source image integrity need further validation.
- An F5-eligible CFB header is not proof of a safe hostile input. Python and Blender can still crash or stall during legacy scene parsing or approved image decoding. Separate-process isolation, timeouts/resource constraints, memory and CPU budgets, and further parser-level fuzzing are release requirements.
- This report is **not** the frozen strict P0 maxblend.scene/v1 manifest. P6 must separately validate and derive any v1 object/material provenance from verified decoder evidence. Camera/light physical fields, actual animation keys, layer state and instance identity need a separately reviewed versioned schema, not invented additional v1 fields.
- No export_scene.max registration or supported native MAX writer exists.

## Local validation and CI

Commands, run from repository root:

    python -m compileall -q source tests
    for suite in baseline transforms geometry materials textures container scene_nodes instances integration; do
      PYTHONPATH=source python -m unittest discover -s tests/$suite -p 'test_*.py' -v
    done
    blender --command extension build --source-dir=source --output-dir=dist
    blender --command extension validate dist/io_scene_max-1.9.2.zip
    blender --background --factory-startup --disable-autoexec --python-exit-code 1 --python tests/baseline/blender_smoke.py
    blender --background --factory-startup --disable-autoexec --python-exit-code 1 --python tests/materials/blender_smoke.py
    blender --background --factory-startup --disable-autoexec --python-exit-code 1 --python tests/integration/blender_smoke.py

The above deterministic synthetic suites, extension build and Blender 4.2 smoke tests are in .github/workflows/wave2-integration.yml. CI downloads an official verified Blender binary solely in the CI build environment; the installed importer makes no runtime network call.

No customer MAX file, texture, image, screenshot, source path, object name or metadata may be uploaded to the public fork, public PR, issue, CI, CI artifact, logs or external service.

## P6 handoff

P6 should pin this fork's exact verified commit, invoke import_scene.max only if this fork owns that operator, inspect the local MAXBLEND scene report after the invocation in the *same Blender host process*, and combine F6 partial/unsupported outcomes with P1/P2/P3/P7 downstream diagnostics. P6 must not treat maxblend.import/v1 as the strict maxblend.scene/v1 interchange schema. A verified semantic manifest adapter, safe process isolation and F1 units/geometry measurements are independent P6/I0 release gates.

Upstream provenance: Sebastian Schrand, Jens M. Plonka and Philippe Lagadec retain their original source notices. The Blender extension manifest retains its GPL-3.0-or-later license declaration; core source SPDX remains GPL-2.0-or-later.