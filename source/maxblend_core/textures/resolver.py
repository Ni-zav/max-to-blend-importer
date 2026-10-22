# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded, offline bitmap discovery; no Blender, MAX, or network dependencies.

Never serialize ``resolved_path``/``tile_paths`` or log exception strings:
these are confidential local filesystem capabilities, not manifest fields.
``manifest_record`` is INTERNAL-ONLY and is not a P0 scene/v1 record.
Use ``project_texture_v1`` for the exact P0 wire shape; do not log it publicly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import os
from pathlib import Path
import re
import stat
from typing import Mapping

from ..interfaces import Diagnostic, TextureReference, TextureResolution

_UDIM = re.compile(r"<UDIM>|%\(UDIM\)d|\$\{UDIM\}|\$UDIM", re.IGNORECASE)
_DRIVE = re.compile(r"^[A-Za-z]:")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_IMAGE_SUFFIXES = frozenset((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".bmp", ".webp", ".gif", ".tga", ".hdr", ".dds"))
_COLOR = frozenset(("base_color", "basecolor", "diffuse", "albedo", "color", "emission", "emissive", "emission_color", "specular_color"))
_DATA = frozenset(("normal", "normalmap", "bump", "roughness", "diffuse_roughness", "metallic", "metalness", "displacement", "height", "opacity", "alpha", "transparency", "glossiness", "gloss", "shininess", "specular_ior", "specular_level", "ao", "ambient_occlusion"))
_ALIASES = {"bitmap": "base_color", "bitmap_color": "base_color", "diffusemap": "base_color", "base_color.shader": "base_color", "shinmap": "roughness", "normalmap_texture": "normal", "transmap": "opacity", "glossmap": "specular_color"}


def classify_channel(slot: str | None, overrides: Mapping[str, str] | None = None) -> tuple[str | None, str, tuple[Diagnostic, ...]]:
    """Use the *connecting socket*, not an image filename, to determine color space.

    Glossiness is not roughness; its inversion is a separate shader operation.
    Legacy ``glossmap`` may be specular tint, so it is kept distinct.
    """
    key = (slot or "").strip().casefold().replace(" ", "_")
    channel = _ALIASES.get(key, key) or None
    if overrides and key in overrides:
        choice = overrides[key]
        if choice not in ("color", "data", "unknown"):
            raise ValueError("Color-space override must be color, data or unknown")
        return channel, choice, ()
    if channel in _COLOR:
        return channel, "color", ()
    if channel in _DATA:
        extra = ((Diagnostic("GLOSS_INVERSION", "Glossiness is not roughness; shading needs an explicit inversion", "warning", "slot semantics"),)
                 if channel in ("glossiness", "gloss") else ())
        return channel, "data", extra
    return channel, "unknown", (Diagnostic("UNKNOWN_TEXTURE_ROLE", "No verified color-space role for this socket", "warning", "socket semantics"),)


def _diagnostic(code: str, message: str, *, severity: str = "warning") -> Diagnostic:
    # Only constant messages. No filenames, raw graph values or OS errors.
    return Diagnostic(code, message, severity, evidence="local bitmap resolver")


def _reference_components(source: str, allow_absolute_basename: bool = False) -> tuple[tuple[str, ...] | None, bool, str | None]:
    if not isinstance(source, str) or len(source) > 2048 or not source:
        return None, False, "INVALID_REFERENCE"
    try:
        source.encode("utf-8", "strict")
    except UnicodeError:
        return None, False, "INVALID_UNICODE"
    if _CONTROL.search(source) or "~" == source[:1] or "${" in source.replace("${UDIM}", ""):
        return None, False, "INVALID_REFERENCE"
    normalized = source.replace("\\", "/")
    # Never trust foreign absolute roots or URLs as authorization. A caller can
    # explicitly opt into *basename-only* recovery inside approved roots.
    absolute = bool(_DRIVE.match(normalized) or normalized.startswith("/") or "://" in normalized)
    if absolute:
        if not allow_absolute_basename:
            return None, True, "ABSOLUTE_REFERENCE"
        normalized = normalized.rsplit("/", 1)[-1]
    parts = tuple(normalized.split("/"))
    if not parts or any(p in ("", ".", "..") for p in parts):
        return None, absolute, "PATH_TRAVERSAL"
    # Disallow wildcard shells and zip-entry syntax, even if not expanded by us.
    if any(any(t in p for t in ("*", "?", "[", "]", "!", "|", ":")) for p in parts):
        return None, absolute, "UNSAFE_PATTERN"
    tokenized = _UDIM.sub("1001", parts[-1])
    if _UDIM.search("/".join(parts[:-1])) or "<" in tokenized or ">" in tokenized or "$" in tokenized or "%" in tokenized:
        return None, absolute, "UNSAFE_PATTERN"
    if Path(tokenized).suffix.casefold() not in _IMAGE_SUFFIXES:
        return None, absolute, "NON_IMAGE_REFERENCE"
    if _UDIM.findall(parts[-1]) and len(_UDIM.findall(parts[-1])) != 1:
        return None, absolute, "INVALID_UDIM"
    return parts, absolute, None


