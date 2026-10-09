#!/usr/bin/env python3
"""Zstandard against the reference `zstd` CLI: it compresses seeded inputs at levels 1-19
(and 22 with --ultra), with a long window, without checksum or content size, and as
several frames; the codec tool decodes each to the same bytes. Damaged frames: when the
reference rejects one the codec fails with corrupt or unsupported (never a trap), and
when it accepts one the codec gives its output. Frames the codec writes at levels 1-9
decode with the reference to their input."""
import random
import shutil
import subprocess
import tempfile
import zlib
from pathlib import Path
from check_brotli import batch, sample


def compress(cli, data, *flags):
    return subprocess.run([cli, "-q", "-c", *flags], input=data, capture_output=True, check=True).stdout


def reference(cli, data):
    """The reference's decoding of `data`, or None when it rejects it. The memory limit is
    lifted: the codec decodes whole buffers and has no window budget."""
    result = subprocess.run([cli, "-q", "-d", "-c", "--memory=2048MB"], input=data, capture_output=True)
    return result.stdout if result.returncode == 0 else None


def check(tool, cases=150):
    cli = shutil.which("zstd")
    if cli is None:
        print("SKIP zstd oracle: no zstd CLI", flush=True)
        return
    tool = Path(tool).resolve()
    rng = random.Random(8878)
    jobs, expected, frames = [], [], []
    for case in range(cases):
        size = rng.choice([0, 1, 2, 7, 100, 1000, 4096, 30000, 70000, 140000, 300000])
        data = sample(rng, size)
        level = 1 + case % 19
        flags = [f"-{level}"]
        if case % 7 == 3:
            flags.append("--no-check")
        if case % 11 == 5:
            flags += ["--long=24"]
        if case % 13 == 6:
            flags = ["--ultra", "-22"]
        frame = compress(cli, data, *flags)
        if case % 5 == 4:
            # Streamed (no content size), then a second frame and a skippable frame.
            frame = subprocess.run([cli, "-q", "-c", "--no-content-size"], input=data, capture_output=True, check=True).stdout
            tail = sample(rng, rng.randrange(0, 5000))
            skip = (0x184D2A50 + rng.randrange(16)).to_bytes(4, "little") + (3).to_bytes(4, "little") + b"abc"
            frame += skip + compress(cli, tail, "-3")
            data += tail
        frames.append((frame, data))
        jobs.append(("zstd", frame))
        expected.append(f"OK {len(frame)} {len(data)} {zlib.crc32(data)}")
    # Damage: the reference decides; the codec must agree, with its output.
    for _ in range(cases * 4):
        frame, data = rng.choice(frames)
        damaged = bytearray(frame)
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
        output = reference(cli, damaged)
        jobs.append(("zstd", damaged))
        expected.append(None if output is None else f"OK {len(damaged)} {len(output)} {zlib.crc32(output)}")
    with tempfile.TemporaryDirectory(prefix="luce-compress-zstd-") as temporary:
        root = Path(temporary)
        verdicts = batch(tool, jobs, root)
        mismatches = 0
        for (mode, frame), want, got in zip(jobs, expected, verdicts):
            ok = (got.startswith("ERR corrupt") or got.startswith("ERR unsupported")) if want is None else got == want
            if not ok:
                mismatches += 1
                print(f"MISMATCH {mode} {len(frame)} bytes: expected {want}, got {got}", flush=True)
        assert mismatches == 0, mismatches
        # The codec's frames through the reference.
        encodes = []
        for case in range(60):
            data = sample(rng, rng.choice([0, 1, 50, 3000, 70000, 200000, 500000]))
            encodes.append((f"zstd-encode/{1 + case % 9}", data))
        lines = []
        for index, (mode, data) in enumerate(encodes):
            (root / f"in{index}").write_bytes(data)
            lines.append(f"{mode} {root / f'in{index}'} {root / f'out{index}'}")
        (root / "encodes").write_text("\n".join(lines) + "\n")
        result = subprocess.run([tool, "batch", root / "encodes"], capture_output=True, text=True, timeout=600)
        assert result.returncode == 0, result.stderr[-2000:]
        for index, (mode, data) in enumerate(encodes):
            back = reference(cli, (root / f"out{index}").read_bytes())
            assert back == data, f"{mode}: the reference decodes {None if back is None else len(back)} bytes of {len(data)}"
    print(f"PASS {len(jobs)} zstd checks against the reference decoder, {len(encodes)} frames encoded", flush=True)


if __name__ == "__main__":
    import sys
    check(sys.argv[1])
