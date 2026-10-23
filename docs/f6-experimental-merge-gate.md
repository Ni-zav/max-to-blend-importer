# F6 experimental merge qualification — NOT a native-MAX release

SPDX-License-Identifier: GPL-2.0-or-later

**Disposition sought:** Independent I0 authorization may permit merging F6 **only as disabled-by-default experimental source code**, with no public native MAX fidelity, parser security, packaged-runtime, or production-converter claims. This document is a proposed gate, not approval or authorization to merge.

## Installation and parser permission matrix

| Distribution / caller | Installation | Native parser | Classification |
| --- | --- | --- | --- |
| Built Blender 4.2 ZIP | Build, validate, install and register | **DENIED**, even with explicit acknowledgment: installed ZIP cannot attest clean Git source | Packaging/UX smoke only, **not** functional installation |
| Ordinary Linux Blender from reviewed Git checkout | Register | **DENIED** by default, before source file is opened or parser launched | Default safe state |
| Linux Blender from reviewed **clean Git checkout**, per-call `experimental_ack=True` | Register | Permitted through a bounded separate Blender child for *authorized trusted input in a disposable VM* only | **Experimental preview**, not safe for hostile input |
| Dirty/untracked/Git-less checkout, Windows/macOS, missing limits | May register | **DENIED**, no in-process fallback | Unsupported |
| P6 release converter / normal unattended production / untrusted client MAX | Not qualified | **DENIED by policy**; no production activation | **NO-GO** |

The code enforces a clean Git checkout and explicit per-operation acknowledgment in `isolated_import()`, not just in the UI. The operator warns users and defaults `experimental_ack=False` with `SKIP_SAVE` to avoid silently saving consent in presets. An installed ZIP cannot obtain an approved commit from a caller-supplied SHA or self-declared ZIP metadata.

This opt-in is a declaration of risk, not proof an input file is benign or an environment is securely confined. A script already executing arbitrary Python in Blender is trusted code and can bypass addon controls; neither Python consent flags nor rlimits are an OS security boundary.

## Parser isolation status and threat model

Current child provides **resource limits, not a security sandbox**:

- Linux only, `--background --factory-startup --disable-autoexec`, limited inherited environment, private request/response files.
- `RLIMIT_AS=8 GiB`, `RLIMIT_CPU=20s/22s`, `RLIMIT_FSIZE=32 MiB`, `RLIMIT_CORE=0`, 30-second parent walltime; bounded JSON replay validation and rollback.
- **Not implemented/verified:** seccomp allowlist, network namespace, user/mount/PID namespace, filesystem restrictions beyond staging, AppArmor/SELinux, privilege drop, network denial, fork/exec escape prevention, hostile semantic fuzzing or native-code RCE resistance.
- **Untrusted customer files must not be processed on ordinary user workstations or servers.** Controlled research should run in a disposable *externally isolated VM* with networking disabled, no mounted secrets, independent resource controls and minimal privileges.
- Python `preexec_fn` threading safety in Blender remains a risk to review before hardening claims.
- Synthetic geometry and invalid native header rejection are not measurements of genuine native MAX fidelity.

## I0 checklist for an *experimental source merge* only

- [ ] Independently inspect exact F6 HEAD/diff and verify default-deny controls.
- [ ] F6 Python/Blender 4.2 CI green: build+installed ZIP parser denial, no parser execution on missing acknowledgment, approved clean-checkout opt-in rejects invalid native input, official/fork co-registration and P0 partial canonical schema.
- [ ] P6 independently repins its **test-only** F6 candidate HEAD and reruns Blender contract. Production `APPROVED_F6_MERGE_SHA` stays `None` pending authorization.
- [ ] I0 explicitly records **EXPERIMENTAL MERGE GO** distinct from native MAX **RELEASE NO-GO**, with owner acceptance of restrictions.
- [ ] No customer MAX, textures, files, private paths, screenshots or derived identifying data uploaded.

If all are satisfied, an **authorized maintainer** may merge PR #12 as internal experimental source code. No release tag, distribution/publishing, default-on parser, conversion/fidelity/security claim or P6 production activation follows automatically. CI synthetic green alone does not establish signoff.

## Later production/fidelity certification gates: still NO-GO

1. **Installed ZIP build provenance:** reproducibly bind the ZIP digest to an approved reviewed commit using trusted signed release metadata or an external known digest; independently verify installed bytes at runtime and reject tampering, substitutions and repackaging. A Git SHA embedded in an archive is **not** attestation. Until then ZIP native import stays disabled; installed registration smoke is not a usable importer.
2. **Kernel-enforced parser containment:** independently test network denial, least-privilege filesystem/mounts, no executable code escape, bounded child tree, restricted syscalls, memory/CPU and adversarial parser behavior. A disposable VM alone does not establish safe default host behavior.
3. **Authorized genuine MAX test suite (private/local):** verify source units/axes/transforms, geometry/UV, native material Multi/Sub IDs, renderer graphs, instances/proxies, scene version behavior and source-to-Blender/export metrics. Synthetic Blender fixtures alone cannot certify fidelity.
4. **P6/P3 release integration:** approved merged SHA, attested same-host importer/converter, scene rollback, strict P0 partial handling, and explicit USD dependency packaging; never silently remove nonempty sidecars. No native MAX writer exists.

**Current decision: candidate for independent experimental merge review, NOT approved production installation, parser security or native MAX fidelity release.**
