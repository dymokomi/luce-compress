#!/usr/bin/env python3
"""Stock Git is a fixture oracle only, never a codec/server runtime dependency."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import zlib


def check(executable):
    executable = Path(executable).resolve()
    # Do not inherit overrides that could redirect Git writes outside the fixture.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    with tempfile.TemporaryDirectory(prefix="luce-compress-git-") as temporary:
        root = Path(temporary)
        repository = root / "fixture.git"

        def git(*arguments, data=None):
            return subprocess.run(["git", "-c", f"core.hooksPath={os.devnull}", *arguments],
                                  input=data, capture_output=True, env=environment,
                                  check=True, timeout=30).stdout

        version = git("--version").decode().strip()
        git("init", "--bare", "--quiet", "--template=", "--initial-branch=main", "--object-format=sha1", str(repository))
        corpus = [b"", b"pub func package_fixture() -> int: return 42\n",
                  b"package source\0" * 4096, bytes(range(256)) * 256]
        object_ids = []
        checks = 0

        def decode(packed, plain, consumed):
            nonlocal checks
            source, expected = root / "packed", root / "expected"
            source.write_bytes(packed)
            expected.write_bytes(plain)
            for inchunk, outchunk in [(1, 1), (31, 127), (0, 0)]:
                result = subprocess.run([str(executable), str(source), str(expected), "zlib",
                                         str(inchunk), str(outchunk), str(consumed), str(len(plain)), "end", "valid"],
                                        capture_output=True, check=False, timeout=30)
                assert result.returncode == 0, (result.stdout, result.stderr)
                for marker in [b"AddressSanitizer", b"UndefinedBehaviorSanitizer", b"runtime error:"]:
                    assert marker not in result.stderr, result.stderr
                fields = result.stdout.decode().strip().split()
                assert fields[0] == "OK" and int(fields[1]) == consumed and int(fields[2]) == len(plain)
                checks += 1

        for plain in corpus:
            oid = git("-C", str(repository), "hash-object", "-w", "--stdin", data=plain).decode().strip()
            logical = f"blob {len(plain)}\0".encode() + plain
            assert hashlib.sha1(logical).hexdigest() == oid
            object_ids.append(oid)
            loose = (repository / "objects" / oid[:2] / oid[2:]).read_bytes()
            assert zlib.decompress(loose) == logical
            decode(loose, logical, len(loose))

        packed = git("-C", str(repository), "pack-objects", "--stdout", "--window=0", "--depth=0",
                     data=("\n".join(object_ids) + "\n").encode())
        assert packed[:4] == b"PACK" and int.from_bytes(packed[4:8], "big") in [2, 3]
        assert int.from_bytes(packed[8:12], "big") == len(corpus)
        assert hashlib.sha1(packed[:-20]).digest() == packed[-20:]
        offset, seen = 12, set()
        for _ in corpus:
            byte = packed[offset]; offset += 1
            kind, size, shift = (byte >> 4) & 7, byte & 15, 4
            while byte & 128:
                assert shift < 64
                byte = packed[offset]; offset += 1
                size |= (byte & 127) << shift
                shift += 7
            assert kind == 3 and size <= max(map(len, corpus))  # undeltified blobs only
            oracle = zlib.decompressobj()
            plain = oracle.decompress(packed[offset:], size + 1)
            assert oracle.eof and len(plain) == size
            used = len(packed) - offset - len(oracle.unused_data)
            oid = hashlib.sha1(f"blob {size}\0".encode() + plain).hexdigest()
            assert oid in object_ids and oid not in seen
            seen.add(oid)
            # Later objects and the pack checksum stay in the offered input.
            decode(packed[offset:], plain, used)
            offset += used
        assert offset == len(packed) - 20 and seen == set(object_ids)
    print(f"PASS {checks} stock-Git loose/packed zlib boundary cases ({version})", flush=True)


if __name__ == "__main__":
    import sys
    check(sys.argv[1])
