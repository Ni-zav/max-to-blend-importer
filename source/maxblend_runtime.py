# SPDX-License-Identifier: GPL-2.0-or-later
"""F6 trusted, offline input gate and path-free import reporting.

A successful structural preflight is only permission to attempt the legacy
reader. It is not evidence of MAX semantic fidelity or a process sandbox.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import io
import os
from pathlib import Path
import stat

from maxblend_core.container import DefensiveContainerProbe, ProbeLimits


MAX_IMPORT_BYTES = 128 * 1024 * 1024


class ImportRejected(ValueError):
    """A bounded, deliberately path-free import rejection."""


@dataclass
class ImportReport:
    status: str = "unsupported"
    container: str = "unknown"
    objects_created: int = 0
    materials_created: int = 0
    textures_linked: int = 0
    warnings: list[str] = field(default_factory=list)

    def warn(self, code: str) -> None:
        # Only trusted internal diagnostic codes may be published.
        if isinstance(code, str) and code.isascii() and 0 < len(code) <= 80 and all(
                c.isupper() or c.isdigit() or c == "_" for c in code):
            if len(self.warnings) < 256 and code not in self.warnings:
                self.warnings.append(code)
        if self.status != "failed":
            self.status = "partial"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "maxblend.import/v1",
            "status": self.status,
            "container": self.container,
            "objects_created": self.objects_created,
            "materials_created": self.materials_created,
            "textures_linked": self.textures_linked,
            "warnings": tuple(self.warnings),
            "native_max_export": False,
            "source_units_verified": False,
        }


def _secure_open(path: str):
    """Open selected regular input by descriptor, no path-based parser reopen.

    Non-POSIX/no-O_NOFOLLOW platforms fail closed instead of claiming a
    symlink/TOCTOU guarantee they cannot implement.
    """
    if not (os.name == "posix" and hasattr(os, "O_NOFOLLOW")
            and hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NONBLOCK")):
        raise ImportRejected("SECURE_OPEN_UNAVAILABLE")
    if not isinstance(path, str) or not os.path.isabs(path):
        raise ImportRejected("INPUT_MUST_BE_ABSOLUTE")
    parts = Path(path).parts
    if any(part in (".", "..") for part in parts):
        raise ImportRejected("INPUT_TRAVERSAL_REJECTED")
    components = parts[1:]
    if not components:
        raise ImportRejected("INPUT_NOT_REGULAR")
    fd = os.open(os.sep, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in components[:-1]:
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        source_fd = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                            dir_fd=fd)
        return os.fdopen(source_fd, "rb")
    except (OSError, ValueError) as exc:
        raise ImportRejected("INPUT_OPEN_REJECTED") from None
    finally:
        os.close(fd)


def checked_bytes(path: str, *, max_bytes: int = MAX_IMPORT_BYTES):
    """Preflight and snapshot identical bytes; never hand parser a pathname."""
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_IMPORT_BYTES:
        raise ImportRejected("INVALID_IMPORT_BYTE_LIMIT")
    limits = ProbeLimits(max_input_bytes=max_bytes)
    try:
        with _secure_open(path) as fp:
            metadata = os.fstat(fp.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > max_bytes:
                raise ImportRejected("INPUT_LIMIT_OR_TYPE_REJECTED")
            result = DefensiveContainerProbe(limits).probe_stream(fp, max_input_bytes=max_bytes)
            if result.status != "partial" or result.kind != "max_cfb":
                raise ImportRejected("CONTAINER_UNSUPPORTED_OR_INVALID")
            fp.seek(0)
            data = fp.read(max_bytes + 1)
            if len(data) != metadata.st_size or len(data) > max_bytes:
                raise ImportRejected("INPUT_CHANGED_OR_TOO_LARGE")
            # Reject in-place mutation observed during the descriptor read.
            after = os.fstat(fp.fileno())
            if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                    metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns):
                raise ImportRejected("INPUT_CHANGED_DURING_SNAPSHOT")
            # Structural revalidation is on the immutable bytes passed to the parser.
            snapshot = DefensiveContainerProbe(limits).probe_detailed(data, max_input_bytes=max_bytes)
            if snapshot.status != "partial" or snapshot.kind != "max_cfb":
                raise ImportRejected("INPUT_PREFLIGHT_MISMATCH")
            return data, snapshot
    except ImportRejected:
        raise
    except (OSError, ValueError) as exc:
        raise ImportRejected("INPUT_READ_REJECTED") from None


def preflight_bytes(data: bytes, *, max_bytes: int = MAX_IMPORT_BYTES):
    """Synthetic/offline tests only; does not establish authorization to read a path."""
    if not isinstance(data, bytes) or len(data) > max_bytes:
        raise ImportRejected("INVALID_INPUT_BYTES")
    summary = DefensiveContainerProbe(ProbeLimits(max_input_bytes=max_bytes)).probe_detailed(
        data, max_input_bytes=max_bytes)
    if summary.status != "partial" or summary.kind != "max_cfb":
        raise ImportRejected("CONTAINER_UNSUPPORTED_OR_INVALID")
    return io.BytesIO(data), summary
