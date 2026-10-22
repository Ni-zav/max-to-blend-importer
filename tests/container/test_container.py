# SPDX-FileCopyrightText: 2026 Contributors to max-to-blend-importer
# SPDX-License-Identifier: GPL-2.0-or-later
"""Deterministic synthetic CFB/ZIP tests. No client assets or real MAX fixtures."""
import io
import os
import random
import struct
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'source')))
from maxblend_core.container import (DefensiveContainerProbe, ProbeLimits,
                                     UnsafeContainer, decompress_limited, validate_chunks)
from maxblend_core.interfaces import ContainerReport

FREE = 0xFFFFFFFF
END = 0xFFFFFFFE
FAT = 0xFFFFFFFD
MAGIC = bytes.fromhex('d0cf11e0a1b11ae1')


def directory_entry(name, typ, *, left=FREE, right=FREE, child=FREE, start=END, size=0):
    out = bytearray(128)
    raw = (name + '\0').encode('utf-16-le')
    out[:len(raw)] = raw
    struct.pack_into('<HBBIII', out, 64, len(raw), typ, 1, left, right, child)
    struct.pack_into('<I', out, 116, start)
    struct.pack_into('<Q', out, 120, size)
    return bytes(out)


def valid_cfb(scene=None):
    # Four CFB sectors: dir, FAT, root mini stream, miniFAT. A deliberately
    # *synthetic*, structurally valid OLE file, not actual native MAX content.
    if scene is None:
        scene = struct.pack('<Hi', 0x1001, 64) + b'Q' * 58
    assert len(scene) == 64
    head = bytearray(512)
    head[:8] = MAGIC
    struct.pack_into('<HHHHH', head, 24, 0x003e, 3, 0xfffe, 9, 6)
    struct.pack_into('<9I', head, 40, 0, 1, 0, 0, 4096, 3, 1, END, 0)
    struct.pack_into('<109I', head, 76, 1, *([FREE] * 108))
    directory = (directory_entry('Root Entry', 5, child=1, start=2, size=128) +
                 directory_entry('Scene', 2, right=2, start=0, size=64) +
                 directory_entry('ClassDirectory3', 2, start=1, size=64))
    directory = directory.ljust(512, b'\0')
    fat_sector = struct.pack('<128I', END, FAT, END, END, *([FREE]*124))
    root_sector = (scene + b'K'*64).ljust(512, b'\0')
    mini_fat = struct.pack('<128I', END, END, *([FREE]*126))
    return bytes(head) + directory + fat_sector + root_sector + mini_fat


