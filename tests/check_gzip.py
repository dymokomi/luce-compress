#!/usr/bin/env python3
"""gzip against Python's gzip and zlib: members at every level with every header flag,
multi-member files with zero padding, decoded whole and in seeded pieces to the same
bytes; damaged files are accepted exactly when an RFC 1952 reading over zlib accepts
them (which Python's gzip then reads the same), with its output."""
import gzip
import random
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
from check_brotli import batch, sample


def member(rng, data):
    """A member with random header fields (FTEXT, FHCRC, FEXTRA, FNAME, FCOMMENT)."""
    flags = rng.randrange(32)
    header = bytearray(b"\x1f\x8b\x08" + bytes([flags]) + struct.pack("<I", rng.randrange(1 << 32)) + bytes([rng.choice([0, 2, 4]), rng.randrange(256)]))
    if flags & 4:
        extra = rng.randbytes(rng.randrange(0, 300))
        header += struct.pack("<H", len(extra)) + extra
    if flags & 8:
        header += bytes(rng.randrange(1, 256) for _ in range(rng.randrange(0, 60))) + b"\0"
    if flags & 16:
        header += bytes(rng.randrange(1, 256) for _ in range(rng.randrange(0, 200))) + b"\0"
    if flags & 2:
        header += struct.pack("<H", zlib.crc32(header) & 0xFFFF)
    body = zlib.compressobj(rng.randrange(10), zlib.DEFLATED, -15, rng.randrange(1, 10),
                            rng.choice([zlib.Z_DEFAULT_STRATEGY, zlib.Z_FILTERED, zlib.Z_HUFFMAN_ONLY, zlib.Z_RLE, zlib.Z_FIXED]))
    return bytes(header) + body.compress(data) + body.flush() + struct.pack("<II", zlib.crc32(data), len(data) & 0xFFFFFFFF)


def reference(data):
    """The file's data by RFC 1952 over zlib's raw inflate, or None when it is not a valid
    gzip file: a header CRC or reserved flag Python's gzip module ignores also fails. What
    it accepts Python's gzip must read the same."""
    out, at, members = bytearray(), 0, 0
    while members == 0 or any(data[at:]):
        if len(data) - at < 10 or data[at:at + 3] != b"\x1f\x8b\x08" or data[at + 3] & 0xE0:
            return None
        flags, end = data[at + 3], at + 10
        if flags & 4:
            if len(data) - end < 2:
                return None
            end += 2 + struct.unpack_from("<H", data, end)[0]
        for flag in (8, 16):
            if flags & flag:
                zero = data.find(b"\0", end)
                if zero < 0:
                    return None
                end = zero + 1
        if flags & 2:
            if end + 2 > len(data) or struct.unpack_from("<H", data, end)[0] != zlib.crc32(data[at:end]) & 0xFFFF:
                return None
            end += 2
        if end > len(data):
            return None
        inflater = zlib.decompressobj(-15)
        try:
            body = inflater.decompress(data[end:])
        except zlib.error:
            return None
        rest = inflater.unused_data
        if not inflater.eof or len(rest) < 8 or struct.unpack_from("<II", rest) != (zlib.crc32(body), len(body) & 0xFFFFFFFF):
            return None
        out += body
        at = len(data) - len(rest) + 8
        members += 1
    assert gzip.decompress(data) == out
    return bytes(out)


def check(tool, cases=300):
    tool = Path(tool).resolve()
    rng = random.Random(1952)
    jobs, expected, files = [], [], []
    for case in range(cases):
        members = [sample(rng, rng.choice([0, 1, 100, 5000, 40000, 200000])) for _ in range(rng.choice([1, 1, 1, 2, 3]))]
        packed = b"".join(member(rng, data) for data in members) + bytes(rng.choice([0, 0, 0, 1, 64]))
        data = b"".join(members)
        files.append(packed)
        piece, room = rng.choice([1, 3, 64, 4093, 1 << 20]), rng.choice([1, 7, 4096, 1 << 20])
        for mode in ["gzip", f"gzip/{piece}/{room}"]:
            if mode != "gzip" and len(data) > 60000 and min(piece, room) < 64:
                continue
            jobs.append((mode, packed))
            expected.append(f"OK {len(packed)} {len(data)} {zlib.crc32(data)}")
    for _ in range(cases * 3):
        damaged = bytearray(rng.choice(files))
        operation = rng.randrange(4)
        if operation == 0:
            damaged[rng.randrange(len(damaged))] ^= 1 << rng.randrange(8)
        elif operation == 1:
            del damaged[rng.randrange(len(damaged)):]
        elif operation == 2:
            damaged[rng.randrange(len(damaged) + 1):0] = rng.randbytes(rng.randrange(1, 9))
        else:
            at = rng.randrange(len(damaged))
            damaged[at:at + 4] = rng.randbytes(4)
        damaged = bytes(damaged)
        output = reference(damaged)
        jobs.append(("gzip", damaged))
        expected.append(None if output is None else f"OK {len(damaged)} {len(output)} {zlib.crc32(output)}")
    with tempfile.TemporaryDirectory(prefix="luce-compress-gzip-") as temporary:
        verdicts = batch(tool, jobs, Path(temporary))
    mismatches = 0
    for (mode, packed), want, got in zip(jobs, expected, verdicts):
        ok = got.startswith("ERR corrupt") if want is None else got == want
        if not ok:
            mismatches += 1
            print(f"MISMATCH {mode} {len(packed)} bytes: expected {want}, got {got}", flush=True)
    assert mismatches == 0, mismatches
    print(f"PASS {len(jobs)} gzip checks against Python's gzip", flush=True)


if __name__ == "__main__":
    check(sys.argv[1])
