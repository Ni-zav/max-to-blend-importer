# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Strict offline read-only preflight for untrusted native MAX containers.

CFB structure validation is NOT full MAX semantic validation. No dynamic
imports, file extraction, embedded scripts, or external network calls.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import io
import os
import struct
import zipfile
from typing import BinaryIO

from ..interfaces import ContainerReport, Diagnostic
from .chunks import UnsafeContainer, validate_chunks

MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
END = 0xFFFFFFFE
FREE = 0xFFFFFFFF
FAT = 0xFFFFFFFD
DIFAT = 0xFFFFFFFC
SPECIAL = {END, FREE, FAT, DIFAT}


@dataclass(frozen=True)
class ProbeLimits:
    """Defaults intended for workstation archviz; increase only deliberately.

    An override requires explicit acknowledgement via with_overrides().
    CPU limits are deterministic operation counters, not wall-time guarantees.
    """
    max_input_bytes: int = 2 * 1024**3
    max_fat_sectors: int = 32768
    max_dir_entries: int = 32768
    max_chain_sectors: int = 2_000_000
    max_stream_bytes: int = 1024**3
    max_chunk_nodes: int = 250_000
    max_chunk_depth: int = 48
    max_steps: int = 4_000_000
    max_zip_entries: int = 256
    max_decompressed_bytes: int = 512 * 1024**2
    max_decompression_ratio: int = 100

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in vars(self).values()):
            raise ValueError("all limits must be positive integers")

    def with_overrides(self, *, acknowledge_risk: bool = False, **changes: int) -> 'ProbeLimits':
        if not acknowledge_risk:
            raise ValueError("operator must acknowledge elevated memory/CPU risk")
        return replace(self, **changes)


@dataclass(frozen=True)
class ProbeSummary:
    kind: str  # max_cfb, generic_cfb, zip_wrapped_candidate, zip_archive, unknown
    status: str  # success|partial|failed|unsupported (preflight != import success)
    bytes_examined: int
    diagnostics: tuple[Diagnostic, ...]
    cfb_version: int | None = None  # OLE container version, NOT a 3ds Max release
    max_version: str | None = None  # None unless independently evidenced
    stream_names: tuple[str, ...] = ()
    chunk_count: int | None = None

    def to_report(self) -> ContainerReport:
        return ContainerReport(self.status, self.bytes_examined, self.diagnostics)


class _Budget:
    def __init__(self, limit: int):
        self.limit = limit
        self.steps = 0
        self.bytes_examined = 0

    def spend(self, n: int = 1):
        self.steps += n
        if self.steps > self.limit:
            raise UnsafeContainer("inspection CPU budget exceeded")


