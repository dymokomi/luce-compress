#!/usr/bin/env python3
"""Decode reference Brotli and gzip streams with tools/codec_tool and compare the output
with the original byte for byte; print a table of the cases by group.

Brotli cases: Google's tests/testdata (*.compressed beside their originals), and
generated ones: every quality (0-11) at every window (10-24) over text, markup,
multilingual UTF-8, binary, incompressible, tiny, zero and periodic inputs; a 20 MB
input at a range of qualities and windows (so 4 MiB and 16 MiB rings wrap); Python's
brotli module in its text, font and generic modes with several block sizes; and streams
with metadata comments. Each is decoded whole and incrementally (4093-byte input pieces,
65521-byte output pieces); the smaller ones also a byte in and a byte out at a time.

gzip cases: /usr/bin/gzip at every level, Python's gzip with every header flag (FEXTRA,
FNAME, FCOMMENT, FHCRC, FTEXT) set alone and together, multi-member files, members of
empty input, and zero padding after the last member.

  python3 tools/conformance.py [--tool build/codec_tool] [--work build/conformance]
                               [--brotli BROTLI_CLI] [--python VENV_PYTHON] [--quick]

The brotli CLI (`brotli`, Google's reference) makes the generated Brotli cases; Python's
brotli module, when the given interpreter has it, adds the mode and block-size cases.
Google's test data is read from ../.donors/brotli (a local clone, never committed).
"""
import argparse
import base64
import gzip
import hashlib
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
TESTDATA = ROOT.parent / ".donors/brotli/tests/testdata"


