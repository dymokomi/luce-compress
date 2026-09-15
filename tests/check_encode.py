#!/usr/bin/env python3
"""Independent zlib reader; deterministic chunking, exact limits and Git consumers."""
import hashlib
import os
from pathlib import Path
import random
import subprocess
import tempfile
import zlib


def fixed_matches(raw):
    """Small independent RFC 1951 fixed-block inspector for boundary fixtures."""
    bit_at = 0
    def read(count):
        nonlocal bit_at
        value = 0
        for i in range(count):
            assert bit_at < len(raw) * 8
            value |= ((raw[bit_at // 8] >> (bit_at % 8)) & 1) << i
            bit_at += 1
        return value
    assert read(3) == 3  # final fixed block
    codes = {}
    for symbol in range(288):
        code, width = ((symbol + 48, 8) if symbol < 144 else (symbol + 256, 9) if symbol < 256
                       else (symbol - 256, 7) if symbol < 280 else (symbol - 88, 8))
        codes[code, width] = symbol
    lengths = [3,4,5,6,7,8,9,10,11,13,15,17,19,23,27,31,35,43,51,59,67,83,99,115,131,163,195,227,258]
    lextra = [0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,0]
    distances = [1,2,3,4,5,7,9,13,17,25,33,49,65,97,129,193,257,385,513,769,1025,1537,2049,3073,4097,6145,8193,12289,16385,24577]
    dextra = [0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12,12,13,13]
    matches = set()
    while True:
        code = 0
        for width in range(1, 10):
            code = (code << 1) | read(1)
            if (code, width) in codes:
                symbol = codes[code, width]
                break
        else:
            raise AssertionError("invalid fixed symbol")
        if symbol == 256: return matches
        if symbol < 256: continue
        assert symbol <= 285
        length = lengths[symbol - 257] + read(lextra[symbol - 257])
        distance_code = 0
        for _ in range(5): distance_code = (distance_code << 1) | read(1)
        assert distance_code < 30
        distance = distances[distance_code] + read(dextra[distance_code])
        matches.add((length, distance))


def check(executable):
    executable = Path(executable).resolve()
    rng = random.Random(19510915)
    checks = 0
    with tempfile.TemporaryDirectory(prefix="luce-compress-encode-") as temporary:
        root = Path(temporary)
        source, destination = root / "plain", root / "encoded"

        def invoke(plain, framing="zlib", inchunk=0, outchunk=0, max_input=None,
                   max_output=2097152, end="end", reject=False):
            nonlocal checks
            source.write_bytes(plain)
            if max_input is None: max_input = len(plain)
            result = subprocess.run([str(executable), str(source), str(destination), framing,
                                     str(inchunk), str(outchunk), str(max_input), str(max_output), end],
                                    capture_output=True, timeout=30)
            checks += 1
            for marker in [b"AddressSanitizer", b"UndefinedBehaviorSanitizer", b"runtime error:"]:
                assert marker not in result.stderr, result.stderr
            if reject:
                assert result.returncode == 1 and result.stdout.startswith(b"REJECT "), (result.returncode, result.stdout, result.stderr)
                return
            assert result.returncode == 0, (len(plain), framing, inchunk, outchunk, result.stdout, result.stderr)
            packed = destination.read_bytes()
            fields = result.stdout.decode().strip().split()
            assert fields[0] == "OK" and int(fields[1]) == len(plain) and int(fields[2]) == len(packed)
            # Feed independent streaming zlib small chunks; EOF and exact framing
            # are checked, not just the output prefix or a local round trip.
            oracle = zlib.decompressobj(15 if framing == "zlib" else -15)
            decoded = bytearray()
            for at in range(0, len(packed), 37):
                decoded.extend(oracle.decompress(packed[at:at + 37], len(plain) + 1 - len(decoded)))
                assert not oracle.unconsumed_tail and len(decoded) <= len(plain)
            assert oracle.eof and not oracle.unused_data and bytes(decoded) == plain
            assert zlib.decompress(packed, 15 if framing == "zlib" else -15) == plain
            return packed

        corpus = [b"", b"A", b"AB", b"ABC", b"x" * 257, b"x" * 258, b"x" * 259,
                  b"package\0source\n" * 3000, bytes(range(256)) * 300, b"z" * 524288]
        corpus += [rng.randbytes(n) for n in [17, 257, 258, 259, 4097, 32767, 32768, 32769, 65535, 65536, 65537]]
        history = rng.randbytes(32768)
        corpus += [history + history, history + b"!" + history[:1024], history * 3]
        maximum_distance = b"XYZ" + b"a" * 32765 + b"XYZ" + b"a" * 255
        corpus.append(maximum_distance)
        for framing in ["zlib", "raw"]:
            for plain in corpus:
                reference = invoke(plain, framing, 65536, 65536)
                for inchunk, outchunk, end in [(1, 257, "end"), (17, 1, "late"), (0, 0, "end"), (258, 7, "end")]:
                    assert invoke(plain, framing, inchunk, outchunk, end=end) == reference
                assert invoke(plain, framing, 0, 0, max_output=len(reference), end="late") == reference
                invoke(plain, framing, 1, 1, max_output=len(reference) - 1, reject=True)
                invoke(plain, framing, 0, 0, max_output=0, reject=True)
                if plain:
                    invoke(plain, framing, 1, 17, max_input=len(plain) - 1, reject=True)
                if len(plain) == 524288:
                    assert len(reference) < len(plain) // 20  # actual match compression, not stored-only
                    assert (258, 1) in fixed_matches(reference[2:-4] if framing == "zlib" else reference)
                if plain == maximum_distance:
                    assert (258, 32768) in fixed_matches(reference[2:-4] if framing == "zlib" else reference)

            for plain in [b"", b"ABCABCABCABC", bytes(range(31)), b"a" * 259]:
                reference = invoke(plain, framing)
                for cut in range(len(plain) + 1):
                    for outchunk in [0, 1, 13]:
                        assert invoke(plain, framing, -cut - 1, outchunk) == reference

            for _ in range(64):
                seed = rng.randbytes(rng.randrange(1, 257))
                plain = seed * rng.randrange(1, 65) + rng.randbytes(rng.randrange(257))
                reference = invoke(plain, framing, 0, 0)
                assert invoke(plain, framing, 1, 1, end="late") == reference

        # Stock Git reads our encoder's zlib streams as loose and packed objects.
        # All Git state is disposable and isolated from inherited configuration.
        environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
        repository = root / "reader.git"

        def git(*arguments, data=None):
            return subprocess.run(["git", "-c", f"core.hooksPath={os.devnull}", *arguments], input=data,
                                  capture_output=True, env=environment, check=True, timeout=30).stdout

        git("init", "--bare", "--quiet", "--template=", "--initial-branch=main", "--object-format=sha1", str(repository))
        blobs = [b"", b"pub func fixture() -> int: return 42\n", bytes(range(256)) * 256, b"source\0" * 8192]
        pack = bytearray(b"PACK" + (2).to_bytes(4, "big") + len(blobs).to_bytes(4, "big"))
        object_ids = []
        for plain in blobs:
            logical = f"blob {len(plain)}\0".encode() + plain
            oid = hashlib.sha1(logical).hexdigest()
            object_ids.append(oid)
            directory = repository / "objects" / oid[:2]
            directory.mkdir(exist_ok=True)
            (directory / oid[2:]).write_bytes(invoke(logical, inchunk=1, outchunk=1))
            assert git("-C", str(repository), "cat-file", "blob", oid) == plain
            # Minimal undeltified pack fixture. Python supplies only framing/hash;
            # every object's compressed bytes come from the Base encoder.
            size = len(plain)
            first, size = 0x30 | (size & 15), size >> 4
            pack.append(first | (128 if size else 0))
            while size:
                value, size = size & 127, size >> 7
                pack.append(value | (128 if size else 0))
            pack.extend(invoke(plain, inchunk=0, outchunk=0))
        pack.extend(hashlib.sha1(pack).digest())
        # Separate empty reader guarantees cat-file cannot fall back to loose files.
        packed_repository = root / "packed-reader.git"
        git("init", "--bare", "--quiet", "--template=", "--initial-branch=main", "--object-format=sha1", str(packed_repository))
        git("-C", str(packed_repository), "index-pack", "--stdin", "--strict", data=bytes(pack))
        for oid, plain in zip(object_ids, blobs):
            assert git("-C", str(packed_repository), "cat-file", "blob", oid) == plain
        print(f"PASS {checks} incremental encoder oracle/chunk/budget cases; stock Git reads 4 loose and 4 packed Base-encoded objects", flush=True)


if __name__ == "__main__":
    import sys
    check(sys.argv[1])
