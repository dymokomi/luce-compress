#!/usr/bin/env python3
"""Independent zlib oracle, strict corruption fixtures and bounded mutation tests."""
import random
import subprocess
import tempfile
from pathlib import Path
import zlib


class Bits:
    def __init__(self):
        self.bits = []

    def put(self, value, count):
        self.bits.extend((value >> i) & 1 for i in range(count))

    def code(self, value, count):
        self.bits.extend((value >> i) & 1 for i in reversed(range(count)))

    def finish(self, plain=b""):
        data = bytearray((len(self.bits) + 7) // 8)
        for index, bit in enumerate(self.bits):
            data[index // 8] |= bit << (index % 8)
        return b"\x78\x01" + data + zlib.adler32(plain).to_bytes(4, "big")


def dynamic_literal(plain=b"", missing_end=False):
    """Independent valid single-symbol/empty-distance and missing-EOB fixtures."""
    bits = Bits()
    bits.put(5, 3)
    bits.put(0, 5)  # 257 literal/length codes
    bits.put(0, 5)  # one unused distance code
    bits.put(14, 4)  # 18 code-length entries, including symbols 0 and 1
    order = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1]
    for symbol in order:
        bits.put(1 if symbol in [0, 1] else 0, 3)
    for symbol in range(258):
        bits.put(int((symbol == 65 and bool(plain)) or (symbol == 256 and not missing_end)), 1)
    for _ in plain:
        bits.put(0, 1)
    bits.put(1 if plain else 0, 1)
    return bits.finish(plain)


def check(executable):
    executable = Path(executable).resolve()
    generator = random.Random(20260914)
    checks = 0
    with tempfile.TemporaryDirectory(prefix="luce-compress-oracle-") as tmp:
        source, output = Path(tmp) / "input", Path(tmp) / "output"

        def invoke(operation, data, maximum=1048576, trailing=False, expected=None, reject=False):
            nonlocal checks
            source.write_bytes(data)
            result = subprocess.run([str(executable), operation, str(source), str(output),
                                     str(maximum), "trailing" if trailing else "strict"],
                                    capture_output=True, timeout=30)
            checks += 1
            for marker in [b"AddressSanitizer", b"UndefinedBehaviorSanitizer", b"runtime error:"]:
                assert marker not in result.stderr, result.stderr
            if reject:
                assert result.returncode == 1, (operation, result.returncode, result.stderr)
                return
            assert result.returncode == 0, (operation, result.returncode, result.stderr)
            fields = result.stdout.decode().strip().split()
            assert len(fields) == 4 and fields[0] == "OK", fields
            consumed, adler, crc = map(int, fields[1:])
            assert adler == zlib.adler32(data) and crc == zlib.crc32(data)
            actual = output.read_bytes()
            if expected is not None:
                assert actual == expected, (len(actual), len(expected))
            return actual, consumed

        corpus = [b"", b"A", b"ab", b"package/source\0" * 8192,
                  bytes(range(256)) * 512, b"x" * 524288]
        corpus += [generator.randbytes(n) for n in [17, 257, 4096, 32768, 65535, 65536, 65537]]
        for plain in corpus:
            encoded, consumed = invoke("encode", plain)
            assert consumed == len(plain) and zlib.decompress(encoded) == plain
            invoke("encode", plain, len(encoded), expected=encoded)
            invoke("encode", plain, len(encoded) - 1, reject=True)
            streams = [zlib.compress(plain, level) for level in [0, 1, 6, 9]]
            for strategy in [zlib.Z_FILTERED, zlib.Z_HUFFMAN_ONLY, zlib.Z_RLE, zlib.Z_FIXED]:
                compressor = zlib.compressobj(6, zlib.DEFLATED, 15, 8, strategy)
                streams.append(compressor.compress(plain) + compressor.flush())
            for stream in streams + [encoded]:
                _, count = invoke("decode", stream, len(plain), expected=plain)
                assert count == len(stream)
            stream = streams[-1]
            _, count = invoke("decode", stream + b"next object", len(plain), True, plain)
            assert count == len(stream)
            invoke("decode", stream + b"next object", len(plain), reject=True)
            if plain:
                invoke("decode", stream, len(plain) - 1, reject=True)

        for plain in [b"", b"A", b"A" * 1000]:
            stream = dynamic_literal(plain)
            assert zlib.decompress(stream) == plain
            invoke("decode", stream, len(plain), expected=plain)
        invoke("decode", dynamic_literal(b"A", missing_end=True), reject=True)

        # Invalid code-length alphabets: over-subscribed, incomplete, empty.
        for lengths in [[1, 1, 1, 1], [2, 2, 0, 0], [0, 0, 0, 0], [1, 0, 0, 0]]:
            bits = Bits()
            bits.put(5, 3)
            bits.put(0, 14)
            for length in lengths:
                bits.put(length, 3)
            invoke("decode", bits.finish(), reject=True)
        # Reserved block, illegal literal/length, illegal distance, no history.
        bits = Bits(); bits.put(7, 3)
        invoke("decode", bits.finish(), reject=True)
        bits = Bits(); bits.put(3, 3); bits.code(198, 8)
        invoke("decode", bits.finish(), reject=True)
        for distance in [0, 30, 31]:
            bits = Bits(); bits.put(3, 3); bits.code(1, 7); bits.code(distance, 5)
            invoke("decode", bits.finish(), reject=True)
        invoke("decode", b"\x78\x01\x01\x01\x00\xff\xffA\x00\x42\x00\x42", reject=True)
        dictionary = zlib.compressobj(zdict=b"shared dictionary")
        invoke("decode", dictionary.compress(b"shared dictionary") + dictionary.flush(), reject=True)

        stream = zlib.compress(bytes(range(128)) * 4)
        for cut in range(len(stream)):
            invoke("decode", stream[:cut], reject=True)
        for position in range(len(stream) - 4, len(stream)):
            for bit in range(8):
                changed = bytearray(stream); changed[position] ^= 1 << bit
                invoke("decode", bytes(changed), reject=True)
        for maximum in [-1, 1073741825]:
            invoke("decode", stream, maximum, reject=True)
            invoke("encode", b"x", maximum, reject=True)
        first, second = zlib.compress(b"first"), zlib.compress(b"second")
        _, count = invoke("decode", first + second, 5, True, b"first")
        assert count == len(first)
        invoke("decode", first + second, reject=True)
        invoke("decode", zlib.compress(b"x" * 1048576), 4096, reject=True)

        # Bounded, seeded byte mutations; any accepted bytes must agree with zlib.
        for iteration in range(256):
            changed = bytearray(stream)
            for _ in range(1 + iteration % 3):
                changed[generator.randrange(len(changed))] ^= 1 << generator.randrange(8)
            changed = bytes(changed)
            oracle = zlib.decompressobj()
            try:
                plain = oracle.decompress(changed, 65537)
                valid = oracle.eof and not oracle.unused_data and len(plain) <= 65536
            except zlib.error:
                valid = False
            invoke("decode", changed, 65536, expected=plain if valid else None, reject=not valid)
    print(f"PASS {checks} independent zlib, bounds, checksum, truncation, tree and mutation cases", flush=True)


if __name__ == "__main__":
    import sys
    check(sys.argv[1])
