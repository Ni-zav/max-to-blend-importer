<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# R1 native MAX write feasibility: evidence ledger and NO-GO

Date: 2026-10-22. Verdict: **NO-GO for serialization or claiming usable native .max output**. The limitation is falsifiable: more public format evidence plus independently produced, lawfully redistributable minimal fixtures may permit a future strictly experimental serializer. Generic CFB container correctness alone does not guarantee a 3ds Max scene.

## Authority and inspected code

Read the frozen platform interchange-v1 contract, parallel-workstreams ownership, workstream-issues index, tracking issue #18, current importer fork main, merged Wave 1/F0 modules, baseline and F5 documentation, upstream licensing and importer implementation. The branch modifies only research/native_max_writer/** and tests/native_writer/**, leaving the existing importer, UI and packaging unchanged.

Read-side evidence was examined in source/import_max.py (ImportMaxFile, MaxStream, MaxFileDirEntry, ChunkReader, ClassIDChunk, DirectoryChunk, SceneChunk, read_chunks, read_class_directory, read_directory, get_references, get_node_parent, get_guid); source/maxblend_core/container/chunks.py and probe.py; and the upstream io_scene_max / FreeCAD Importer3D lineage. F5 performs bounded, **read-only** CFB and chunk preflight. A status of partial is not a successful scene import or native writing verdict. The legacy parser can contain separate unsafe pathways; R1 does not claim it is safe on arbitrary malicious files.

## What is actually understood, versus missing write semantics

| Layer | Read-side/public evidence | Missing necessary writer evidence |
| --- | --- | --- |
| Generic OLE / Compound File Binary | Microsoft's MS-CFB public specification defines magic, header, sector size, FAT/DIFAT, miniFAT, directory entries and streams. F5 validates some CFB v3/v4 structures with resource budgets. | No R1 CFB writer or independently opened output. Generic CFB acceptance says nothing about a native scene. CFB major version 3 or 4 is **not** a 3ds Max product release. |
| MAX-like stream inventory | Reader looks for Scene, ClassData, ClassDirectory3 or ClassDirectory, DllDirectory, Config and VideoPostQueue. | Per-release required stream set, defaults, ordering, cross-stream references and integrity dependencies are unknown. Guessing streams would fabricate compatibility. |
| Chunk envelope | ChunkReader recognizes a 6-byte little-endian <H,i> header, zero-sized extended 64-bit length, negative 32-bit container sizes. F5 validates bounded nesting/lengths. | Semantic payload definitions, required hierarchy, extended chunk encoding, compression and class-specific state are incomplete. A framed chunk is not necessarily valid to Max. |
| Class registry | Type 0x2042 encodes class-name data; class type 0x2060 unpacks as <IQI> (DLL index, class ID, superclass ID) in ClassDirectory3/ClassDirectory. DllDirectory resolves plugin references. | Stock and plugin class registry population, class index assignment, version-specific class serialization, and valid object instantiation rules unverified. |
| Scene graph | Reader recognizes 0x2034/0x2035 object references, 0x0960 parent reference and 0x0962 name. It recognizes selected Editable Mesh/Poly and material class IDs. | Correct scene root/controller topology, mandatory nodes, stable ID and reference allocation, material assignment, coordinates and native mesh buffer encodings not fully specified. |
| Versions/compression | Importer has special 0x8B1F / zlib handling for some streams; F5 deliberately classifies compressed native streams as unsupported. | No proven mapping from these markers to a release-specific native write schema; compression cannot be assumed universally accepted. |
| Legal/offline baseline | Microsoft's CFB is publicly specified. Existing importer is GPL-2.0-or-later-derived, with FreeCAD/olefile notices. | No proprietary Autodesk SDK/redistributables may be copied; no client reference scene, licensed Autodesk runtime, cloud conversion or paid API may be required in the normal path. |

**Important:** Another parser derived from the same importer lineage is not genuinely independent evidence. Reading what our own parser wrote, matching the signature, passing generic CFB format tests, or getting an F5 partial preflight result does not establish native compatibility. The separate .3ds interchange format is not proof of writing .max.

## Exact minimal candidate target — not a native wire schema

For any future lawful trial, use an independently generated synthetic scene with:

- Exactly one static triangle, local vertices in meters (0,0,0), (1,0,0), (0,1,0); winding (0,1,2); no UV, texture, animation or external linked assets.
- Exactly one mesh object, transform translation (2,3,4) meters, identity scale and rotation. Matrix convention: row-major, homogeneous column vectors. Expected world coordinates (2,3,4), (3,3,4), (2,4,4).
- Exactly one simple material with intended linear RGBA (0.8,0.2,0.1,1.0), assigned to the triangle. The actual native Max material class, gamma mapping and on-disk encoding are **unresolved**, so the target is not a serialization recipe.
- Independently measured object/vertex/face/material counts, winding, transform, world-space bounds and assigned material semantics. Numeric tolerances must be declared before testing for each supported field.
- No scripts or executable scene controllers, XRefs, proprietary plug-in dependency, asset paths, client files, photos, metadata or confidential identifiers.

