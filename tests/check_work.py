#!/usr/bin/env python3
"""Independent codec fixtures with bounded dispatch budgets, including zero-I/O yields."""
from pathlib import Path
import random
import subprocess
import tempfile
import zlib
from check_codecs import dynamic_literal


def check(decoder, encoder):
    decoder, encoder = Path(decoder).resolve(), Path(encoder).resolve()
    rng = random.Random(19514096)
    checks = 0
    default_yields = [False, False]
    empty_yields = [False, False]
    with tempfile.TemporaryDirectory(prefix="luce-compress-work-") as temporary:
        root = Path(temporary)
        source, expected, destination = root / "source", root / "expected", root / "encoded"

        def run(command, maximum_steps, kind, work, reject=False):
            nonlocal checks
            result = subprocess.run([str(item) for item in command], capture_output=True, timeout=30)
            checks += 1
            for marker in [b"AddressSanitizer", b"UndefinedBehaviorSanitizer", b"runtime error:"]:
                assert marker not in result.stderr, result.stderr
            if reject:
                assert result.returncode == 1 and result.stdout.startswith(b"REJECT "), (result.stdout, result.stderr)
                return None
            assert result.returncode == 0, (command, result.stdout, result.stderr)
            fields = result.stdout.decode().strip().split()
            assert len(fields) == 7 and fields[0] == "OK", fields
            consumed, produced, steps, yields, empty, units = map(int, fields[1:])
            assert 1 <= steps <= maximum_steps and 0 <= empty <= yields < steps, fields
            assert steps <= units <= steps * (31 if work == 0 else work), fields
            if work == 4096 and yields: default_yields[kind] = True
            if empty: empty_yields[kind] = True
            return consumed, produced

        def decode(packed, plain, framing, work, chunks=(65536, 65536), end="end",
                   reject=False, max_input=None, max_output=None, suffix=b""):
            source.write_bytes(packed + suffix)
            expected.write_bytes(plain)
            limits = (len(packed) if max_input is None else max_input,
                      len(plain) if max_output is None else max_output)
            counts = run([decoder, source, expected, framing, *chunks, *limits, end,
                          "invalid" if reject else "valid", work],
                         16 * (len(packed) + len(plain) + 1) + 128, 0, work, reject)
            if not reject: assert counts == (len(packed), len(plain)), counts

        def encode(plain, framing, work, chunks=(65536, 65536), end="end",
                   reject=False, max_input=None, max_output=2097152):
            source.write_bytes(plain)
            counts = run([encoder, source, destination, framing, *chunks,
                          len(plain) if max_input is None else max_input, max_output, end, work],
                         16 * (len(plain) + 1) + 128, 1, work, reject)
            if reject: return None
            packed = destination.read_bytes()
            assert counts == (len(plain), len(packed)), counts
            oracle = zlib.decompressobj(15 if framing == "zlib" else -15)
            decoded = oracle.decompress(packed, len(plain) + 1)
            assert decoded == plain and oracle.eof and not oracle.unused_data and not oracle.unconsumed_tail
            return packed

        corpus = [b"", b"A", b"abc\0" * 259, rng.randbytes(4097), rng.randbytes(65537),
                  b"a" * 131073, bytes(range(256)) * 257]
        def chunks_for(work):
            # Borrowed buffers are overwritten after every step. Avoid quadratic
            # test-driver copying of a huge suffix when one dispatch consumes a
            # byte; native output still has room for many dispatches. Default/max
            # allowance fixtures retain the full 64 KiB input-span coverage.
            if work == 0: return 0, 0
            return (257, 65536) if work in [1, 2, 7] else (65536, 65536)

        for framing, window in [("raw", -15), ("zlib", 15)]:
            for plain in corpus:
                reference = encode(plain, framing, 65536)
                for work in [1, 2, 7, 0, 4096, 65536]:
                    assert encode(plain, framing, work, chunks_for(work)) == reference
                for level, strategy in [(0, zlib.Z_DEFAULT_STRATEGY), (6, zlib.Z_FIXED),
                                        (6, zlib.Z_DEFAULT_STRATEGY), (6, zlib.Z_HUFFMAN_ONLY)]:
                    writer = zlib.compressobj(level, zlib.DEFLATED, window, 8, strategy)
                    packed = writer.compress(plain) + writer.flush()
                    for work in [1, 2, 7, 0, 4096, 65536]:
                        decode(packed, plain, framing, work, chunks_for(work))

            # Empty stored blocks spend CPU even when they emit no bytes.
            raw = b"\x00\x00\x00\xff\xff" * 4096 + b"\x01\x00\x00\xff\xff"
            packed = raw if framing == "raw" else b"\x78\x01" + raw + b"\x00\x00\x00\x01"
            assert zlib.decompress(packed, window) == b""
            for work in [1, 7, 4096]: decode(packed, b"", framing, work, suffix=b"next object")

            # Every first split and truncated prefix of fixed/dynamic fixtures,
            # with a one-operation budget and both ordinary and delayed EOF.
            for wrapped, plain in [(zlib.compress(b"abcabcabc"), b"abcabcabc"),
                                   (dynamic_literal(b"A"), b"A"), (dynamic_literal(), b"")]:
                packed = wrapped if framing == "zlib" else wrapped[2:-4]
                for cut in range(len(packed) + 1):
                    decode(packed, plain, framing, 1, (-cut - 1, 1))
                for cut in range(len(packed)):
                    decode(packed[:cut], b"", framing, 1, (1, 1), end="late", reject=True, max_output=1024)
                decode(packed, plain, framing, 1, (1, 1), end="late", suffix=b"next stream")
                if plain:
                    decode(packed, b"", framing, 1, reject=True, max_output=len(plain) - 1)
                decode(packed, b"", framing, 1, reject=True, max_input=len(packed) - 1, max_output=1024)

            short = b"final marker across yields"
            reference = encode(short, framing, 65536)
            for cut in range(len(short) + 1):
                assert encode(short, framing, 1, (-cut - 1, 1), end="late") == reference
            encode(short, framing, 1, reject=True, max_input=len(short) - 1)
            encode(short, framing, 1, reject=True, max_output=len(reference) - 1)
            # A reserved block must reject, not yield indefinitely.
            invalid = b"\x07" if framing == "raw" else b"\x78\x01\x07"
            decode(invalid, b"", framing, 1, reject=True, max_output=1024)

        wrapped = zlib.compress(b"partial output remains quarantined" * 100)
        for index in range(len(wrapped) - 4, len(wrapped)):
            changed = bytearray(wrapped); changed[index] ^= 1
            decode(bytes(changed), b"", "zlib", 1, reject=True, max_output=65536)

    assert all(default_yields) and all(empty_yields), (default_yields, empty_yields)
    print(f"PASS {checks} cooperative-work oracle/split/error cases; bounded dispatches, zero-I/O/default yields and exact resumed bytes", flush=True)


if __name__ == "__main__":
    import sys
    check(sys.argv[1], sys.argv[2])
