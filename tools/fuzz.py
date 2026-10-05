#!/usr/bin/env python3
"""Mutate Brotli and gzip streams and decode them: the codecs must never trap, hang or
grow without bound, whatever the bytes.

The corpus is Google's brotli test data, streams the brotli CLI or Python's brotli module
makes from varied inputs at every quality, and gzip files with every header field and
several members. Each case is one stream changed by a few mutations (bits flipped, bytes
set, inserted, deleted or repeated, spans spliced from another stream, cut short or
extended) and decoded whole or incrementally with random piece sizes, under an output
limit of 16 MiB. Cases run in batches through codec_tool, each batch under a time limit;
a batch that dies or times out is narrowed to the case responsible, which is saved
under build/fuzz-failures. With Python's brotli module, every Brotli verdict is also
compared with Google's decoder: accepted with the same bytes, or refused by both.

First, a bomb phase: streams that would expand to gigabytes (Brotli meta-blocks of 16 MiB
copies, a 1 GiB gzip member of zeros) must fail with `limit` quickly and in little memory.
The peak memory of the decoding processes is reported.

  python3 tools/fuzz.py [--cases 20000] [--seed 1] [--tool build/codec_tool]
"""
import argparse
import gzip
import random
import resource
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTDATA = ROOT.parent / ".donors/brotli/tests/testdata"
FAILURES = ROOT / "build/fuzz-failures"
LIMIT = 16 * 1024 * 1024
sys.path.insert(0, str(ROOT / "tests"))
from check_brotli import compressor, sample  # noqa: E402
from check_gzip import member  # noqa: E402

try:
    import brotli as google
except ImportError:
    google = None