def inputs():
    """The generated inputs: (group, name, bytes)."""
    rng = random.Random(7932)
    alice = (TESTDATA / "alice29.txt").read_bytes()
    words = alice.split()
    tags = [b"div", b"span", b"a", b"p", b"li", b"table", b"td", b"script", b"style"]
    markup = bytearray(b"<!DOCTYPE html><html><head><title>Brotli</title></head><body>\n")
    while len(markup) < 200000:
        tag = rng.choice(tags)
        markup += b'<%s class="c%d" href="http://www.example.com/%s">%s</%s>\n' % (
            tag, rng.randrange(50), rng.choice(words), b" ".join(rng.choice(words) for _ in range(rng.randrange(1, 12))), tag)
    scripts = ["Brotli est un format de compression ", "Бротли — формат сжатия данных ", "ブロトリは圧縮形式です。",
               "Ο brotli είναι μορφή συμπίεσης ", "ब्रोटली एक संपीड़न प्रारूप है ", "브로틀리는 압축 형식입니다 ", "Brotli ist ein Format "]
    utf8 = "".join(rng.choice(scripts) for _ in range(4000)).encode()
    binary = (TESTDATA / "mapsdatazrh").read_bytes()
    periodic = b"".join(bytes([i % period for i in range(period)]) * (4000 // period) for period in range(1, 40))
    sparse = bytes(rng.randrange(256) if rng.random() < 0.02 else 0 for _ in range(150000))
    yield "text", "alice29", alice
    yield "markup", "html", bytes(markup)
    yield "utf8", "scripts", utf8
    yield "binary", "mapsdatazrh", binary
    yield "binary", "sparse", sparse
    yield "periodic", "periods", periodic
    yield "random", "random64k", rng.randbytes(65536)
    yield "zeros", "zeros300k", bytes(300000)
    for size in (0, 1, 2, 3, 5, 16, 100):
        yield "tiny", f"tiny{size}", (alice[1000:1000 + size] if size != 2 else b"\xff\x00")


def large_input():
    """20 MB: text with variations, markup, binary and incompressible stretches."""
    rng = random.Random(24)
    alice = (TESTDATA / "alice29.txt").read_bytes()
    binary = (TESTDATA / "mapsdatazrh").read_bytes()
    out = bytearray()
    while len(out) < 20_000_000:
        choice = rng.random()
        if choice < 0.4:
            start = rng.randrange(len(alice) - 20000)
            out += alice[start:start + rng.randrange(1000, 20000)].replace(b"the", rng.choice([b"THE", b"teh", b"the"]))
        elif choice < 0.7:
            start = rng.randrange(len(binary) - 50000)
            out += binary[start:start + rng.randrange(1000, 50000)]
        elif choice < 0.85:
            out += rng.randbytes(rng.randrange(100, 30000))
        else:
            out += bytes([rng.randrange(256)]) * rng.randrange(10, 5000)
    return bytes(out[:20_000_000])


class Cases:
    """Compressed cases on disk: (group, packed path, original path, small)."""

    def __init__(self, work):
        self.work = work
        self.items = []

    def original(self, name, data):
        path = self.work / "originals" / name
        if not path.exists() or path.stat().st_size != len(data):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return path

    def add(self, group, packed, original, small):
        self.items.append((group, packed, original, small))


def brotli_cli(cases, cli, quick):
    for group, name, data in inputs():
        original = cases.original(name, data)
        qualities = range(12) if not quick else (0, 5, 11)
        windows = range(10, 25) if not quick else (10, 16, 24)
        for quality in qualities:
            for window in windows:
                packed = cases.work / "brotli" / f"{name}.q{quality}.w{window}.br"
                if not packed.exists():
                    packed.parent.mkdir(parents=True, exist_ok=True)
                    subprocess.run([cli, "-q", str(quality), "-w", str(window), "-c", original],
                                   stdout=packed.open("wb"), check=True)
                cases.add(f"cli {group}", packed, original, len(data) <= 300000)
        # A metadata comment ahead of the data.
        packed = cases.work / "brotli" / f"{name}.comment.br"
        if not packed.exists():
            comment = base64.b64encode(hashlib.sha256(data).digest()[:24]).decode()
            subprocess.run([cli, "-q", "9", "-C", comment, "-c", original], stdout=packed.open("wb"), check=True)
        cases.add("cli metadata", packed, original, True)
    data = large_input()
    original = cases.original("large20m", data)
    for quality in ((0, 1, 3, 5, 9, 11) if not quick else (1, 5)):
        for window in (16, 22, 24):
            packed = cases.work / "brotli" / f"large20m.q{quality}.w{window}.br"
            if not packed.exists():
                subprocess.run([cli, "-q", str(quality), "-w", str(window), "-c", original],
                               stdout=packed.open("wb"), check=True)
            cases.add("cli large 20 MB", packed, original, False)


def brotli_python(cases, python, quick):
    script = r"""
import brotli, sys
data = open(sys.argv[1], 'rb').read()
mode = {'text': brotli.MODE_TEXT, 'font': brotli.MODE_FONT, 'generic': brotli.MODE_GENERIC}[sys.argv[3]]
packed = brotli.compress(data, mode=mode, quality=int(sys.argv[4]), lgwin=int(sys.argv[5]), lgblock=int(sys.argv[6]))
open(sys.argv[2], 'wb').write(packed)
"""
    for group, name, data in inputs():
        if group in ("tiny", "zeros"):
            continue
        original = cases.original(name, data)
        for mode in ("text", "font", "generic"):
            for quality in ((4, 9, 11) if not quick else (11,)):
                for lgblock in (0, 16, 24):
                    packed = cases.work / "brotli-py" / f"{name}.{mode}.q{quality}.b{lgblock}.br"
                    if not packed.exists():
                        packed.parent.mkdir(parents=True, exist_ok=True)
                        subprocess.run([python, "-c", script, original, packed, mode, str(quality), "22", str(lgblock)], check=True)
                    cases.add(f"python {mode}", packed, original, True)


def google_testdata(cases):
    for packed in sorted(TESTDATA.glob("*.compressed*")):
        original = TESTDATA / packed.name.split(".compressed")[0]
        cases.add("google testdata", packed, original, True)


def gzip_cases(cases, quick):
    """gzip members from /usr/bin/gzip and Python's gzip, and hand-made headers."""
    rng = random.Random(1952)
    samples = [(name, data) for group, name, data in inputs() if group != "random" or True]
    for name, data in samples:
        original = cases.original(name, data)
        for level in (range(1, 10) if not quick else (1, 6, 9)):
            packed = cases.work / "gzip" / f"{name}.gz{level}"
            if not packed.exists():
                packed.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["/usr/bin/gzip", "-c", f"-{level}", "-n" if level % 2 else "-N", original],
                               stdout=packed.open("wb"), check=True)
            cases.add("gzip cli", packed, original, True)
        # Every header flag alone, and all together.
        for flags in (0, 1, 2, 4, 8, 16, 31):
            packed = cases.work / "gzip" / f"{name}.flags{flags}.gz"
            if not packed.exists():
                packed.write_bytes(member(data, flags, rng))
            cases.add("gzip header flags", packed, original, True)
    # Multi-member: several members of pieces, members of nothing, then zero padding.
    alice = (TESTDATA / "alice29.txt").read_bytes()
    for parts in (2, 3, 7):
        cuts = sorted(rng.sample(range(len(alice)), parts - 1))
        pieces = [alice[a:b] for a, b in zip([0, *cuts], [*cuts, len(alice)])]
        packed = cases.work / "gzip" / f"multi{parts}.gz"
        packed.write_bytes(b"".join(gzip.compress(piece, rng.choice([1, 6, 9])) for piece in pieces))
        cases.add("gzip multi-member", packed, cases.original("alice29", alice), True)
    packed = cases.work / "gzip" / "multi-empty.gz"
    packed.write_bytes(gzip.compress(b"") + gzip.compress(alice[:5000]) + gzip.compress(b"") + bytes(512))
    cases.add("gzip multi-member", packed, cases.original("alice5000", alice[:5000]), True)
    packed = cases.work / "gzip" / "cli-concatenated.gz"
    first = subprocess.run(["/usr/bin/gzip", "-c", "-9"], input=alice[:70000], capture_output=True, check=True).stdout
    second = subprocess.run(["/usr/bin/gzip", "-c", "-1"], input=alice[70000:], capture_output=True, check=True).stdout
    packed.write_bytes(first + second)
    cases.add("gzip multi-member", packed, cases.original("alice29", alice), True)


def member(data, flags, rng):
    """One gzip member with header `flags` (bit 0 FTEXT, 1 FHCRC, 2 FEXTRA, 3 FNAME,
    4 FCOMMENT)."""
    header = bytearray(b"\x1f\x8b\x08" + bytes([flags]) + struct.pack("<I", 1700000000) + bytes([2, 3]))
    if flags & 4:
        extra = b"AB" + struct.pack("<H", 5) + b"hello" + b"CD" + struct.pack("<H", 0)
        header += struct.pack("<H", len(extra)) + extra
    if flags & 8:
        header += b"name-\xe9\xe8.txt\0"
    if flags & 16:
        header += b"a comment, " + bytes(rng.randrange(1, 256) for _ in range(40)) + b"\0"
    if flags & 2:
        header += struct.pack("<H", zlib.crc32(header) & 0xFFFF)
    body = zlib.compressobj(6, zlib.DEFLATED, -15)
    return bytes(header) + body.compress(data) + body.flush() + struct.pack("<II", zlib.crc32(data), len(data) & 0xFFFFFFFF)


def decode_all(tool, cases, work, gzip_mode):
    """Run every case through the tool in each mode; [(group, mode, ok)]."""
    out = work / "decoded"
    out.mkdir(parents=True, exist_ok=True)
    results = []
    modes = ["", "/4093/65521", "/1/1"]
    for mode in modes:
        jobs = [(group, packed, original) for group, packed, original, small in cases.items
                if mode != "/1/1" or small]
        listing = work / "list.txt"
        lines = []
        for index, (group, packed, original) in enumerate(jobs):
            kind = "gzip" if group.startswith("gzip") else "brotli"
            lines.append(f"{kind}{mode} {packed} {out / str(index)}")
        listing.write_text("\n".join(lines) + "\n")
        run = subprocess.run([tool, "batch", listing], capture_output=True, text=True, timeout=3600)
        verdicts = run.stdout.splitlines()
        if run.returncode != 0 or len(verdicts) != len(jobs):
            sys.exit(f"codec_tool failed ({run.returncode}): {run.stderr[-2000:]}")
        for index, ((group, packed, original), verdict) in enumerate(zip(jobs, verdicts)):
            decoded = out / str(index)
            fields = verdict.split()
            ok = (fields[0] == "OK" and int(fields[1]) == packed.stat().st_size
                  and decoded.read_bytes() == original.read_bytes())
            if not ok:
                print(f"FAIL {mode or 'whole'} {packed}: {verdict}", flush=True)
            results.append((group, mode or "whole", ok))
            decoded.unlink(missing_ok=True)
    return results


def table(results):
    groups = {}
    for group, mode, ok in results:
        row = groups.setdefault(group, {})
        passed, total = row.get(mode, (0, 0))
        row[mode] = (passed + ok, total + 1)
    modes = ["whole", "/4093/65521", "/1/1"]
    print(f"\n{'group':<22}" + "".join(f"{m:>16}" for m in modes))
    failures = 0
    for group in sorted(groups):
        cells = []
        for mode in modes:
            passed, total = groups[group].get(mode, (0, 0))
            failures += total - passed
            cells.append(f"{passed}/{total}" if total else "-")
        print(f"{group:<22}" + "".join(f"{c:>16}" for c in cells))
    total = sum(t for row in groups.values() for _, t in row.values())
    print(f"\n{total - failures}/{total} decodes byte for byte", flush=True)
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tool", type=Path, default=ROOT / "build/codec_tool")
    parser.add_argument("--work", type=Path, default=ROOT / "build/conformance")
    parser.add_argument("--brotli", default=shutil.which("brotli"))
    parser.add_argument("--python", default=None, help="an interpreter with the brotli module")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--only", choices=["brotli", "gzip"])
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    cases = Cases(args.work)
    if args.only != "gzip":
        google_testdata(cases)
        if args.brotli:
            brotli_cli(cases, args.brotli, args.quick)
        if args.python:
            brotli_python(cases, args.python, args.quick)
    if args.only != "brotli":
        gzip_cases(cases, args.quick)
    failures = table(decode_all(args.tool.resolve(), cases, args.work, False))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
