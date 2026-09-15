#!/usr/bin/env python3
"""Independent incremental/raw/zlib fixtures; short-lived chunks and exact budgets."""
from pathlib import Path
import random
import subprocess
import tempfile
import zlib
from check_codecs import Bits, dynamic_literal


def check(executable):
    executable = Path(executable).resolve()
    random_source = random.Random(19501951)
    checks = 0
    with tempfile.TemporaryDirectory(prefix="luce-compress-stream-") as tmp:
        packed_file, plain_file = Path(tmp) / "packed", Path(tmp) / "plain"

        def invoke(packed, plain=b"", framing="zlib", inchunk=0, outchunk=0,
                   max_input=None, max_output=None, end="end", suffix=b"", reject=False):
            nonlocal checks
            packed_file.write_bytes(packed + suffix)
            plain_file.write_bytes(plain)
            if max_input is None: max_input = len(packed)
            if max_output is None: max_output = 1048576 if reject else len(plain)
            result = subprocess.run([str(executable), str(packed_file), str(plain_file), framing,
                                     str(inchunk), str(outchunk), str(max_input), str(max_output),
                                     end, "invalid" if reject else "valid"],
                                    capture_output=True, timeout=30)
            checks += 1
            for marker in [b"AddressSanitizer", b"UndefinedBehaviorSanitizer", b"runtime error:"]:
                assert marker not in result.stderr, result.stderr
            if reject:
                assert result.returncode == 1 and result.stdout.startswith(b"REJECT "), (result.returncode, result.stdout, result.stderr)
            else:
                assert result.returncode == 0, (framing, len(packed), inchunk, outchunk, result.stdout, result.stderr)
                fields = result.stdout.decode().strip().split()
                assert fields[0] == "OK" and int(fields[1]) == len(packed) and int(fields[2]) == len(plain), fields

        corpus = [b"", b"A", b"abracadabra\0" * 31, b"x" * 4097,
                  bytes(range(256)) * 300, random_source.randbytes(4097), random_source.randbytes(65537)]
        for framing, window in [("zlib", 15), ("raw", -15)]:
            for plain in corpus:
                for level, strategy in [(0, zlib.Z_DEFAULT_STRATEGY), (6, zlib.Z_FIXED),
                                        (6, zlib.Z_DEFAULT_STRATEGY), (6, zlib.Z_HUFFMAN_ONLY)]:
                    encoder = zlib.compressobj(level, zlib.DEFLATED, window, 8, strategy)
                    packed = encoder.compress(plain) + encoder.flush()
                    for inchunk, outchunk in [(1, 257), (17, 1), (0, 0), (65536, 65536)]:
                        invoke(packed, plain, framing, inchunk, outchunk)
                    if len(plain) <= 4097:
                        invoke(packed, plain, framing, 1, 1, end="late")
                    invoke(packed, plain, framing, 7, 13, suffix=b"the next object\0\xff")
                    invoke(packed, framing=framing, inchunk=1, outchunk=17,
                           max_input=len(packed) - 1, reject=True)
                    if plain:
                        invoke(packed, framing=framing, inchunk=11, outchunk=1,
                               max_output=len(plain) - 1, reject=True)

            # Every first split, including empty input, and every truncated prefix.
            short = [(zlib.compress(b"one two one two"), b"one two one two"),
                     (zlib.compress(b"abc", 0), b"abc"), (dynamic_literal(b"A"), b"A"),
                     (dynamic_literal(), b"")]
            for wrapped, plain in short:
                packed = wrapped if framing == "zlib" else wrapped[2:-4]
                for cut in range(len(packed) + 1):
                    for outchunk in [0, 1, 7]:
                        invoke(packed, plain, framing, -cut - 1, outchunk)
                for cut in range(len(packed)):
                    for inchunk, outchunk, end in [(1, 1, "end"), (3, 0, "late")]:
                        invoke(packed[:cut], framing=framing, inchunk=inchunk, outchunk=outchunk,
                               end=end, reject=True)

            # Multiple compressed/empty stored blocks with history across flushes.
            encoder = zlib.compressobj(wbits=window)
            base = random_source.randbytes(32768)
            pieces = [base, base, b"a" * 40000, base[:1000]]
            packed = b""
            for piece in pieces:
                packed += encoder.compress(piece) + encoder.flush(zlib.Z_SYNC_FLUSH)
            packed += encoder.flush()
            invoke(packed, b"".join(pieces), framing, 19, 1)
            invoke(packed, b"".join(pieces), framing, 1, 127)

            # Explicit maximum-distance reference crossing the history ring wrap.
            prefix = bytes(range(256)) * 128
            bits = Bits(); bits.put(3, 3); bits.code(197, 8); bits.code(29, 5)
            bits.put(8191, 13); bits.code(0, 7)
            raw = b"\x00\x00\x80\xff\x7f" + prefix + bits.finish()[2:-4]
            plain = prefix + prefix[:258]
            wrapped = b"\x78\x01" + raw + zlib.adler32(plain).to_bytes(4, "big")
            assert zlib.decompress(raw, -15) == plain and zlib.decompress(wrapped) == plain
            invoke(wrapped if framing == "zlib" else raw, plain, framing, 1, 1)
            if framing == "zlib":
                # Same valid DEFLATE, but a declared 256-byte window cannot serve it.
                invoke(b"\x08\x1d" + wrapped[2:], framing=framing, reject=True)

            raw = b"\x00\x00\x00\xff\xff" * 64 + b"\x01\x00\x00\xff\xff"
            packed = raw if framing == "raw" else b"\x78\x01" + raw + b"\x00\x00\x00\x01"
            invoke(packed, b"", framing, 1, 1)

            # Mutation oracle also handles valid altered raw streams (no checksum).
            original = zlib.compress(b"mutation stream" * 20)
            original = original if framing == "zlib" else original[2:-4]
            for _ in range(96):
                candidate = bytearray(original)
                candidate[random_source.randrange(len(candidate))] ^= 1 << random_source.randrange(8)
                candidate = bytes(candidate)
                oracle = zlib.decompressobj(window)
                try:
                    plain = oracle.decompress(candidate, 65537)
                    valid = oracle.eof and len(plain) <= 65536
                except zlib.error:
                    valid = False
                if valid:
                    boundary = len(candidate) - len(oracle.unused_data)
                    invoke(candidate[:boundary], plain, framing, 1, 1, max_output=65536, suffix=oracle.unused_data)
                else:
                    invoke(candidate, framing=framing, inchunk=1, outchunk=1, max_output=65536, reject=True)

        # Wrapped checksum corruption after output was produced remains an error.
        packed = zlib.compress(b"quarantined output" * 300)
        for index in range(len(packed) - 4, len(packed)):
            for bit in range(8):
                candidate = bytearray(packed); candidate[index] ^= 1 << bit
                invoke(bytes(candidate), inchunk=1, outchunk=1, reject=True)
        dictionary = zlib.compressobj(zdict=b"dictionary")
        invoke(dictionary.compress(b"dictionary") + dictionary.flush(), inchunk=1, outchunk=1, reject=True)
        for lengths in [[1, 1, 1, 1], [2, 2, 0, 0], [0, 0, 0, 0]]:
            bits = Bits(); bits.put(5, 3); bits.put(0, 14)
            for length in lengths: bits.put(length, 3)
            invoke(bits.finish(), inchunk=1, outchunk=1, reject=True)
        invoke(dynamic_literal(b"A", missing_end=True), inchunk=1, outchunk=1, reject=True)
    print(f"PASS {checks} incremental raw/zlib, split/truncation, backpressure, history, budget and mutation cases", flush=True)


if __name__ == "__main__":
    import sys
    check(sys.argv[1])