class Bits:
    def __init__(self):
        self.value, self.count = 0, 0

    def put(self, value, bits):
        self.value |= value << self.count
        self.count += bits

    def bytes(self):
        return self.value.to_bytes((self.count + 7) // 8, "little")


def brotli_bomb(blocks):
    """`blocks` meta-blocks of 16 MiB each: one literal, then a copy of 16,777,215 bytes
    at distance 1, written with one-symbol codes (a dozen bytes a block)."""
    bits = Bits()
    bits.put(0b1111, 4)  # WBITS 24
    for _ in range(blocks):
        bits.put(0, 1)  # not last
        bits.put(2, 2)  # six nibbles
        bits.put((1 << 24) - 1, 24)  # MLEN 16 MiB
        bits.put(0, 1)  # compressed
        for _ in range(3):
            bits.put(0, 1)  # one block type
        bits.put(0, 6)  # NPOSTFIX 0, NDIRECT 0
        bits.put(0, 2)  # LSB6
        bits.put(0, 2)  # one tree each
        bits.put(1, 2); bits.put(0, 2); bits.put(ord("z"), 8)  # literal code: one symbol
        # Insert code 1 (one literal), copy code 23 (2118 + 24 bits): symbol 384 + 8 + 7.
        bits.put(1, 2); bits.put(0, 2); bits.put(384 + 8 + 7, 10)
        bits.put(1, 2); bits.put(0, 2); bits.put(16, 6)  # distance code: one symbol (16: distance 1 or 2)
        bits.put((1 << 24) - 1 - 2118, 24)  # copy extra: the rest of the block
        bits.put(0, 1)  # distance extra bit: distance 1
    bits.put(0b11, 2)
    return bits.bytes()


def corpus(rng):
    """(kind, bytes) streams to mutate."""
    streams = []
    for path in sorted(TESTDATA.glob("*.compressed*")):
        if path.stat().st_size < 200000:
            streams.append(("brotli", path.read_bytes()))
    compress = compressor()
    if compress is not None:
        for quality in range(12):
            for _ in range(6):
                data = sample(rng, rng.choice([1, 50, 600, 5000, 40000]))
                streams.append(("brotli", compress(data, quality, rng.randrange(10, 25), rng.randrange(3))))
    for _ in range(60):
        data = b"".join(sample(rng, rng.choice([0, 10, 3000, 30000])) for _ in range(rng.choice([1, 2])))
        streams.append(("gzip", member(rng, data) + (member(rng, data[:100]) if rng.random() < 0.3 else b"")))
    return streams


def mutate(data, rng, donors):
    data = bytearray(data)
    for _ in range(rng.choice([1, 1, 2, 3, 4])):
        choice = rng.random()
        at = rng.randint(0, len(data))
        if choice < 0.3 and data:
            data[min(at, len(data) - 1)] ^= 1 << rng.randint(0, 7)
        elif choice < 0.4 and data:
            data[min(at, len(data) - 1)] = rng.choice([0, 0xFF, rng.randrange(256)])
        elif choice < 0.5:
            data[at:at] = rng.randbytes(rng.randint(1, 8))
        elif choice < 0.6 and data:
            del data[at:at + rng.randint(1, 16)]
        elif choice < 0.7 and data:
            end = min(len(data), at + rng.randint(1, 64))
            data[at:at] = data[at:end] * rng.randint(1, 4)
        elif choice < 0.8:
            donor = rng.choice(donors)
            start = rng.randint(0, max(0, len(donor) - 1))
            data[at:at] = donor[start:start + rng.randint(1, 200)]
        elif choice < 0.9:
            del data[at:]
        else:
            data += rng.randbytes(rng.randint(1, 32))
    return bytes(data)


def run(tool, jobs, timeout):
    """Run [(mode, bytes)] in one tool process: (verdicts or None when it died or timed
    out, why)."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        lines = []
        for index, (mode, data) in enumerate(jobs):
            (root / str(index)).write_bytes(data)
            lines.append(f"{mode} {root / str(index)}")
        (root / "list").write_text("\n".join(lines) + "\n")
        try:
            result = subprocess.run([tool, "batch", root / "list", str(LIMIT)], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, "timeout"
        verdicts = result.stdout.splitlines()
        if result.returncode != 0 or len(verdicts) != len(jobs):
            return None, f"exit {result.returncode}: {result.stderr.strip()[-300:]}"
        return verdicts, ""


def narrow(tool, jobs, timeout):
    """The first job that alone makes the tool die or time out."""
    while len(jobs) > 1:
        half = jobs[:len(jobs) // 2]
        verdicts, _ = run(tool, half, timeout)
        jobs = half if verdicts is None else jobs[len(jobs) // 2:]
    return jobs[0]


def bombs(tool):
    failures = []
    for name, mode, data in [("brotli 1000 x 16 MiB", "brotli", brotli_bomb(1000)),
                             ("brotli 1000 x 16 MiB in pieces", "brotli/4096/65536", brotli_bomb(1000)),
                             ("gzip 1 GiB of zeros", "gzip", None), ("gzip 1 GiB in pieces", "gzip/4096/65536", None)]:
        if data is None:
            writer = zlib.compressobj(9, zlib.DEFLATED, -15)
            chunk, body = bytes(1 << 20), bytearray()
            for _ in range(1024):
                body += writer.compress(chunk)
            body += writer.flush()
            data = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff" + bytes(body) + zlib.crc32(b"").to_bytes(4, "little") + bytes(4)
        started = time.monotonic()
        verdicts, why = run(tool, [(mode, data)], 60)
        spent = time.monotonic() - started
        verdict = verdicts[0] if verdicts else why
        ok = verdict.startswith("ERR limit") and spent < 10
        print(f"bomb {name:<32} {len(data):>9} bytes {spent:6.2f} s  {verdict}", flush=True)
        if not ok:
            failures.append(f"bomb {name}: {verdict}")
    if google is not None:
        try:
            google.decompress(brotli_bomb(1))
        except google.error:
            failures.append("bomb: Google's decoder refuses the one-block bomb")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tool", type=Path, default=ROOT / "build/codec_tool")
    parser.add_argument("--cases", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--batch", type=int, default=400)
    args = parser.parse_args()
    tool = args.tool.resolve()
    rng = random.Random(args.seed)
    failures = bombs(tool)
    streams = corpus(rng)
    donors = [data for _, data in streams]
    started = time.monotonic()
    counts = {"OK": 0, "ERR": 0}
    agreed = disagreed = 0
    done = 0
    while done < args.cases:
        jobs, references = [], []
        for _ in range(min(args.batch, args.cases - done)):
            kind, data = rng.choice(streams)
            mutated = mutate(data, rng, donors)
            mode = kind if rng.random() < 0.6 else f"{kind}/{rng.choice([1, 3, 64, 4096])}/{rng.choice([1, 7, 1000, 65536])}"
            jobs.append((mode, mutated))
            references.append(None)
            if kind == "brotli" and google is not None:
                try:
                    output = google.decompress(mutated)
                    references[-1] = f"OK {len(mutated)} {len(output)} {zlib.crc32(output)}" if len(output) <= LIMIT else "limit"
                except google.error:
                    references[-1] = "ERR"
        verdicts, why = run(tool, jobs, 120)
        if verdicts is None:
            mode, data = narrow(tool, jobs, 120)
            FAILURES.mkdir(parents=True, exist_ok=True)
            path = FAILURES / f"case-{args.seed}-{done}.{mode.split('/')[0]}"
            path.write_bytes(data)
            failures.append(f"{why} ({mode}) saved as {path}")
            print(f"FAIL {why}: {path}", flush=True)
        else:
            for (mode, data), verdict, reference in zip(jobs, verdicts, references):
                fields = verdict.split()
                counts[fields[0]] += 1
                if reference is None or reference == "limit":
                    continue
                # A stream decoded in pieces stops at its end; bytes after it are
                # refused only by a whole-buffer decode, as Google's decoder refuses them.
                trailing = fields[0] == "OK" and int(fields[1]) != len(data)
                if verdict == reference or (reference == "ERR" and (fields[0] == "ERR" or trailing)):
                    agreed += 1
                else:
                    disagreed += 1
                    print(f"DIFFERS from Google's decoder: {verdict} / {reference}", flush=True)
        done += len(jobs)
        print(f"{done} cases, {time.monotonic() - started:.0f} s, accepted {counts['OK']}, refused {counts['ERR']}", flush=True)
    peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    peak_mib = peak / (1 << 20) if sys.platform == "darwin" else peak / 1024
    print(f"\n{done} cases from {len(streams)} streams: accepted {counts['OK']}, refused {counts['ERR']}; "
          f"Brotli verdicts agreeing with Google's decoder {agreed}, differing {disagreed}; "
          f"peak decoder memory {peak_mib:.1f} MiB; {len(failures)} failures", flush=True)
    for failure in failures:
        print(f"  {failure}")
    sys.exit(1 if failures or disagreed else 0)


if __name__ == "__main__":
    main()
