<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# R1 — Native MAX Writer Research (Wave 2)

**Decision: NO-GO for native .max serialization.**

This subtree intentionally has **no writer, no .max output, no Blender operator registration, no payload fixtures, and no Autodesk runtime dependency**. See [NO_GO.md](NO_GO.md) for the observed read-side data, unresolved wire schemas, minimal synthetic target, source ledger and version compatibility matrix.

The stdlib-only [gate.py](gate.py) evaluates *fixed evidence verdicts* offline and fail-closed. Its SHA-256 digest covers **normalized test claims, not a MAX file, scene contents or authenticated evidence**. All-pass mock evidence still returns **manual_release_review_required**; it never enables export. It reads no external data, never executes scripts, and makes no network calls.

## Isolated validation

Run from repository root:

    python -m compileall -q research/native_max_writer tests/native_writer
    python -m unittest discover -s tests/native_writer -v

These are deterministic synthetic tests for evidence rejection, claim ordering, version/consumer identity, fail-closed decisions and a specified mathematical single-triangle reference.

**NOT RUN / blocked:** actual CFB or native MAX serialization, true hostile .max input parsing, third-party file open, authorized 3ds Max open/save, cross-version interoperability, Blender export UI integration. No redistributable known-good minimal native MAX corpus or independent native consumer trace was available to this R1 effort. Do not report missing tests as passed.

## Handoff to F6 / P6

**No integration port changes are authorized.** Do not wire this package into Blender File > Export, CLI, platform format support or extension manifest. Once format-level evidence, independent reader verification, and authorized native open/resave tests are available, submit a separate contract/interface review before even an opt-in experimental serializer is exposed. This no-go research is not a production-export PR and is not eligible for a production merge without independent gate review.

License: additive research under GPL-2.0-or-later. Existing upstream GPL notices and FreeCAD/olefile provenance remain unchanged.