Obtain a lawfully redistributable known-good native file from an **authorized synthetic** source, with exact release and fixture-generation recipe. Compare at least two variants to distinguish IDs, timestamps, offsets and hashes from true constants. Never publish client MAX files or derivatives. Since these references and native semantic schemas were not available, **no CFB payload or MAX writer was fabricated**.

## Falsifiable gates and actual execution

| Gate | Observed R1 status | What would unblock it |
| --- | --- | --- |
| Bounded CFB serialization / valid directory | **NOT RUN** | Implement only after researched stream schema, then require size/depth/count budgets, deterministic bytes and third-party CFB reader validation. |
| Native stream/class registry and scene chunk serialization | **NOT RUN** | Per-version class identifiers, references, non-executable payload semantics and complete required scene graph demonstrated from lawful references. |
| Writer robustness against malformed scene DTO/input | **NOT RUN — no writer** | Explicit immutable scene DTO, rejected NaN/nonfinite coordinates, oversized records, strings, missing objects, malicious payloads, and bounded allocation/CPU; fuzz independently. |
| Repeatability / candidate artifact digest | **NOT RUN — no candidate bytes** | Byte-for-byte identical output for identical synthetic input and actual candidate SHA-256; R1 gate hash is **only claim-data** hashing. |
| Independent native semantic reader acceptance | **NOT RUN** | Different implementation, non-shared parser lineage, measured triangle/material/transform semantics and fixed consumer/release. |
| Authorized native 3ds Max open, resave, reopen | **NOT RUN** | Authorized testing for a precisely named product release; preserve geometry/material invariants and report errors. Product-specific gates cannot be tested without a lawful installed Max instance. |
| Native version compatibility | **NOT RUN** | Test each claimed release; never infer support from CFB version, importer observations or file extensions. |
| Blender File > Export / CLI integration | **NOT IMPLEMENTED by design** | Prohibited before independent proof and reviewed contract/integration PR. |

The added standalone gate.py only rejects untrusted/unsupported **verdict labels** and produces a deterministic SHA-256 of normalized evidence claims. Tests are **synthetic**; they do not feed a hostile binary parser or certify a producer. Even manually supplied all-pass evidence returns manual_release_review_required and native_export_enabled=false. An independent non-native reader pass still needs authorized native validation for product compatibility. Such attestations are not digitally verified.

## Verified feature and version matrix

| Consumer / product | Native scene opened | Triangle mesh verified | Transform verified | Material verified | Save-and-reopen verified |
| --- | --- | --- | --- | --- | --- |
| Independent generic CFB reader | N/A (CFB-only) | N/A | N/A | N/A | N/A |
| Independent native .max reader | **NOT RUN** | **NOT RUN** | **NOT RUN** | **NOT RUN** | N/A |
| Autodesk 3ds Max 2010–2023, each individual release | **NOT RUN** | **NOT RUN** | **NOT RUN** | **NOT RUN** | **NOT RUN** |
| Autodesk 3ds Max 2024–2027, each individual release | **NOT RUN** | **NOT RUN** | **NOT RUN** | **NOT RUN** | **NOT RUN** |

The release ranges above group *untested candidates* for future research only. **Verified native compatibility: none.** No generation, opening, authorized native runtime test, cross-version test, or export-fidelity test was performed. No actual target output was created.

## Next research and F6/P6 integration decision

1. Establish lawful independent corpus provenance and version-tagged field mappings. No client assets or derived private metadata in the public fork, PRs, CI, screenshots or output.
2. Use F5's separate read-side bounded probe as one diagnostic input, not proof of a valid writer. Investigate required stream graph and native class metadata without executing scripts or shipping proprietary code.
3. Only after a documented semantic write contract exists, consider an offline deterministic, size/depth-limited research serializer under this exclusive subtree with no Blender hooks.
4. Have a different reader validate application semantics and a lawfully authorized native Max test machine open, inspect, resave and reopen a candidate. This is **test-only**, never a runtime end-user requirement. Report measured versions/features, failed and untested gates explicitly.
5. **F6/P6 integration port change needed now: NONE.** Keep File > Export, source/__init__.py, manifest and application CLI untouched. If a future independent gate passes, request a **separate reviewed contract amendment and importer integration PR** with clear status/feature flags; do not wire a writer from this branch.

## Public source references and licensing

- Microsoft MS-CFB published format: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/53989ce4-7b05-4f8d-829b-d08d6148375b
- Microsoft MS-CFB introduction: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/50708a61-81d9-49c8-ab9c-43c98a795242
- Autodesk scene file description: https://help.autodesk.com/cloudhelp/2025/ENU/MAXDEV-Developer/files/3ds_max_sdk_features/scenes_and_nodes/scene_file_max_file.html
- Autodesk MAX-specific compatibility: https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/What-file-formats-does-3ds-Max-import-and-export.html
- Upstream importer, GPL provenance: https://github.com/nrgsille76/io_scene_max/blob/main/source/import_max.py
- Original FreeCAD Importer3D MAX parser: https://github.com/jmplonka/Importer3D/blob/master/importMAX.py
- Fork F5 preflight: https://github.com/Ni-zav/max-to-blend-importer/blob/main/source/maxblend_core/container/README.md

All R1 additions are GPL-2.0-or-later; no upstream notice was modified, no proprietary Autodesk SDK binary was added, and no executable embedded scene code is parsed or evaluated here.
