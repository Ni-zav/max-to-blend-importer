# F4 texture resolution (Wave 1)

This subtree is **an isolated, offline Python module**, not a wired importer fix.
It must not be advertised as repairing `get_bitmap()`, `get_texmap()`, or
`load_image()` until Wave 2 F6 integrates it and real Blender import tests pass.

## Interface / integration port (F6 owns importer wiring)

1. In `source/import_max.py`, adapt `get_bitmap()` and `get_texmap()` at the
   source chunk decoding boundary to **validated plain mappings** of the shape
   `{"class": "VRayBitmap", "filename": "relative/asset.png"}` (similarly
   `CoronaBitmap`, regular `Bitmap`, and nested `{"class": "ColorCorrection",
   "input": {...}}`). Parse the legacy bitmap GUID `0x240`, the documented
   upstream VRayBitmap GUID `0x2c1017d6769144b`, and verified metadata/pathlink
   references before handing strings to F4. The binary chunk decoding and
   Corona class-ID discovery are **not** implemented here. Don't guess indexes
   in an undocumented serialized class or execute MAX scene expressions.
2. For each known material socket/slot call `extract_bitmap_sources(graph,
   slot="base_color")` or `resolve_graph(graph, resolver, slot=...)`. The
   supplied slot is authoritative: filename heuristics are intentionally absent.
   Wrapper traversal discovers candidates only: color-correction, mix, falloff
   and normal/bump shader transforms still require F3 semantics and must retain
   a **partial/approximation** warning.
3. Construct `SafeTextureResolver(approved_roots=(project_root, explicitly_
   approved_asset_root), role_overrides={...})`. Do not automatically include
   the process working directory, OS-wide libraries, or host/network paths.
   Absolute source references are blocked. Optional
   `allow_absolute_basename=True` **only** searches the last basename inside
   the approved roots; it never accesses the original absolute location.
4. Replace the unsafe `load_image(..., recursive=search)` call with a
   non-recursive load of **only** a `found` result's private `resolved_path`.
   For UDIM, use the explicit `tile_paths` after checking completeness; don't
   pass the raw untrusted source path into Blender's recursive finder. Let F3
   attach images and set color spaces based on `color_space_role`, not texture
   extension or filename. Handle `ambiguous`, `blocked`, `missing` as visible
   partial failures, never silently substitute by filename.
5. The `TextureResolver.resolve(TextureReference, approved_root=...)` F0
   protocol is implemented. `TextureReference.reference` is already sanitized
   by contract; F6 must call `resolve_detailed(raw_source, slot=...)` **before**
   treating raw MAX paths as safe references. `ResolutionDetail.resolved_path`
   and `tile_paths` are internal-only. `manifest_record()` is a compatibility
   alias of `internal_diagnostic_record()`; both are **internal-only F4**
   diagnostics, NOT P0 wire JSON and NOT public logs. Use
   `project_texture_v1` for frozen P0 texture records after the
   caller independently supplies stable ID and provenance. Never print exception
   details, path objects, parsed source path text, filenames or customer names
   to public logs/CI.

## Semantics and limits

- Standard, V-Ray and Corona bitmap *normalized graph records* are supported;
  actual binary wrapper extraction is pending F6 and not independently proved.
- No scripts, network operations, directory recursion, filename-based
  guessing, image decoding, or Autodesk SDK/licensing is needed.
- Direct lookup only. If a texture exists in an unrelated nested directory,
  explicitly approve that directory (or provide its relative path).
- UDIM `<UDIM>`, `%(UDIM)d`, `${UDIM}` or `$UDIM`: finite probes of 1001–1999
  and a configurable matched-tile count cap. A lone tile or missing 1001 is
  reported as potentially incomplete, not fabricated as verified fidelity.
- Readable PNG/JPEG/TIFF/EXR/BMP/GIF/WEBP/TGA/HDR/DDS headers are recognized,
  but not fully decoded; headers and hashes **do not** prove a valid image.
- POSIX no-follow dirfd traversal rejects symlink escapes and file swapping.
  On Windows, path confinement is checked before/after opening, but hostile
  concurrent directory replacement remains a TOCTOU risk: approve directories
  that untrusted users cannot alter while conversion is running.
- The current implementation opens/reads each matched candidate to hash it.
  Input files are size-limited; however, many large UDIM candidates may take
  considerable I/O, so integrators should apply an overall job time/I/O budget.
- Original upstream GPL code and notice files are unchanged.

## Offline test command

```sh
python -m unittest discover -s tests/textures -v
python -m compileall -q source/maxblend_core/textures tests/textures
```

These synthetic fixture checks do **not** establish actual 3ds Max or Blender
conversion fidelity. No native `.max` export feature is provided.

## Strict P0 `maxblend.scene/v1` texture item projection (G1 handoff)

`from maxblend_core.textures import project_texture_v1` is a standalone
Blender-free adapter function. On a locally authorized `ResolutionDetail`:

```python
record = project_texture_v1(
    detail,
    stable_id="texture:trusted-native-0001",     # F6-owned deterministic identity
    provenance_method="native",                 # verified F6 source knowledge
    provenance_evidence="verified_metadata_link", # path-free token, optional
)
```

The returned JSON item has **exactly** these eight P0 keys (frozen platform
schema blob `976b084ba6b357756872911bdb3de483cd8cff51`):
`id`, `source_ref`, `path_status`, `channel`, `color_space_role`,
`sha256`, `provenance`, `warnings`. Tests pin P0's exact texture-item
JSON-schema slice under `tests/textures/fixtures/`. No change to P0 or F0.

**Exact mapping** for F6/P6: `ResolutionDetail.state -> path_status`,
`channel -> channel`, `color_space_role -> color_space_role`,
`sha256 -> sha256` only if status is `found` and hash syntax is verified
(other states yield null), `diagnostics -> warnings[]` with
`code,severity,reason,evidence,attribute,before,after` (all seven required
fields). Warning reasons are **fixed trusted descriptions**, never arbitrary
`Diagnostic.message/evidence` strings or local paths. F6 must supply stable
manifest `id` tied to validated source semantics (never a guessed basename or
process memory ID), plus `provenance.method` and optional path-free evidence
token. `source_ref` is **null by default**; for an authorized private/local
manifest, `publish_basename=True` exposes only revalidated sanitized
basename, never original absolute path, parent directories or a client path.
No public-facing log should contain the returned record if hashes, IDs or
basenames are confidential; redact by policy at the logging boundary.

Color-space mismatch against a known socket is explicitly warned, never
silently corrected. `missing`, `blocked` and `ambiguous` remain their
literal states and do not expose a verified digest. UDIM tile paths and
tile hashes are internal F4 sidecars (the strict P0 texture item has no
`udim_tiles` field). F6 should keep a private sidecar or pursue a separately
reviewed schema version if that information must cross the P6 wire boundary.
No renderer shader graph or native binary extraction is claimed.

### G1 commands and independent test boundary

```sh
PYTHONPATH=source python -m unittest discover -s tests/textures -v
python -m compileall -q source/maxblend_core/textures tests/textures
PYTHONPATH=source python -m unittest discover -s tests/baseline -v
```

The fork root CI still tests `tests/baseline` only. G1 or a CI owner must
run `tests/textures` on a complete checkout at the exact PR HEAD before merge.
This component does **not** need a Blender-dependent node smoke test; F3/F6
own Blender material application and native MAX loading respectively.