def _looks_like_image(header: bytes, suffix: str) -> bool:
    # Signature/structure check, not a full decoder or proof of image validity.
    if suffix == ".png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix in (".jpg", ".jpeg"):
        return header.startswith(b"\xff\xd8\xff")
    if suffix in (".tif", ".tiff"):
        return header.startswith((b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"))
    if suffix == ".exr":
        return header.startswith(b"\x76\x2f\x31\x01")
    if suffix == ".bmp":
        return header.startswith(b"BM")
    if suffix == ".gif":
        return header.startswith((b"GIF87a", b"GIF89a"))
    if suffix == ".webp":
        return header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    if suffix == ".dds":
        return header.startswith(b"DDS ")
    if suffix == ".hdr":
        return header.startswith((b"#?RADIANCE", b"#?RGBE"))
    if suffix == ".tga":
        return (len(header) >= 18 and header[1] in (0, 1) and header[2] in (1, 2, 3, 9, 10, 11)
                and int.from_bytes(header[12:14], "little") > 0 and int.from_bytes(header[14:16], "little") > 0)
    return False


@dataclass(frozen=True)
class ResolutionDetail:
    state: str
    reference: str  # normalized relative reference (never a raw absolute path)
    channel: str | None
    color_space_role: str
    sha256: str | None = None
    resolved_path: str | None = field(default=None, repr=False, compare=False)
    tile_paths: tuple[tuple[int, str], ...] = field(default=(), repr=False, compare=False)
    tile_hashes: tuple[tuple[int, str], ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    def contract_resolution(self) -> TextureResolution:
        return TextureResolution(self.state, self.resolved_path, self.diagnostics)

    def internal_diagnostic_record(self) -> dict[str, object]:
        """Local F4 investigation record, NOT the P0 schema or a public log."""
        # Filenames and hashes can themselves be private project metadata.
        return {"reference": self.reference, "path_state": self.state,
                "channel": self.channel, "color_space_role": self.color_space_role,
                "sha256": self.sha256, "udim_tiles": [{"tile": t, "sha256": digest} for t, digest in self.tile_hashes],
                "warnings": [d.code for d in self.diagnostics]}

    def manifest_record(self) -> dict[str, object]:
        """Compatibility alias: INTERNAL-ONLY; never treat as P0 v1 JSON."""
        return self.internal_diagnostic_record()


class SafeTextureResolver:
    """Default-deny resolver with bounded direct lookup inside explicit roots.

    No recursive directory walk/glob, script evaluation, image decoder, API or
    telemetry. Roots are never inferred from raw source paths or Blender state.
    """
    def __init__(self, approved_roots: tuple[str | Path, ...] = (), *,
                 allow_absolute_basename: bool = False, max_roots: int = 16,
                 max_file_bytes: int = 512 * 1024 * 1024, max_udim_tiles: int = 128,
                 role_overrides: Mapping[str, str] | None = None):
        if not (1 <= max_roots <= 64 and 1 <= max_file_bytes <= 2**32 and 1 <= max_udim_tiles <= 999):
            raise ValueError("Invalid resolver limits")
        if len(approved_roots) > max_roots:
            raise ValueError("Too many approved roots")
        self.roots = tuple(Path(root) for root in approved_roots)
        self.allow_absolute_basename = allow_absolute_basename
        self.max_roots = max_roots
        self.max_file_bytes = max_file_bytes
        self.max_udim_tiles = max_udim_tiles
        self.role_overrides = dict(role_overrides or {})

    def resolve(self, reference: TextureReference, *, approved_root: str | None = None) -> TextureResolution:
        return self.resolve_detailed(reference.reference, slot=reference.channel,
                                     approved_root=approved_root,
                                     role=reference.color_space_role).contract_resolution()

    def resolve_detailed(self, source: str, *, slot: str | None = None,
                         approved_root: str | None = None,
                         role: str | None = None) -> ResolutionDetail:
        channel, inferred_role, role_diags = classify_channel(slot, self.role_overrides)
        if role is not None and role != "unknown":
            if role not in ("color", "data"):
                raise ValueError("Invalid color-space role")
            inferred_role = role
        parts, was_absolute, error = _reference_components(source, self.allow_absolute_basename)
        safe_name = parts[-1] if parts else ""  # never include rejected raw path
        if error:
            return ResolutionDetail("blocked", safe_name, channel, inferred_role, diagnostics=role_diags +
                                    (_diagnostic(error, "Bitmap reference rejected by path policy"),))
        assert parts is not None
        if was_absolute:
            role_diags += (_diagnostic("BASENAME_RECOVERY", "Absolute source reference reduced to basename by explicit policy"),)
        root_list = (Path(approved_root),) if approved_root is not None else self.roots
        if not root_list or len(root_list) > self.max_roots:
            return ResolutionDetail("blocked", parts[-1], channel, inferred_role,
                                    diagnostics=role_diags + (_diagnostic("NO_APPROVED_ROOT", "An explicit approved local root is required"),))
        is_udim = bool(_UDIM.search(parts[-1]))
        ids = range(1001, 2000) if is_udim else (None,)
        records: dict[int | None, dict[str, tuple[str, str]]] = {}
        blocked = False
        for root in root_list:
            if not root.is_dir() or root.is_symlink():
                blocked = True
                continue
            for tile in ids:
                name = _UDIM.sub(str(tile), parts[-1]) if tile is not None else parts[-1]
                current = parts[:-1] + (name,)
                try:
                    asset = self._fingerprint(root, current)
                except FileNotFoundError:
                    continue
                except (OSError, ValueError):
                    blocked = True
                    continue
                if asset is None:
                    blocked = True
                    continue
                digest, private_path = asset
                # Dedupe by file contents, not a filename or root spelling.
                records.setdefault(tile, {}).setdefault(digest, (digest, private_path))
                if len(records) > self.max_udim_tiles:
                    return ResolutionDetail("blocked", parts[-1], channel, inferred_role,
                                            diagnostics=role_diags + (_diagnostic("UDIM_LIMIT", "UDIM tile limit exceeded"),))
        if any(len(fingerprints) > 1 for fingerprints in records.values()):
            return ResolutionDetail("ambiguous", parts[-1], channel, inferred_role,
                                    diagnostics=role_diags + (_diagnostic("HASH_COLLISION", "Distinct content matches the same requested texture"),))
        if not records:
            state = "blocked" if blocked else "missing"
            code = "BLOCKED_CANDIDATE" if blocked else "MISSING_TEXTURE"
            return ResolutionDetail(state, parts[-1], channel, inferred_role,
                                    diagnostics=role_diags + (_diagnostic(code, "No authorized decodable image header was identified"),))
        if blocked:
            return ResolutionDetail("blocked", parts[-1], channel, inferred_role,
                                    diagnostics=role_diags + (_diagnostic("INCOMPLETE_SEARCH", "An approved location could not be safely checked"),))
        if is_udim:
            if 1001 not in records:
                role_diags += (_diagnostic("UDIM_1001_MISSING", "UDIM sequence has no 1001 tile; it may be incomplete"),)
            if len(records) < 2:
                role_diags += (_diagnostic("UDIM_SINGLE_TILE", "Only one UDIM tile was found"),)
        # SHA256 stable across root ordering; for UDIM include tile identities.
        tiles = tuple(sorted((t, next(iter(values.values()))) for t, values in records.items() if t is not None))
        if is_udim:
            digest = sha256(";".join(f"{tile}:{value[0]}" for tile, value in tiles).encode("ascii")).hexdigest()
            tile_hashes = tuple((tile, value[0]) for tile, value in tiles)
            tile_paths = tuple((tile, value[1]) for tile, value in tiles)
            path = None
        else:
            digest, path = next(iter(records[None].values()))
            tile_hashes = ()
            tile_paths = ()
        return ResolutionDetail("found", "/".join(parts), channel, inferred_role,
                                digest, path, tile_paths, tile_hashes, role_diags)

    def _fingerprint(self, root: Path, parts: tuple[str, ...]) -> tuple[str, str] | None:
        """Open via no-follow directory FDs on POSIX; check and fail closed elsewhere.

        On Windows, where directory FDs may be unavailable, the fallback checks
        resolved confinement and links before/after opening. Windows directory
        swaps remain a documented race; integration should avoid attacker-writable
        roots when using the portable fallback.
        """
        # Do not resolve the approved root before a no-follow open: that could
        # silently follow an attacker-replaced root link.
        root = Path(os.path.abspath(root))
        if os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY"):
            fds = []
            try:
                fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                fds.append(fd)
                for component in parts[:-1]:
                    fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    fds.append(fd)
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0), dir_fd=fd)
                fds.append(fd)
                return self._hash_opened(fd, Path(parts[-1]).suffix.casefold(), str(root.joinpath(*parts)))
            finally:
                for fd in reversed(fds):
                    os.close(fd)
        target = root.joinpath(*parts)
        cur = root
        for part in parts:
            cur = cur / part
            if cur.is_symlink():
                raise OSError("Symlink prohibited")
        if not target.resolve(strict=True).is_relative_to(root):
            raise OSError("Path outside approved root")
        with target.open("rb") as handle:
            value = self._hash_opened(handle.fileno(), Path(parts[-1]).suffix.casefold(), str(target))
            if cur.is_symlink() or not target.resolve(strict=True).is_relative_to(root):
                raise OSError("Path changed")
            return value

    def _hash_opened(self, fd: int, suffix: str, private_path: str) -> tuple[str, str] | None:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > self.max_file_bytes:
            return None
        with os.fdopen(os.dup(fd), "rb") as stream:
            header = stream.read(32)
            if not _looks_like_image(header, suffix):
                return None
            stream.seek(0)
            checksum = sha256()
            count = 0
            while True:
                block = stream.read(min(1024 * 1024, self.max_file_bytes - count + 1))
                if not block:
                    break
                count += len(block)
                if count > self.max_file_bytes:
                    return None
                checksum.update(block)
        return checksum.hexdigest(), private_path
