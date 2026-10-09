#!/usr/bin/env python3
"""Generate src/zstd/vectors.lucb: Zstandard test vectors as tests of the module.

  tools/zstd_vectors.py [--zstd ZSTD_CLI] [--donor DIR]

Three kinds of frame:

* The zstd repository's golden decompression files (tests/golden-decompression and
  tests/golden-decompression-errors, from --donor, a checkout of facebook/zstd): small
  frames exercising corner cases; the error files must fail.
* Reference frames: the `zstd` CLI compressing deterministic inputs (text and binary
  made by a small generator the tests repeat in Luce) at a range of levels, without a
  checksum or content size, with a long window, as several frames and with a skippable
  frame between them.
* The output's length and CRC-32 are what each test expects.

Each vector becomes a `test` block (compiled only for tests). The frames are held as
little-endian 64-bit words.
"""
import argparse
import shutil
import subprocess
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src/zstd/vectors.lucb"


def text(size, seed):
    """Deterministic words: an LCG over a word list (the tests' `sample_text`)."""
    words = [b"the", b"zstd", b"window", b"of", b"and", b"frame", b"<div>", b"</div>", b"sequence", b"\xc3\xa9t\xc3\xa9",
             b"\n", b"for", b"a", b"literal", b"0123", b"http://", b".com/", b"ing ", b"The ", b"block"]
    out, state = bytearray(), seed
    while len(out) < size:
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        out += words[(state >> 16) % len(words)] + b" "
    return bytes(out[:size])


def binary(size, seed):
    """Records: a counter, a small varying field and a noisy byte."""
    out, state = bytearray(), seed
    while len(out) < size:
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        out += (len(out) // 8).to_bytes(4, "little") + bytes([(state >> 16) & 3, 0, (state >> 20) & 0xFF, 7])
    return bytes(out[:size])


def zstd(cli, data, *flags):
    return subprocess.run([cli, "-q", "-c", *flags], input=data, capture_output=True, check=True).stdout


def words(frame):
    padded = frame + bytes(-len(frame) % 8)
    values = [int.from_bytes(padded[i:i + 8], "little") for i in range(0, len(padded), 8)]
    lines = []
    for start in range(0, len(values), 6):
        lines.append("        " + ", ".join(f"0x{v:016x}" for v in values[start:start + 6]) + ",")
    return "\n".join(lines)


def block(name, frame, output):
    """A test that decodes `frame` to `output`, or expects it to fail when output is None."""
    count = len(words(frame).replace("\n", "").split(",")) - 1
    lines = [f'test "{name}":', f"    let frame: u64[{count}] = [", words(frame), "    ]"]
    view = f"u8[]((u8*)&frame[0], {len(frame)})"
    if output is None:
        lines.append(f"    assert(failure_of({view}) == corrupt)")
    else:
        lines.append(f"    try check_vector({view}, {len(output)}, {zlib.crc32(output)})")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zstd", default=shutil.which("zstd"))
    parser.add_argument("--donor", default=str(ROOT.parent / ".donors/zstd"))
    args = parser.parse_args()
    version = subprocess.run([args.zstd, "--version"], capture_output=True, text=True, check=True).stdout.split()
    version = next(word for word in version if word.startswith("v")).rstrip(",")
    tests = []
    donor = Path(args.donor) / "tests"
    for path in sorted((donor / "golden-decompression").glob("*.zst")):
        if path.stat().st_size > 4096:
            continue  # block-128k is built by a test of its own
        frame = path.read_bytes()
        output = subprocess.run([args.zstd, "-d", "-c"], input=frame, capture_output=True, check=True).stdout
        tests.append(block(f"golden {path.name}", frame, output))
    for path in sorted((donor / "golden-decompression-errors").glob("*.zst")):
        tests.append(block(f"golden error {path.name}", path.read_bytes(), None))
    sample = text(12000, 7)
    records = binary(12000, 11)
    for level in [1, 3, 7, 12, 19]:
        tests.append(block(f"text, level {level}", zstd(args.zstd, sample, f"-{level}"), sample))
    tests.append(block("binary, level 3", zstd(args.zstd, records, "-3"), records))
    tests.append(block("binary, level 22", zstd(args.zstd, records, "--ultra", "-22"), records))
    tests.append(block("text without checksum", zstd(args.zstd, sample, "--no-check"), sample))
    tests.append(block("text, long window", zstd(args.zstd, sample, "--long=24", "-5"), sample))
    # Streamed: no content size in the header.
    streamed = subprocess.run([args.zstd, "-q", "-c", "--no-content-size", "-3"], input=sample, capture_output=True, check=True).stdout
    tests.append(block("text without content size", streamed, sample))
    # Two frames with a skippable frame between them.
    skippable = (0x184D2A53).to_bytes(4, "little") + (5).to_bytes(4, "little") + b"luce!"
    joined = zstd(args.zstd, sample[:7000], "-3") + skippable + zstd(args.zstd, records[:9000], "-1")
    tests.append(block("two frames and a skippable frame", joined, sample[:7000] + records[:9000]))
    header = f"""#==============================================================================================
#
#   zstd/vectors - Reference and golden frames (generated tests)
#
#   DESCRIPTION:
#       Generated by tools/zstd_vectors.py; do not edit. The zstd repository's golden
#       decompression files, and frames from the zstd CLI ({version}) over deterministic
#       inputs. Each decodes to the output's length and CRC-32, or fails as corrupt (the
#       frame is held as little-endian 64-bit words).
#
#==============================================================================================
"""
    OUTPUT.write_text(header + "\n" + "\n".join(tests))
    print(f"wrote {OUTPUT} ({len(tests)} vectors)")


if __name__ == "__main__":
    main()
