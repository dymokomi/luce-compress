#!/usr/bin/env python3
"""Seeded bounded decoder mutations with independent zlib bytes/EOF expectations."""
import argparse
import hashlib
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
MAGIC = b"LCFZ01\0\0"


def oracle(packed, wrapped, max_input, max_output):
    assert len(packed) <= 262144 and 0 <= max_input <= 262144 and 0 <= max_output <= 65536
    reader = zlib.decompressobj(15 if wrapped else -15)
    try:
        decoded = reader.decompress(packed, max_output + 1)
    except zlib.error:
        return False, b"", 0
    if not reader.eof or len(decoded) > max_output:
        return False, b"", 0
    assert not reader.unconsumed_tail
    consumed = len(packed) - len(reader.unused_data)
    if consumed > max_input:
        return False, b"", 0
    return True, decoded, consumed


def cases(seed, count):
    rng = random.Random(seed)
    for identity in range(count):
        wrapped = bool(identity % 2)
        size = rng.choice([0, 1, 2, 3, 31, 127, 258, 1024, 4096, 32767, 32768, 32769, 65536])
        pattern = rng.randrange(4)
        if pattern == 0: plain = b"A" * size
        elif pattern == 1: plain = (bytes(range(256)) * ((size + 255) // 256))[:size]
        elif pattern == 2: plain = rng.randbytes(size)
        else: plain = (b"package/name\0version/source\n" * ((size + 27) // 27 + 1))[:size]
        writer = zlib.compressobj(rng.choice([0, 1, 6, 9]), zlib.DEFLATED, 15 if wrapped else -15,
                                 8, rng.choice([zlib.Z_DEFAULT_STRATEGY, zlib.Z_FIXED, zlib.Z_HUFFMAN_ONLY, zlib.Z_RLE]))
        original = writer.compress(plain) + writer.flush()
        packed = bytearray(original)
        operation = (identity // 2) % 12  # exercise both framings for every mutation
        at = rng.randrange(len(packed))
        if operation == 1: packed[at] ^= 1 << rng.randrange(8)
        elif operation == 2: del packed[rng.randrange(len(packed)):]
        elif operation == 3: packed[at:at + rng.randrange(1, 9)] = rng.randbytes(rng.randrange(1, 9))
        elif operation == 4: packed += rng.randbytes(rng.randrange(1, 65))
        elif operation == 5: packed[at:at] = rng.randbytes(rng.randrange(1, 9))
        elif operation == 6: del packed[at:at + rng.randrange(1, 9)]
        elif operation == 7: packed = bytearray(rng.randbytes(rng.randrange(129)))
        elif operation == 8:
            for _ in range(2): packed[rng.randrange(len(packed))] ^= 1 << rng.randrange(8)
        elif operation == 9:
            other = rng.randrange(len(packed))
            packed[at], packed[other] = packed[other], packed[at]
        elif operation == 10: packed += original
        elif operation == 11:
            if wrapped: packed[-1 - rng.randrange(4)] ^= 1 << rng.randrange(8)
            else: packed[0] |= 7
        max_input = len(packed)
        if identity % 17 == 0: max_input = 0
        elif identity % 19 == 0: max_input = max(0, max_input - 1)
        max_output = rng.choice([0, 1, 16, 257, 4096, 65536]) if identity % 23 == 0 else 65536
        valid, decoded, consumed = oracle(packed, wrapped, max_input, max_output)
        partition_seed = rng.getrandbits(32) or 1
        record = struct.pack("<9I", identity, wrapped, valid, len(packed), len(decoded), consumed,
                             max_input, max_output, partition_seed) + packed + decoded
        yield record, valid


def check(driver, seed=19510001, count=4096):
    driver = Path(driver).resolve()
    assert 1 <= count <= 65536 and 0 <= seed < 2 ** 32
    print(f"FUZZ seed={seed} cases={count} python={sys.version.split()[0]} "
          f"zlib={zlib.ZLIB_RUNTIME_VERSION}", flush=True)
    accepted = rejected = batches = total = 0
    digest = hashlib.sha256()
    with tempfile.TemporaryDirectory(prefix="luce-compress-fuzz-") as temporary:
        source = Path(temporary) / "batch.bin"
        pending, size = [], 0

        def run_batch():
            nonlocal batches
            payload = MAGIC + struct.pack("<I", len(pending)) + b"".join(pending)
            assert len(payload) <= 16 * 1024 * 1024
            source.write_bytes(payload)
            try:
                result = subprocess.run([str(driver), str(source)], capture_output=True, timeout=30)
                assert result.returncode == 0, (result.returncode, result.stdout[-2048:], result.stderr[-4096:])
                assert result.stdout.endswith(f"PASS batch {len(pending)}\n".encode()), result.stdout[-1024:]
                for marker in [b"AddressSanitizer", b"UndefinedBehaviorSanitizer", b"runtime error:"]:
                    assert marker not in result.stderr, result.stderr[-4096:]
            except BaseException:
                saved = ROOT / "build/fuzz-failures"
                fingerprint = hashlib.sha256(payload).hexdigest()
                target = saved / f"seed-{seed}-batch-{batches}-{fingerprint[:16]}.bin"
                print(f"FUZZ_FAILURE seed={seed} batch={batches} batch_sha256={fingerprint}", flush=True)
                try:
                    saved.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(payload)
                except OSError as storage_error:
                    # The VPS bundle is read-only; do not hide the codec failure
                    # or relax its isolation merely to retain a test fixture.
                    print(f"REPRO_UNAVAILABLE {storage_error}", flush=True)
                else:
                    print(f"REPRO {target} seed={seed} batch={batches}", flush=True)
                raise
            batches += 1

        for record, valid in cases(seed, count):
            if pending and (len(pending) == 128 or size + len(record) > 8 * 1024 * 1024):
                run_batch()
                pending, size = [], 0
            digest.update(record)
            pending.append(record)
            size += len(record)
            accepted += int(valid)
            rejected += int(not valid)
            total += 1
        if pending: run_batch()
    assert total == count and accepted + rejected == count
    if count >= 256: assert accepted >= count // 10 and rejected >= count // 10
    print(f"PASS {total} seeded decoder fuzz cases; accepted={accepted} rejected={rejected} batches={batches} "
          f"seed={seed} corpus_sha256={digest.hexdigest()} python={sys.version.split()[0]} "
          f"zlib={zlib.ZLIB_RUNTIME_VERSION}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("driver", type=Path)
    parser.add_argument("--seed", type=int, default=19510001)
    parser.add_argument("--cases", type=int, default=4096)
    args = parser.parse_args()
    check(args.driver, args.seed, args.cases)
