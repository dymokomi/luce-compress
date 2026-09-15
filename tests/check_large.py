#!/usr/bin/env python3
"""Independent larger file-stream fixtures; bounded Python/native working chunks."""
import argparse
from pathlib import Path
import random
import subprocess
import tempfile
import zlib

MIB = 1024 * 1024


def verify_encoded(original, actual, window, amount):
    reader = zlib.decompressobj(window)
    expanded = 0
    while chunk := actual.read(65536):
        while chunk:
            previous = len(chunk)
            output = reader.decompress(chunk, 65536)
            chunk = reader.unconsumed_tail
            assert output or len(chunk) < previous, "oracle made no progress"
            assert expanded + len(output) <= amount
            assert original.read(len(output)) == output
            expanded += len(output)
            assert not reader.unused_data, "unexpected trailing compressed bytes"
    # Empty unconsumed_tail is not an EOF proof; drain retained output as needed.
    while not reader.eof:
        output = reader.decompress(b"", 65536)
        if not output: break
        assert expanded + len(output) <= amount
        assert original.read(len(output)) == output
        expanded += len(output)
    assert reader.eof and expanded == amount and not original.read(1)


def check(driver, full=False):
    driver = Path(driver).resolve()
    checks = 0
    with tempfile.TemporaryDirectory(prefix="luce-compress-large-") as temporary:
        root = Path(temporary)
        plain, reference, encoded, decoded = [root / name for name in ["plain", "reference", "encoded", "decoded"]]

        def run(operation, source, target, framing, input_limit, output_limit, reject=False):
            nonlocal checks
            result = subprocess.run([str(driver), operation, str(source), str(target), framing,
                                     str(input_limit), str(output_limit)], capture_output=True, timeout=90)
            checks += 1
            for marker in [b"AddressSanitizer", b"UndefinedBehaviorSanitizer", b"runtime error:"]:
                assert marker not in result.stderr, result.stderr
            if reject:
                assert result.returncode == 1 and result.stdout.startswith(b"REJECT "), (result.stdout, result.stderr)
            else:
                assert result.returncode == 0, (result.stdout, result.stderr)
                fields = result.stdout.decode().split()
                assert len(fields) == 3 and fields[0] == "OK", fields
                assert int(fields[1]) == source.stat().st_size and int(fields[2]) == target.stat().st_size

        for amount in ([MIB + 1, 16 * MIB + 3] if full else [MIB + 1]):
            for framing, window in [("raw", -15), ("zlib", 15)]:
                for pattern in ["repeat", "noise"]:
                    rng = random.Random(19510002)
                    writer = zlib.compressobj(6, zlib.DEFLATED, window)
                    with plain.open("wb") as original, reference.open("wb") as packed:
                        remaining = amount
                        while remaining:
                            size = min(65536, remaining)
                            chunk = rng.randbytes(size) if pattern == "noise" else b"A" * size
                            original.write(chunk)
                            packed.write(writer.compress(chunk))
                            remaining -= size
                        packed.write(writer.flush())
                    packed_size = reference.stat().st_size
                    run("decode", reference, decoded, framing, packed_size, amount)
                    with plain.open("rb") as original, decoded.open("rb") as actual:
                        while chunk := original.read(65536):
                            assert actual.read(len(chunk)) == chunk
                        assert not actual.read(1)
                    run("encode", plain, encoded, framing, amount, amount * 2 + 1024)
                    native_size = encoded.stat().st_size
                    with plain.open("rb") as original, encoded.open("rb") as actual:
                        verify_encoded(original, actual, window, amount)
                    # Keep the full-size positive output intact until both oracles
                    # have verified it; all negative output is disposable afterward.
                    run("decode", reference, decoded, framing, packed_size - 1, amount, reject=True)
                    run("decode", reference, decoded, framing, packed_size, amount - 1, reject=True)
                    run("encode", plain, encoded, framing, amount - 1, amount * 2 + 1024, reject=True)
                    run("encode", plain, encoded, framing, amount, native_size - 1, reject=True)
                    print(f"LARGE bytes={amount} framing={framing} pattern={pattern} native_bytes={native_size}", flush=True)
    print(f"PASS {checks} independent larger-stream oracle/budget cases; bounded file I/O and exact bytes", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("driver", type=Path)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    check(args.driver, args.full)
