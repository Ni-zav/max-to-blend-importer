# Defensive native MAX container preflight (F5)

This module is **offline, read-only and independent of Blender**. It validates
CFB/OLE header fields, FAT/DIFAT/miniFAT and directory links, stream boundaries,
UTF-16 directory names, and framing of a recognizable `Scene` chunk stream. ZIP
wrappers and compressed native `Scene` streams are classified but deliberately
**unsupported**. No stream is extracted or decoded as a shader/scene script.

```python
from maxblend_core.container import DefensiveContainerProbe, ProbeLimits
report = DefensiveContainerProbe().probe_path(operator_approved_local_file)
# The caller MUST refuse all reports except status == 'partial' with
# kind == 'max_cfb', and must not infer parsing, version or fidelity success.
```

`DefensiveContainerProbe().probe(data, max_input_bytes=N)` satisfies the
Wave 0 `ContainerProbe` protocol and returns the F0 `ContainerReport`. For
more detailed metadata use `probe_detailed`, `probe_stream`, or `probe_path`.
The report deliberately contains no private file paths. The path-taking entry
point does **not** authorize which files a caller may read; the UI/integrator
must enforce its own file authorization and symlink/race policy.

Default limits: 2 GiB input; 32,768 FAT sectors; 32,768 directory slots;
2,000,000 sector-chain elements; 1 GiB per stream; 250,000 chunks; depth 48;
4,000,000 deterministic inspection steps; 256 ZIP members; 512 MiB aggregate
ZIP output metadata; 100:1 compression ratio. `max_input_bytes` is an
additional per-call ceiling (never expands the configured limit).
For locally trusted *large* work, explicitly call
`ProbeLimits().with_overrides(acknowledge_risk=True, ...)`. Do not raise
limits automatically from scene metadata or remote input. Higher limits
increase memory, CPU and denial-of-service exposure. `decompress_limited` is a
separate bounded helper, not used to allow compressed native scenes into the
legacy parser. Byte-count metrics are reads, not deduplicated source coverage.

Important limitations:
- CFB major version 3/4 is **not** the 3ds Max product release. Native MAX
  release detection remains unknown; do not assume newer compressed variants
  are supported. `partial` means *preflight structurally acceptable*, **not**
  successful native import.
- No full semantic MAX format verification, password/encryption support, native
  export, or certified safe sandbox is provided. The legacy importer is still
  vulnerable until F6 gates its execution; even a passing preflight is not a
  substitute for process resource limits and careful scene import handling.
- Header/stream evidence is heuristic: at least `Scene` and
  `ClassDirectory3` or `DllDirectory` to classify MAX-like CFB. A malicious
  impostor could mimic these streams; subsequent parser sandboxing matters.
- Chunk validation follows the existing upstream 6/14-byte frame model;
  unknown payload semantics are opaque and may be legitimately unsupported.

**F6 integration port:** At the existing `_dispatch_scene_import()` entrypoint
in `source/import_max.py`, run preflight **before** constructing
`ImportMaxFile`, and reject `failed`, `unsupported`, or any kind other than
`max_cfb`. Convert diagnostics to safe UI messages (no source paths). Wire
`partial` as "preflight eligible" only; never as import success. This port
change is reserved for F6 and is intentionally not made here.

Tests: `PYTHONPATH=source python -m unittest discover -s tests/container -v`.
Synthetic CFB tests are format-structural only; **actual native MAX scene import
is untested** until a redistributable fixture and Blender environment exist.
SPDX: GPL-2.0-or-later; retains upstream FreeCAD/olefile provenance in the
unchanged legacy importer.