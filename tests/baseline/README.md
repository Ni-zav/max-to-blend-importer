# Wave 0 baseline: provenance, limits, and reproducibility

This fork begins from upstream `nrgsille76/io_scene_max` commit
`37db107126f956f7219152671443080360565691` (2026-07-06).
At the fork baseline, both `main` refs and trees were identical.
The upstream addon identifies as `io_scene_max`, version `1.9.2`,
with Blender extension minimum `4.2.0`. Its parser is in the original
`source/import_max.py` (86,426 bytes at baseline). Preserve the original
SPDX notices (GPL-2.0-or-later) and the Blender manifest's
SPDX:GPL-3.0-or-later; upstream attributions remain intact.

## Run tests

- `python -m compileall -q source tests/baseline`
- `python -m unittest discover -s tests/baseline -v`
- `python tests/baseline/perf_probe.py` (header-only, no .max parser timing)
- `blender --command extension build --source-dir=source --output-dir=dist`
- `blender --command extension validate dist/io_scene_max-1.9.2.zip`
- `blender --command extension install-file --repo YOUR_LOCAL_REPO dist/io_scene_max-1.9.2.zip` (after `repo-add`)
- `blender --background --factory-startup --python tests/baseline/blender_smoke.py`

CI uses official Blender 4.2.0 Linux binaries for extension build and
headless registration smoke tests, plus isolated offline extension ZIP installation. The repository has no redistributable
legal native .max fixture, so full-scene import is **SKIPPED**, not passing.
Do not substitute confidential client scenes for CI fixtures.

## Known upstream behavior and gaps

- The public operator remains `bpy.ops.import_scene.max`, with unchanged
  option/property names and the same legacy default scene reader.
- `_dispatch_scene_import()` is the single explicit integration port;
  it only calls the unchanged `read_scene()`. The later F6 integrator must
  wire vetted planners at this port, maintaining fallback and regression
  coverage. There is no runtime discovery or dynamic plugin execution.
- `IO_FH_max.bl_export_operator` previously declared a **nonexistent**
  `export_scene.max` operator. The misleading declaration was removed;
  it never provided export implementation. No native MAX exporter exists.
- Existing import parsing can be unsafe on malicious CFB/chunk input
  (unbounded traversal/allocation, path resolution and decompression);
  F5 owns bounded container probing. Wave 0 DOES NOT harden the parser.
  Do not trust private/untrusted files or imply security certification.
- No fidelity measurements exist for transforms, mesh topology, materials,
  textures, cameras, animations, instancing or arbitrary MAX versions.
  Header recognition proves only an eight-byte signature, not validity.

## Side-by-side extension identity (future F6 decision)

Current manifest ID `io_scene_max` and operator ID `import_scene.max`
are preserved for strict compatibility. Two extensions using these same
identifiers cannot be installed/enabled concurrently without collision.

F6 should allocate a distinct manifest ID (for example
`maxblend_importer_fork`) and namespace the fork's operator/file-handler
IDs (for example `import_scene.maxblend`, `IO_FH_maxblend`) if true
side-by-side operation is required. That conflicts with the current
`import_scene.max` CLI entrypoint, so a backward-compatible compatibility
policy is required: only register an alias if unclaimed; make the platform
adapter select the distinct operator; test official-first and fork-first
registration. Never replace official classes silently. Do not rename IDs in
Wave 0: the manifest belongs to the F6 integrator, and this gate preserves
existing behavior.

## Reporting privacy

Synthetic probes contain no projects, paths or customer assets. Report
missing measurements as missing, never zero. Do not send real scene files,
textures, screenshots, logs containing source paths, or client identifiers
to GitHub issues, CI or PRs.
