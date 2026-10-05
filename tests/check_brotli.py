#!/usr/bin/env python3
"""Brotli against Google's decoder: Python's brotli module (or, without it, the brotli
CLI) compresses seeded inputs at every quality and a range of windows; the codec tool
decodes each whole and in seeded pieces to the same bytes, and damaged streams are
accepted exactly when Google's decoder accepts them, with its output."""
import random
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

try:
    import brotli as google
except ImportError:
    google = None


def compressor():
    """compress(data, quality, window, mode) through the module or the CLI, or None."""
    if google is not None:
        modes = [google.MODE_GENERIC, google.MODE_TEXT, google.MODE_FONT]
        return lambda data, quality, window, mode: google.compress(data, quality=quality, lgwin=window, mode=modes[mode])
    cli = shutil.which("brotli")
    if cli is None:
        return None
    return lambda data, quality, window, mode: subprocess.run(
        [cli, "-q", str(quality), "-w", str(window), "-c"], input=data, capture_output=True, check=True).stdout


def reference(data):
    """Google's decoding of `data`, or None when it rejects it."""
    if google is not None:
        try:
            return google.decompress(data)
        except google.error:
            return None
    result = subprocess.run([shutil.which("brotli"), "-d", "-c"], input=data, capture_output=True)
    return result.stdout if result.returncode == 0 else None


def sample(rng, size):
    kind = rng.randrange(5)
    if kind == 0:
        words = [b"the ", b"brotli ", b"<div class=", b"window ", b"\xc3\xa9t\xc3\xa9 ", b"\n", b"0123 ", b"http://"]
        return b"".join(rng.choice(words) for _ in range(size // 4 + 1))[:size]
    if kind == 1:
        return b"".join(i.to_bytes(4, "little") + bytes([rng.randrange(4), 0, 9, 7]) for i in range(size // 8 + 1))[:size]
    if kind == 2:
        return rng.randbytes(size)
    if kind == 3:
        period = rng.randrange(1, 30)
        return (rng.randbytes(period) * (size // period + 1))[:size]
    return bytes(size)


def batch(tool, jobs, root):
    """Run [(mode, bytes)] through the tool; its verdict lines."""
    listing = root / "list"
    lines = []
    for index, (mode, data) in enumerate(jobs):
        (root / str(index)).write_bytes(data)
        lines.append(f"{mode} {root / str(index)}")
    listing.write_text("\n".join(lines) + "\n")
    result = subprocess.run([tool, "batch", listing], capture_output=True, text=True, timeout=600)
    for marker in ["AddressSanitizer", "UndefinedBehaviorSanitizer", "runtime error:"]:
        assert marker not in result.stderr, result.stderr
    assert result.returncode == 0, (result.returncode, result.stderr[-2000:])
    verdicts = result.stdout.splitlines()
    assert len(verdicts) == len(jobs), (len(verdicts), len(jobs))
    return verdicts


def check(tool, cases=400):
    tool = Path(tool).resolve()
    compress = compressor()
    if compress is None:
        print("SKIP brotli oracle: neither Python's brotli module nor the brotli CLI", flush=True)
        return
    rng = random.Random(7932)
    jobs, expected = [], []
    streams = []
    for case in range(cases):
        size = rng.choice([0, 1, 2, 7, 100, 1000, 4096, 30000, 70000, 300000])
        data = sample(rng, size)
        packed = compress(data, case % 12, rng.randrange(10, 25), rng.randrange(3))
        streams.append((packed, data))
        piece, room = rng.choice([1, 2, 5, 64, 4093]), rng.choice([1, 3, 100, 65536])
        for mode in ["brotli", f"brotli/{piece}/{room}"]:
            if mode != "brotli" and size > 70000 and min(piece, room) < 64:
                continue
            jobs.append((mode, packed))
            expected.append(f"OK {len(packed)} {len(data)} {zlib.crc32(data)}")
    # Damage: Google's decoder decides; the codec must agree, with its output.
    for _ in range(cases * 4):
        packed, data = rng.choice(streams)
        damaged = bytearray(packed)
        operation = rng.randrange(4)
        if operation == 0 and damaged:
            damaged[rng.randrange(len(damaged))] ^= 1 << rng.randrange(8)
        elif operation == 1:
            del damaged[rng.randrange(len(damaged) + 1):]
        elif operation == 2:
            damaged[rng.randrange(len(damaged) + 1):0] = rng.randbytes(rng.randrange(1, 9))
        elif damaged:
            at = rng.randrange(len(damaged))
            damaged[at:at + 4] = rng.randbytes(4)
        damaged = bytes(damaged)
        output = reference(damaged)
        jobs.append(("brotli", damaged))
        expected.append(None if output is None else f"OK {len(damaged)} {len(output)} {zlib.crc32(output)}")
    with tempfile.TemporaryDirectory(prefix="luce-compress-brotli-") as temporary:
        verdicts = batch(tool, jobs, Path(temporary))
    mismatches = 0
    for (mode, packed), want, got in zip(jobs, expected, verdicts):
        if want is None:
            ok = got.startswith("ERR corrupt") or got.startswith("ERR unsupported")
        else:
            ok = got == want
        if not ok:
            mismatches += 1
            print(f"MISMATCH {mode} {len(packed)} bytes: expected {want}, got {got}", flush=True)
    assert mismatches == 0, mismatches
    print(f"PASS {len(jobs)} brotli checks against Google's decoder", flush=True)


if __name__ == "__main__":
    check(sys.argv[1])
