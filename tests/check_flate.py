#!/usr/bin/env python3
"""flate against zlib: its streams decode in zlib, zlib's decode in it, segments join
into one valid stream, and damaged streams fail cleanly."""
from pathlib import Path
import random
import subprocess
import tempfile
import zlib


def check(executable):
    executable = Path(executable).resolve()
    rng = random.Random(19510501)
    samples = [b"", b"a", b"abc", bytes(range(256)) * 40, b"a" * 100000,
               bytes(rng.randrange(256) for _ in range(5000)),
               bytes(rng.randrange(4) for _ in range(70000)),
               bytes((i * 7 + i // 300) % 251 if i % 1000 < 600 else i % 3 for i in range(90000))]
    # Image-like rows: gradients with noise, then long flat runs.
    samples.append(bytes(min(255, (i % 4096) // 16 + rng.randrange(3)) for i in range(200000)))
    checks = 0
    with tempfile.TemporaryDirectory(prefix="luce-compress-flate-") as temporary:
        root = Path(temporary)
        plain, packed, out = root / "plain", root / "packed", root / "out"
        for data in samples:
            plain.write_bytes(data)
            for level in range(10):
                subprocess.run([executable, "deflate", plain, packed, str(level)], check=True, capture_output=True)
                assert zlib.decompress(packed.read_bytes()) == data, (len(data), level)
                packed.write_bytes(zlib.compress(data, level))
                subprocess.run([executable, "inflate", packed, out, str(len(data))], check=True, capture_output=True)
                assert out.read_bytes() == data, (len(data), level)
                subprocess.run([executable, "segments", plain, packed, str(level)], check=True, capture_output=True)
                assert zlib.decompressobj(-15).decompress(packed.read_bytes()) == data, (len(data), level)
                checks += 3
        # Damage: truncations and flipped bytes end in an error, never a crash.
        data = samples[-1]
        stream = zlib.compress(data, 6)
        cases = [stream[:n] for n in range(0, len(stream), max(1, len(stream) // 60))]
        for _ in range(200):
            changed = bytearray(stream)
            changed[rng.randrange(len(changed))] ^= 1 << rng.randrange(8)
            cases.append(bytes(changed))
        for case in cases:
            packed.write_bytes(case)
            result = subprocess.run([executable, "inflate", packed, out, str(len(data))], capture_output=True)
            assert result.returncode in (0, 1), result.returncode
            if result.returncode == 0:
                # Accepted only as zlib accepts it (a damaged stream can keep its
                # Adler-32), with zlib's output.
                assert zlib.decompress(case) == out.read_bytes()
            checks += 1
    print(f"PASS {checks} flate checks against zlib", flush=True)


if __name__ == "__main__":
    import sys
    check(sys.argv[1])