class TestCFB(unittest.TestCase):
    def setUp(self):
        self.probe = DefensiveContainerProbe()
        self.fixture = valid_cfb()

    def diagnostic(self, data):
        return self.probe.probe_detailed(data)

    def test_synthetic_cfbs_validate_not_parse(self):
        r = self.diagnostic(self.fixture)
        self.assertEqual((r.kind, r.status, r.chunk_count), ('max_cfb', 'partial', 1))
        self.assertIsNone(r.max_version)
        self.assertEqual(r.cfb_version, 3)
        self.assertEqual(r.stream_names, ('Scene', 'ClassDirectory3'))
        self.assertIsInstance(self.probe.probe(self.fixture, max_input_bytes=8192), ContainerReport)

    def test_input_budget(self):
        self.assertEqual(self.probe.probe(self.fixture, max_input_bytes=200).status, 'failed')
        with self.assertRaises(ValueError):
            self.probe.probe(self.fixture, max_input_bytes=0)

    def test_short_file_and_truncated_sector(self):
        for data in (b'', b'P', MAGIC, self.fixture[:512], self.fixture[:-1]):
            with self.subTest(size=len(data)):
                self.assertEqual(self.diagnostic(data).status, 'failed')

    def test_not_max(self):
        r = self.diagnostic(b'not a native MAX file')
        self.assertEqual((r.kind, r.status), ('unknown', 'unsupported'))

    def test_corrupt_header(self):
        for at, v in ((26, 9), (28, 0), (30, 12), (32, 9), (56, 0)):
            with self.subTest(at=at):
                data = bytearray(self.fixture)
                struct.pack_into('<H' if at < 40 else '<I', data, at, v)
                self.assertEqual(self.diagnostic(bytes(data)).status, 'failed')

    def test_bad_fat_and_cycle(self):
        for fat_item in (2, 0xffffffff, 99999):
            data = bytearray(self.fixture)
            struct.pack_into('<I', data, 1024+2*4, fat_item)
            self.assertEqual(self.diagnostic(bytes(data)).status, 'failed')

    def test_corrupted_fat_header_links(self):
        for pos, val in ((76, 7777), (76, 0), (44, 999999), (68, 1)):
            with self.subTest(pos=pos):
                data = bytearray(self.fixture)
                struct.pack_into('<I', data, pos, val)
                self.assertEqual(self.diagnostic(bytes(data)).status, 'failed')

    def test_directory_cycle(self):
        data = bytearray(self.fixture)
        struct.pack_into('<I', data, 512+128+72, 1)  # Scene right sibling -> itself
        self.assertEqual(self.diagnostic(bytes(data)).status, 'failed')

    def test_bad_directory_reference(self):
        data = bytearray(self.fixture)
        struct.pack_into('<I', data, 512+128+72, 200)
        self.assertEqual(self.diagnostic(bytes(data)).status, 'failed')

    def test_malformed_unicode(self):
        data = bytearray(self.fixture)
        data[512+128:512+128+2] = b'\x00\xd8'  # lone UTF-16 high surrogate
        self.assertEqual(self.diagnostic(bytes(data)).status, 'failed')

    def test_metadata_length_overflow(self):
        data = bytearray(self.fixture)
        struct.pack_into('<Q', data, 512+128+120, (1<<63))
        self.assertEqual(self.diagnostic(bytes(data)).status, 'failed')

    def test_zero_length_scene_section(self):
        data = bytearray(self.fixture)
        struct.pack_into('<Q', data, 512+128+120, 0)
        struct.pack_into('<I', data, 512+128+116, END)
        result = self.diagnostic(bytes(data))
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.chunk_count, 0)

    def test_difat_metadata_inconsistency(self):
        data = bytearray(self.fixture)
        struct.pack_into('<I', data, 72, 1)  # invalid DIFAT count for 1 FAT sector
        self.assertEqual(self.diagnostic(bytes(data)).status, 'failed')

    def test_stream_minifat_cycle(self):
        data = bytearray(self.fixture)
        struct.pack_into('<I', data, 2048, 0)
        self.assertEqual(self.diagnostic(bytes(data)).status, 'failed')

    def test_missing_scene_evidence(self):
        data = bytearray(self.fixture)
        at = 512+128
        data[at:at+10] = 'Other'.encode('utf-16-le')
        self.assertEqual(self.diagnostic(bytes(data)).status, 'unsupported')

    def test_chunk_boundary_failure(self):
        scene = struct.pack('<Hi', 4, 100) + b'A'*58
        self.assertEqual(self.diagnostic(valid_cfb(scene)).status, 'failed')

    def test_compressed_scene_reports_unsupported(self):
        scene = b'\x1f\x8b' + b'\0'*62
        r = self.diagnostic(valid_cfb(scene))
        self.assertEqual((r.kind, r.status), ('compressed_max_unsupported', 'unsupported'))

    def test_read_budget(self):
        r = DefensiveContainerProbe(ProbeLimits(max_bytes_examined=600)).probe_detailed(self.fixture)
        self.assertEqual(r.status, 'failed')

    def test_cpu_directory_budget(self):
        r = DefensiveContainerProbe(ProbeLimits(max_steps=2)).probe_detailed(self.fixture)
        self.assertEqual(r.status, 'failed')

    def test_strict_override_optin(self):
        with self.assertRaises(ValueError):
            ProbeLimits().with_overrides(max_steps=8_000_000)
        self.assertEqual(ProbeLimits().with_overrides(acknowledge_risk=True,
                         max_steps=8_000_000).max_steps, 8_000_000)
        with self.assertRaises(ValueError):
            ProbeLimits(max_steps=0)

    def test_fuzzed_bytes_bound(self):
        rng = random.Random(160022)
        for _ in range(400):
            payload = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 400)))
            result = DefensiveContainerProbe(ProbeLimits(max_steps=500)).probe_detailed(payload)
            self.assertIn(result.status, ('failed', 'unsupported'))


