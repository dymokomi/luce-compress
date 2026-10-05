#!/usr/bin/env python3
"""Generate src/brotli/vectors.lucb: Brotli test vectors as tests of the module.

  tools/brotli_vectors.py [--brotli BROTLI_CLI] [--python VENV_PYTHON]

Two kinds of stream:

* Reference streams: Google's `brotli` CLI compressing deterministic inputs (text and
  binary made by a small generator the tests repeat in Luce) at a range of qualities
  and windows, one with a metadata comment.
* A crafted stream that names a static dictionary word of every length (4-24) through
  each of the 121 transforms, written here with simple and single-length prefix codes.
  Google's decoder (Python's brotli module) must accept it; its output's CRC-32 and
  length are what the test expects.

Each vector becomes a `test` block (compiled only for tests) that decodes the stream
whole and in small pieces and checks the output's length and CRC-32.
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src/brotli/vectors.lucb"
NDBITS = [0, 0, 0, 0, 10, 10, 11, 11, 10, 10, 10, 10, 10, 9, 9, 8, 7, 7, 8, 7, 7, 6, 6, 5, 5]
COPY_BASE = [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 18, 22, 30, 38, 54, 70, 102, 134, 198, 326, 582, 1094, 2118]
COPY_EXTRA = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 7, 8, 9, 10, 24]


def text(size, seed):
    """Deterministic words: an LCG over a word list."""
    words = [b"the", b"brotli", b"window", b"of", b"and", b"stream", b"<div>", b"</div>", b"compression", b"\xc3\xa9t\xc3\xa9",
             b"\xd0\xb4\xd0\xb0", b"\n", b"for", b"a", b"dictionary", b"0123", b"http://", b".com/", b"ing ", b"The "]
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


class Bits:
    def __init__(self):
        self.value, self.count = 0, 0

    def put(self, value, bits):
        assert 0 <= value < (1 << bits) or bits == 0
        self.value |= value << self.count
        self.count += bits

    def bytes(self):
        return self.value.to_bytes((self.count + 7) // 8, "little")


def distance_code(distance):
    """Distance symbol and extra bits for NPOSTFIX 0, NDIRECT 0 (section 4)."""
    for symbol in range(16, 64):
        bits = 1 + ((symbol - 16) >> 1)
        offset = ((2 + ((symbol - 16) & 1)) << bits) - 4
        if offset < distance <= offset + (1 << bits):
            return symbol, distance - offset - 1, bits
    raise ValueError(distance)


def every_transform():
    """A stream of one meta-block per word length, each naming one word through every
    transform (insert nothing, copy a dictionary word)."""
    sys.path.insert(0, str(ROOT / "tools"))
    import brotli_dictionary
    rfc = (ROOT.parent / ".donors/rfc/rfc7932.txt").read_text(encoding="latin-1")
    table = brotli_dictionary.rfc_transforms(rfc)

    def produced(length, transform):
        prefix, kind, suffix = table[transform]
        word = length
        if 3 <= kind <= 11:
            word = max(0, word - (kind - 2))
        elif kind >= 12:
            word = max(0, word - (kind - 11))
        return len(prefix) + word + len(suffix)

    bits = Bits()
    bits.put(0b0100001, 7)  # WBITS 10: windows wrap
    window = (1 << 10) - 16
    total = 0
    for length in range(4, 25):
        code = next(c for c in range(24) if COPY_BASE[c] <= length < COPY_BASE[c] + (1 << COPY_EXTRA[c]))
        symbol = 128 + code if code < 8 else 192 + code - 8 if code < 16 else 384 + code - 16
        size = sum(produced(length, t) for t in range(121))
        bits.put(0, 1)  # ISLAST
        nibbles = max(4, (size - 1).bit_length() + 3 >> 2)
        bits.put(nibbles - 4, 2)
        bits.put(size - 1, nibbles * 4)
        bits.put(0, 1)  # ISUNCOMPRESSED
        for _ in range(3):
            bits.put(0, 1)  # NBLTYPES = 1
        bits.put(0, 2)  # NPOSTFIX
        bits.put(0, 4)  # NDIRECT
        bits.put(2, 2)  # literal context mode UTF8
        bits.put(0, 1)  # NTREESL = 1
        bits.put(0, 1)  # NTREESD = 1
        bits.put(1, 2); bits.put(0, 2); bits.put(ord("x"), 8)  # literals: one symbol
        bits.put(1, 2); bits.put(0, 2); bits.put(symbol, 10)  # commands: one symbol
        # Distances: 64 symbols of 6 bits, a code length code of the single length 6.
        bits.put(0, 2)  # HSKIP 0
        for value in (1, 2, 3, 4, 0, 5, 17, 6, 16, 7, 8, 9, 10, 11, 12, 13, 14, 15):
            if value == 6:
                bits.put(0b10, 2)  # code length 3 (any one nonzero length)
            else:
                bits.put(0, 2)
        for transform in range(121):
            index = (transform * 37 + length * 11) % (1 << NDBITS[length])
            word_id = (transform << NDBITS[length]) | index
            reach = min(total, window)
            distance_symbol, extra, extra_bits = distance_code(reach + 1 + word_id)
            bits.put(length - COPY_BASE[code], COPY_EXTRA[code])
            reversed_code = int(f"{distance_symbol:06b}"[::-1], 2)
            bits.put(reversed_code, 6)
            bits.put(extra, extra_bits)
            total += produced(length, transform)
    bits.put(0b11, 2)  # ISLAST, ISLASTEMPTY
    return bits.bytes()


def rows(data):
    """`data` as little-endian 64-bit words, six to a line."""
    data = data + bytes(-len(data) % 8)
    words = [int.from_bytes(data[i:i + 8], "little") for i in range(0, len(data), 8)]
    return ",\n".join("        " + ", ".join(f"0x{w:016x}" for w in words[i:i + 6]) for i in range(0, len(words), 6)) + ","


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brotli", default=shutil.which("brotli"))
    parser.add_argument("--python", required=True, help="an interpreter with the brotli module")
    args = parser.parse_args()
    vectors = []
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "input"
        for name, kind, size, seed, options in [
                ("text, quality 0, window 10", "text", 10000, 1, ["-q", "0", "-w", "10"]),
                ("text, quality 1, window 16", "text", 10000, 2, ["-q", "1", "-w", "16"]),
                ("text, quality 5, window 18", "text", 10000, 3, ["-q", "5", "-w", "18"]),
                ("text, quality 9, window 22", "text", 10000, 4, ["-q", "9", "-w", "22"]),
                ("text, quality 11, window 10", "text", 10000, 5, ["-q", "11", "-w", "10"]),
                ("text, quality 11, window 24, metadata", "text", 10000, 6, ["-q", "11", "-w", "24", "-C", "THVjZSBjb21wcmVzcw=="]),
                ("binary, quality 4, window 12", "binary", 12000, 7, ["-q", "4", "-w", "12"]),
                ("binary, quality 11, window 16", "binary", 12000, 8, ["-q", "11", "-w", "16"])]:
            data = text(size, seed) if kind == "text" else binary(size, seed)
            source.write_bytes(data)
            packed = subprocess.run([args.brotli, *options, "-c", source], capture_output=True, check=True).stdout
            vectors.append((name, kind, size, seed, packed, data))
        crafted = every_transform()
        check = "import brotli, sys; sys.stdout.buffer.write(brotli.decompress(sys.stdin.buffer.read()))"
        expected = subprocess.run([args.python, "-c", check], input=crafted, capture_output=True, check=True).stdout
        vectors.append(("every transform of a word of every length", "crafted", len(expected), 0, crafted, expected))
    blocks = []
    for name, kind, size, seed, packed, data in vectors:
        blocks.append(f'''test "{name}":
    let stream: u64[{(len(packed) + 7) // 8}] = [
{rows(packed)}
    ]
    try check_vector(u8[]((u8*)&stream[0], {len(packed)}), {len(data)}, {zlib.crc32(data)})
''')
    OUTPUT.write_text(f"""#==============================================================================================
#
#   brotli/vectors - Reference and crafted streams (generated tests)
#
#   DESCRIPTION:
#       Generated by tools/brotli_vectors.py; do not edit. Streams from Google's brotli CLI
#       (version {subprocess.run([args.brotli, "--version"], capture_output=True, text=True).stdout.split()[-1]}) over deterministic inputs, and a crafted stream naming a
#       dictionary word of every length through each of the 121 transforms, which Google's
#       decoder accepts. Each decodes whole and in pieces to the output's length and CRC-32 (the stream is held
#       as little-endian 64-bit words).
#
#==============================================================================================

{chr(10).join(blocks)}""")
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(vectors)} vectors")


if __name__ == "__main__":
    main()