class _CFB:
    def __init__(self, fp: BinaryIO, size: int, limits: ProbeLimits, budget: _Budget):
        self.fp, self.size, self.limits, self.budget = fp, size, limits, budget
        self.sector_size = 0
        self.sectors = 0
        self.fat: list[int] = []
        self.claimed: set[int] = set()

    def read(self, at: int, size: int) -> bytes:
        self.budget.spend()
        if at < 0 or size < 0 or at > self.size or size > self.size - at:
            raise UnsafeContainer("read outside CFB file")
        self.fp.seek(at)
        raw = self.fp.read(size)
        self.budget.bytes_examined += len(raw)
        if len(raw) != size:
            raise UnsafeContainer("short sector/stream read")
        return raw

    def sector(self, sid: int) -> bytes:
        self._sector_id(sid)
        return self.read((sid + 1) * self.sector_size, self.sector_size)

    def _sector_id(self, sid: int):
        if sid in SPECIAL or sid < 0 or sid >= self.sectors:
            raise UnsafeContainer("out-of-range or reserved sector reference")

    def chain(self, start: int, expected: int | None, *, label: str,
              table: list[int] | None = None, claim: bool = True,
              max_items: int | None = None) -> list[int]:
        fat = self.fat if table is None else table
        if start == END and expected == 0:
            return []
        current = start
        found: list[int] = []
        seen: set[int] = set()
        while current != END:
            self.budget.spend()
            if current in SPECIAL or current < 0 or current >= len(fat):
                raise UnsafeContainer("bad " + label + " allocation reference")
            if current in seen:
                raise UnsafeContainer(label + " allocation cycle")
            if len(found) >= min(self.limits.max_chain_sectors,
                                 max_items if max_items is not None else self.limits.max_chain_sectors):
                raise UnsafeContainer(label + " allocation length budget exceeded")
            seen.add(current)
            found.append(current)
            if claim:
                self._sector_id(current)
                if current in self.claimed:
                    raise UnsafeContainer("overlapping sector allocations")
                self.claimed.add(current)
            if expected is not None and len(found) > expected:
                raise UnsafeContainer(label + " chain longer than declared size")
            current = fat[current]
        if expected is not None and len(found) != expected:
            raise UnsafeContainer(label + " chain shorter than declared size")
        return found

    def inspect(self) -> ProbeSummary:
        b = self.read(0, 512)
        if b[:8] != MAGIC:
            raise UnsafeContainer("invalid CFB magic")
        minor, major, order, sector_shift, mini_shift = struct.unpack_from("<HHHHH", b, 24)
        if order != 0xFFFE or (major, sector_shift) not in ((3, 9), (4, 12)):
            raise UnsafeContainer("unsupported/inconsistent CFB header version")
        if mini_shift != 6 or any(b[34:40]) or any(b[8:24]):
            raise UnsafeContainer("invalid CFB header fields")
        self.sector_size = 1 << sector_shift
        if self.size % self.sector_size or self.size < 2 * self.sector_size:
            raise UnsafeContainer("truncated or misaligned CFB sectors")
        self.sectors = self.size // self.sector_size - 1
        dir_sectors, fat_count, first_dir, _, cutoff, first_mini, mini_count, first_difat, difat_count = struct.unpack_from("<9I", b, 40)
        if cutoff != 4096 or (major == 3 and dir_sectors != 0):
            raise UnsafeContainer("invalid CFB directory/mini-stream header")
        if not fat_count or fat_count > self.limits.max_fat_sectors or fat_count > self.sectors:
            raise UnsafeContainer("FAT sector count outside budget")
        if mini_count > self.limits.max_chain_sectors or difat_count > self.sectors:
            raise UnsafeContainer("miniFAT/DIFAT count outside budget")
        # A DIFAT sector contributes (sector_words - 1) FAT indices.
        expected_difat = max(0, (fat_count - 109 + (self.sector_size//4 - 2)) //
                              (self.sector_size//4 - 1))
        if difat_count != expected_difat:
            raise UnsafeContainer("DIFAT count does not match FAT count")
        if (mini_count == 0) != (first_mini == END):
            raise UnsafeContainer("inconsistent miniFAT header")
        if (difat_count == 0) != (first_difat == END):
            raise UnsafeContainer("inconsistent DIFAT header")
        entries = list(struct.unpack_from("<109I", b, 76))
        difat_ids = []
        if difat_count:
            d = first_difat
            for _ in range(difat_count):
                self._sector_id(d)
                if d in difat_ids:
                    raise UnsafeContainer("DIFAT cycle")
                difat_ids.append(d)
                words = struct.unpack("<%dI" % (self.sector_size // 4), self.sector(d))
                entries.extend(words[:-1])
                d = words[-1]
            if d != END:
                raise UnsafeContainer("DIFAT chain longer than header declares")
        fat_ids = [x for x in entries if x != FREE]
        if len(fat_ids) != fat_count or len(set(fat_ids)) != fat_count:
            raise UnsafeContainer("duplicate or inconsistent FAT sector list")
        if set(fat_ids) & set(difat_ids):
            raise UnsafeContainer("overlapping FAT and DIFAT sectors")
        if any(x in SPECIAL or x >= self.sectors for x in fat_ids):
            raise UnsafeContainer("invalid FAT sector ID")
        self.fat = []
        for sid in fat_ids:
            self.fat.extend(struct.unpack("<%dI" % (self.sector_size // 4), self.sector(sid)))
        if len(self.fat) < self.sectors:
            raise UnsafeContainer("FAT too short for physical file")
        if any(self.fat[sid] != FAT for sid in fat_ids) or any(self.fat[sid] != DIFAT for sid in difat_ids):
            raise UnsafeContainer("FAT/DIFAT sector tag mismatch")
        self.claimed.update(fat_ids)
        self.claimed.update(difat_ids)
        max_dir_sectors = self.limits.max_dir_entries * 128 // self.sector_size
        if major == 4 and dir_sectors > max_dir_sectors:
            raise UnsafeContainer("too many directory records")
        dirs = self.chain(first_dir, dir_sectors if major == 4 else None,
                          label="directory", max_items=max_dir_sectors)
        raw_dir = b"".join(self.sector(x) for x in dirs)
        if not raw_dir:
            raise UnsafeContainer("missing CFB directory")
        records = []
        for at in range(0, len(raw_dir), 128):
            entry = raw_dir[at:at+128]
            name_len = struct.unpack_from("<H", entry, 64)[0]
            typ = entry[66]
            left, right, child = struct.unpack_from("<III", entry, 68)
            start = struct.unpack_from("<I", entry, 116)[0]
            size = struct.unpack_from("<Q", entry, 120)[0]
            if typ not in (0, 1, 2, 5):
                raise UnsafeContainer("invalid directory entry type")
            if typ:
                if name_len < 2 or name_len > 64 or name_len % 2 or entry[name_len-2:name_len] != b"\0\0":
                    raise UnsafeContainer("invalid directory name length/terminator")
                try:
                    name = entry[:name_len-2].decode("utf-16-le", "strict")
                except UnicodeError as exc:
                    raise UnsafeContainer("malformed UTF-16 directory name") from exc
                if "\0" in name or not name:
                    raise UnsafeContainer("invalid directory name content")
                if major == 3 and size >> 32:
                    raise UnsafeContainer("v3 directory stream length overflow")
            else:
                # Empty CFB directory slots are commonly all-zero padding.
                # Their link fields are not meaningful until a slot is active.
                name = ""
            records.append((typ, name, left, right, child, start, size))
        if records[0][0] != 5 or any(r[0] == 5 for r in records[1:]):
            raise UnsafeContainer("missing or duplicate root directory")
        # Validate reachable sibling/storage tree without recursive Python calls.
        seen = {0}
        todo = [(records[0][4], 1)]
        while todo:
            self.budget.spend()
            sid, depth = todo.pop()
            if sid == FREE:
                continue
            if sid >= len(records) or records[sid][0] == 0:
                raise UnsafeContainer("invalid directory tree reference")
            if sid in seen:
                raise UnsafeContainer("directory reference cycle/alias")
            if depth > 128:
                raise UnsafeContainer("directory nesting budget exceeded")
            seen.add(sid)
            typ, _, left, right, child, _, _ = records[sid]
            if typ == 2 and child != FREE:
                raise UnsafeContainer("stream has directory children")
            todo.extend(((left, depth+1), (right, depth+1), (child, depth+1)))
        if any(r[0] and sid not in seen for sid, r in enumerate(records)):
            raise UnsafeContainer("orphaned active directory entry")
        root_size = records[0][6]
        if root_size > self.limits.max_stream_bytes:
            raise UnsafeContainer("root mini stream exceeds budget")
        root_chain = self.chain(records[0][5], (root_size + self.sector_size-1)//self.sector_size,
                                label="root mini stream")
        mini_fat: list[int] = []
        # MiniFAT entries cannot address beyond the root mini stream;
        # bound metadata allocation before fetching or unpacking sectors.
        maxi = (root_size + 63) // 64
        max_minifat_sectors = (maxi*4 + self.sector_size - 1) // self.sector_size
        if mini_count > max_minifat_sectors:
            raise UnsafeContainer("miniFAT count exceeds root mini stream")
        if mini_count:
            mc = self.chain(first_mini, mini_count, label="miniFAT")
            for sid in mc:
                mini_fat.extend(struct.unpack("<%dI" % (self.sector_size//4), self.sector(sid)))
        mini_seen: set[int] = set()
        names = []
        chunks = 0
        compressed = False
        for typ, name, _, _, _, start, length in records[1:]:
            if typ != 2:
                continue
            names.append(name)
            if length > self.limits.max_stream_bytes:
                raise UnsafeContainer("CFB stream size exceeds budget")
            if length == 0:
                if start not in (END, FREE):
                    raise UnsafeContainer("nonempty allocation for zero-length stream")
                continue
            if length < cutoff:
                if root_size == 0 or not mini_fat:
                    raise UnsafeContainer("mini stream missing miniFAT/root storage")
                mini_chain = self.chain(start, (length+63)//64, label="mini stream", table=mini_fat, claim=False)
                for sid in mini_chain:
                    if sid in mini_seen or sid*64 >= root_size:
                        raise UnsafeContainer("invalid/overlapping mini stream sector")
                    mini_seen.add(sid)
                def read_at(at: int, n: int, sect=mini_chain):
                    if at < 0 or n < 0 or at+n > length:
                        raise UnsafeContainer("read outside mini stream")
                    out = bytearray()
                    while n:
                        index, sub = divmod(at, 64)
                        root_at = sect[index]*64 + sub
                        root_idx, root_sub = divmod(root_at, self.sector_size)
                        take = min(n, 64-sub)
                        out.extend(self.read((root_chain[root_idx]+1)*self.sector_size+root_sub, take))
                        at += take
                        n -= take
                    return bytes(out)
            else:
                chain = self.chain(start, (length+self.sector_size-1)//self.sector_size, label="stream")
                def read_at(at: int, n: int, sect=chain):
                    if at < 0 or n < 0 or at+n > length:
                        raise UnsafeContainer("read outside CFB stream")
                    out = bytearray()
                    while n:
                        index, sub = divmod(at, self.sector_size)
                        take = min(n, self.sector_size-sub)
                        out.extend(self.read((sect[index]+1)*self.sector_size+sub, take))
                        at += take
                        n -= take
                    return bytes(out)
            if name.lower() == "scene":
                if length < 6:
                    raise UnsafeContainer("truncated MAX Scene stream")
                prefix = read_at(0, 6)
                if prefix[:2] == b"\x1f\x8b" or prefix[:2] in (b"\x78\x9c", b"\x78\xda"):
                    compressed = True
                else:
                    chunks += validate_chunks(read_at, length,
                                              max_nodes=self.limits.max_chunk_nodes - chunks,
                                              max_depth=self.limits.max_chunk_depth,
                                              max_steps=self.limits.max_steps - self.budget.steps)
        recognized = any(n.lower() == "scene" for n in names) and any(
            n.lower() in ("classdirectory3", "dlldirectory") for n in names)
        kind = "max_cfb" if recognized else "generic_cfb"
        if compressed and recognized:
            return ProbeSummary("compressed_max_unsupported", "unsupported", self.budget.bytes_examined,
                (Diagnostic("MAX_COMPRESSED_UNSUPPORTED", "Compressed Scene stream: legacy framing/version not independently verified; do not import", "warning", status="unsupported"),), major, None, tuple(names), None)
        if not recognized:
            return ProbeSummary(kind, "unsupported", self.budget.bytes_examined,
                (Diagnostic("NOT_CONFIRMED_MAX", "Valid CFB structure without required MAX stream evidence", "warning", status="unsupported"),), major, None, tuple(names), chunks)
        return ProbeSummary(kind, "partial", self.budget.bytes_examined,
            (Diagnostic("MAX_PREFLIGHT_ONLY", "CFB/chunk bounds validated; MAX release and scene semantics unverified", "info"),),
            major, None, tuple(names), chunks)


class DefensiveContainerProbe:
    """Implements F0 ContainerProbe; `probe_detailed` adds safe classification."""
    def __init__(self, limits: ProbeLimits | None = None):
        self.limits = limits or ProbeLimits()

    def probe(self, data: bytes, *, max_input_bytes: int) -> ContainerReport:
        return self.probe_detailed(data, max_input_bytes=max_input_bytes).to_report()

    def probe_detailed(self, data: bytes, *, max_input_bytes: int | None = None) -> ProbeSummary:
        if not isinstance(data, bytes):
            raise TypeError("preflight expects bytes, not a file path")
        return self.probe_stream(io.BytesIO(data), max_input_bytes=max_input_bytes)

    def probe_path(self, path: os.PathLike[str] | str, *, max_input_bytes: int | None = None) -> ProbeSummary:
        # Open read-only, no extraction. Caller owns path authorization and TOCTOU policy.
        with open(path, "rb") as fp:
            return self.probe_stream(fp, max_input_bytes=max_input_bytes)

    def probe_stream(self, fp: BinaryIO, *, max_input_bytes: int | None = None) -> ProbeSummary:
        cap = self.limits.max_input_bytes
        if max_input_bytes is not None:
            if type(max_input_bytes) is not int or max_input_bytes <= 0:
                raise ValueError("max_input_bytes must be a positive integer")
            cap = min(cap, max_input_bytes)
        budget = _Budget(self.limits.max_steps)
        try:
            fp.seek(0, os.SEEK_END)
            size = fp.tell()
            if size > cap:
                raise UnsafeContainer("input exceeds configured byte budget")
            if size < 8:
                raise UnsafeContainer("truncated or unknown container header")
            fp.seek(0)
            prefix = fp.read(8)
            budget.bytes_examined += len(prefix)
            if prefix == MAGIC:
                return _CFB(fp, size, self.limits, budget).inspect()
            if prefix[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
                return self._inspect_zip(fp, budget)
            return ProbeSummary("unknown", "unsupported", budget.bytes_examined,
                (Diagnostic("NOT_MAX_CONTAINER", "No CFB or ZIP signature", "warning", status="unsupported"),))
        except Exception as exc:
            # No file paths, attacker-controlled names or private data in diagnostics.
            # Never catch BaseException (including MemoryError, KeyboardInterrupt).
            kind = ("malformed_cfb" if 'prefix' in locals() and prefix == MAGIC else
                    "malformed_zip" if 'prefix' in locals() and prefix[:2] == b"PK" else "unknown")
            return ProbeSummary(kind, "failed", budget.bytes_examined,
                (Diagnostic("CONTAINER_REJECTED", str(exc) if isinstance(exc, UnsafeContainer)
                            else "Malformed or unreadable container", "error", status="failed"),))

    def _inspect_zip(self, fp: BinaryIO, budget: _Budget) -> ProbeSummary:
        # Bound central-directory allocations BEFORE calling zipfile.ZipFile.
        fp.seek(0, os.SEEK_END)
        length = fp.tell()
        if length > self.limits.max_input_bytes:
            raise UnsafeContainer("ZIP size exceeds input budget")
        tail_size = min(length, 65557)
        fp.seek(length - tail_size)
        tail = fp.read(tail_size)
        budget.bytes_examined += len(tail)
        offset = tail.rfind(b"PK\x05\x06")
        if offset < 0 or len(tail) - offset < 22:
            raise UnsafeContainer("ZIP end-of-central-directory not found")
        _, disk, cdir_disk, disk_count, count, cdir_size, cdir_at, comment_size = struct.unpack_from(
            "<IHHHHIIH", tail, offset)
        if (disk or cdir_disk or disk_count != count or count == 0xffff or
                cdir_size == 0xffffffff or cdir_at == 0xffffffff):
            raise UnsafeContainer("multidisk/ZIP64 archive not supported")
        if count > self.limits.max_zip_entries or cdir_size > 16*1024**2:
            raise UnsafeContainer("ZIP directory count/size budget exceeded")
        if cdir_at + cdir_size > length or offset + 22 + comment_size != len(tail):
            raise UnsafeContainer("malformed ZIP central-directory offsets")
        fp.seek(0)
        with zipfile.ZipFile(fp, "r") as zf:
            entries = zf.infolist()
            if len(entries) > self.limits.max_zip_entries:
                raise UnsafeContainer("ZIP entry count exceeds budget")
            total = 0
            candidate = False
            for item in entries:
                budget.spend()
                name = item.filename.replace("\\", "/")
                parts = name.split("/")
                if (name.startswith("/") or ":" in parts[0] or any(x in ("..", "") for x in parts[:-1])
                        or ".." in parts or "." in parts or "\0" in name or item.flag_bits & 0x1):
                    raise UnsafeContainer("unsafe ZIP path/encrypted entry")
                if item.file_size > self.limits.max_decompressed_bytes:
                    raise UnsafeContainer("ZIP member exceeds output budget")
                total += item.file_size
                if total > self.limits.max_decompressed_bytes:
                    raise UnsafeContainer("ZIP aggregate size exceeds output budget")
                if item.file_size and (item.compress_size == 0 or
                    item.file_size > item.compress_size * self.limits.max_decompression_ratio):
                    raise UnsafeContainer("ZIP expansion ratio exceeds budget")
                if not item.is_dir() and name.lower().endswith(".max") and not candidate:
                    # zipfile verifies paths through metadata only; never extract.
                    # Short reads via ZipExtFile can still decompress significant data;
                    # byte/ratio caps above bound exposure but do NOT prove safety.
                    with zf.open(item) as member:
                        candidate = candidate or member.read(8) == MAGIC
                        budget.bytes_examined += min(8, item.file_size)
            return ProbeSummary("zip_wrapped_candidate" if candidate else "zip_archive", "unsupported",
                budget.bytes_examined,
                (Diagnostic("ZIP_NOT_NATIVE_MAX", "ZIP wrapper is not supported by the native OLE reader; member never parsed as MAX", "warning", status="unsupported"),))