<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# R1 synthetic gate tests

From repository root, with Python standard library only:

    python -m compileall -q research/native_max_writer tests/native_writer
    python -m unittest discover -s tests/native_writer -v

These tests use only synthetic evidence claims and an explicit mathematical one-triangle fixture target. They check deterministic claim digests, malformed labels, path-like input rejection, self-parser exclusion, declared target versions, consumer independence, sequencing, all-pass manual review and no-export defaults.

**They DO NOT test MAX serialization, CFB writer bytes, malicious native input parsing, independent reader acceptance, Blender export integration or any 3ds Max release.** The no-go report records these as NOT RUN. Even a synthetic all-pass gate verdict keeps native_export_enabled false.

No Blender/Autodesk runtime, external library, network connection, user .max file, texture or customer metadata is required.