class TestChunkFraming(unittest.TestCase):
    def test_nested_then_sibling(self):
        nested = struct.pack('<Hi', 1, 6)
        container = struct.pack('<HI', 2, 0x80000000 | (len(nested)+6)) + nested
        sibling = struct.pack('<Hi', 3, 6)
        data = container + sibling
        self.assertEqual(validate_chunks(lambda o, n: data[o:o+n], len(data),
            max_nodes=10, max_depth=3, max_steps=10), 3)

    def test_extended_chunk_and_zero_length(self):
        data = struct.pack('<Hiq', 9, 0, 14)
        self.assertEqual(validate_chunks(lambda o,n: data[o:o+n], len(data),
            max_nodes=10, max_depth=2, max_steps=10), 1)
        for bad in (b'\x00'*5, struct.pack('<Hi', 4, 0), struct.pack('<Hiq', 1, 0, -1)):
            with self.assertRaises(UnsafeContainer):
                validate_chunks(lambda o,n: bad[o:o+n], len(bad), max_nodes=10,
                                max_depth=2, max_steps=10)

    def test_chunk_count_and_depth_budgets(self):
        data = struct.pack('<Hi', 4, 6)*20
        with self.assertRaises(UnsafeContainer):
            validate_chunks(lambda o,n: data[o:o+n], len(data),
                            max_nodes=10, max_depth=2, max_steps=200)
        inner = struct.pack('<Hi', 1, 6)
        outer = struct.pack('<HI', 2, 0x8000000C) + inner
        with self.assertRaises(UnsafeContainer):
            validate_chunks(lambda o,n: outer[o:o+n], len(outer),
                            max_nodes=10, max_depth=0, max_steps=20)

    def test_short_reader(self):
        with self.assertRaises(UnsafeContainer):
            validate_chunks(lambda o,n: b'', 6, max_nodes=2, max_depth=2, max_steps=2)


class TestCompressionAndZip(unittest.TestCase):
    def test_decompress_limits(self):
        import zlib
        payload = b'A' * 100_000
        blob = zlib.compress(payload)
        self.assertEqual(decompress_limited(blob, max_output_bytes=200_000,
                                          max_ratio=10_000), payload)
        for content in (blob[:-2], blob+b'trailing'):
            with self.assertRaises(UnsafeContainer):
                decompress_limited(content, max_output_bytes=200_000, max_ratio=10000)
        with self.assertRaises(UnsafeContainer):
            decompress_limited(blob, max_output_bytes=1000, max_ratio=100)

    def zipfile_bytes(self, files):
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for name, content in files:
                z.writestr(name, content)
        return out.getvalue()

    def test_zip_candidate_not_importable(self):
        data = self.zipfile_bytes([('archive/sample.max', MAGIC+b'other')])
        result = DefensiveContainerProbe().probe_detailed(data)
        self.assertEqual((result.kind, result.status), ('zip_wrapped_candidate', 'unsupported'))

    def test_zip_traversal(self):
        for name in ('../secret.max', '/absolute.max', 'C:/absolute.max', 'a\\..\\b.max'):
            with self.subTest(name=name):
                result = DefensiveContainerProbe().probe_detailed(self.zipfile_bytes([(name, MAGIC)]))
                self.assertEqual(result.status, 'failed')

    def test_zip_bomb_metadata(self):
        data = self.zipfile_bytes([('normal.max', b'A'*100_000)])
        result = DefensiveContainerProbe(ProbeLimits(max_decompression_ratio=4)).probe_detailed(data)
        self.assertEqual(result.status, 'failed')

    def test_zip_entries_budget(self):
        data = self.zipfile_bytes([(str(i)+'.txt', b'A') for i in range(8)])
        result = DefensiveContainerProbe(ProbeLimits(max_zip_entries=4)).probe_detailed(data)
        self.assertEqual(result.status, 'failed')


if __name__ == '__main__':
    unittest.main()