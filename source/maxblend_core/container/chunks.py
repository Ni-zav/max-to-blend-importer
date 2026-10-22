# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded, non-evaluating MAX chunk framing checks; payloads stay opaque.

Framing matches upstream ChunkReader: <H,i> (size includes header), negative
32-bit sizes denote nested containers; size zero introduces a 64-bit size.
This module intentionally does not interpret arbitrary native class records.
"""
from __future__ import annotations

import struct
import zlib
from typing import Callable


class UnsafeContainer(ValueError):
    """Malformed framing, resource exhaustion, or unsupported encoding."""


def validate_chunks(read_at: Callable[[int, int], bytes], length: int, *,
                    max_nodes: int, max_depth: int, max_steps: int) -> int:
    """Validate chunk boundaries and nesting without allocating scene payloads.

    A read_at(offset, count) implementation MUST reject short reads. Unknown
    primitive types are intentionally skipped, never decoded or executed.
    """
    if min(length, max_nodes, max_depth, max_steps) < 0 or not max_nodes or not max_steps:
        raise UnsafeContainer("invalid chunk budget")
    count = steps = 0
    stack = [(0, length, 0)]
    while stack:
        start, end, depth = stack.pop()
        if depth > max_depth:
            raise UnsafeContainer("chunk nesting exceeds budget")
        at = start
        while at < end:
            steps += 1
            count += 1
            if steps > max_steps or count > max_nodes:
                raise UnsafeContainer("chunk count/CPU budget exceeded")
            if end - at < 6:
                raise UnsafeContainer("truncated chunk header")
            header = read_at(at, 6)
            if len(header) != 6:
                raise UnsafeContainer("short chunk header read")
            _, signed_size = struct.unpack("<Hi", header)
            is_container = signed_size < 0
            header_size = 6
            if signed_size == 0:
                if end - at < 14:
                    raise UnsafeContainer("truncated extended chunk header")
                extended = read_at(at + 6, 8)
                if len(extended) != 8:
                    raise UnsafeContainer("short extended chunk read")
                size = struct.unpack("<q", extended)[0]
                header_size = 14
            else:
                size = signed_size & 0x7FFFFFFF
            if size < header_size or size > end - at:
                raise UnsafeContainer("invalid or overflowing chunk length")
            next_at = at + size
            if is_container and size > header_size:
                if depth + 1 > max_depth:
                    raise UnsafeContainer("chunk nesting exceeds budget")
                # Resume siblings AFTER nested body; prevents recursive Python calls.
                stack.append((next_at, end, depth))
                start, end, depth = at + header_size, next_at, depth + 1
                at = start
            else:
                at = next_at
        if at != end:
            raise UnsafeContainer("chunk boundary mismatch")
    return count


def decompress_limited(data: bytes, *, max_output_bytes: int, max_ratio: int,
                       max_steps: int = 100_000) -> bytes:
    """Decode one gzip/zlib stream in bounded increments; never write to disk.

    For *already in-memory, operator-authorized* input only; no implicit use
    in preflight. Reject concatenated streams, trailing data and truncation.
    """
    if not data or min(max_output_bytes, max_ratio, max_steps) <= 0:
        raise UnsafeContainer("invalid decompression input/budget")
    dec = zlib.decompressobj(zlib.MAX_WBITS | 32)
    parts = []
    produced = 0
    offset = 0
    steps = 0
    try:
        while offset < len(data) or dec.unconsumed_tail:
            steps += 1
            if steps > max_steps:
                raise UnsafeContainer("decompression CPU budget exceeded")
            if dec.unconsumed_tail:
                block = dec.unconsumed_tail
            else:
                block = data[offset:offset + 65536]
                offset += len(block)
            remaining = min(max_output_bytes - produced,
                            len(data) * max_ratio - produced)
            # Request one extra byte to detect crossing the cap immediately.
            output = dec.decompress(block, remaining + 1)
            produced += len(output)
            if produced > max_output_bytes or produced > len(data) * max_ratio:
                raise UnsafeContainer("decompression size/ratio exceeded")
            parts.append(output)
            if dec.eof:
                if dec.unused_data or dec.unconsumed_tail or offset < len(data):
                    raise UnsafeContainer("trailing or concatenated compressed data")
                break
            if not block and not output:
                raise UnsafeContainer("decompression stalled")
        if not dec.eof:
            raise UnsafeContainer("truncated compressed stream")
        return b"".join(parts)
    except zlib.error as exc:
        raise UnsafeContainer("invalid compressed stream") from exc