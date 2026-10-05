#!/usr/bin/env python3
"""Generate src/brotli/dictionary.lucb: Brotli's static dictionary, its 121 word
transforms and the literal context lookups (RFC 7932 sections 7.1 and 8, appendices A
and B).

Usage: tools/brotli_dictionary.py [DICTIONARY.BIN] [RFC7932.TXT]

DICTIONARY.BIN is c/common/dictionary.bin of Google's brotli repository
(https://github.com/google/brotli, MIT) and RFC7932.TXT the RFC's text; both default to
the local donor copies beside this repository (../.donors). The dictionary must match the
RFC's appendix A byte for byte and its CRC-32 (0x5136cb04); the transforms are read from
appendix B and checked against the RFC's CRC-32 of their byte form (0x3d965f81), and
the context lookup tables from section 7.1, checked against their CRC-32s.
"""
from pathlib import Path
import re
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
DONORS = ROOT.parent / ".donors"
OUTPUT = ROOT / "src/brotli/dictionary.lucb"
NDBITS = [0, 0, 0, 0, 10, 10, 11, 11, 10, 10, 10, 10, 10, 9, 9, 8, 7, 7, 8, 7, 7, 6, 6, 5, 5]
KINDS = {"Identity": 0, "FermentFirst": 1, "FermentAll": 2,
         **{f"OmitFirst{k}": 2 + k for k in range(1, 10)}, **{f"OmitLast{k}": 11 + k for k in range(1, 10)}}
LICENSE = """Copyright (c) 2009, 2010, 2013-2016 by the Brotli Authors.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE."""


def appendix(text, start, end):
    """The RFC's text between two headings, page furniture removed."""
    body = text[text.rindex(start):text.rindex(end)]
    return [line for line in body.splitlines() if not line.startswith(("RFC 7932", "Alakuijala")) and "\f" not in line]


def rfc_dictionary(text):
    lines = appendix(text, "Appendix A.  Static Dictionary Data", "Appendix B.  List of Word Transformations")
    return bytes.fromhex("".join(line.strip() for line in lines if re.fullmatch(r"\s+[0-9a-f]{2,64}", line)))


def rfc_transforms(text):
    """[(prefix, kind, suffix)] from appendix B's table."""
    lines = appendix(text, "Appendix B.  List of Word Transformations", "Appendix C.  Computing")
    row = re.compile(r'\s+(\d+)\s+("(?:[^"\\]|\\.)*")\s+(\w+)\s+("(?:[^"\\]|\\.)*")\s*$')
    transforms = []
    for line in lines:
        match = row.match(line)
        if match:
            assert int(match[1]) == len(transforms), line
            literal = lambda s: s[1:-1].encode("latin-1").decode("unicode_escape").encode("latin-1")
            transforms.append((literal(match[2]), KINDS[match[3]], literal(match[4])))
    assert len(transforms) == 121
    serial = b"".join(prefix + b"\0" + bytes([kind]) + suffix + b"\0" for prefix, kind, suffix in transforms)
    assert len(serial) == 648 and zlib.crc32(serial) == 0x3D965F81, "appendix B does not match its CRC-32"
    return transforms


def rfc_context_lookup(text):
    """The four context modes' lookups (section 7.1) as one table: for mode m, entry
    m * 512 + p1 and entry m * 512 + 256 + p2, OR'd, give the literal's context ID."""
    section = text[text.rindex("7.1.  Context Modes"):text.rindex("7.2.  Context ID for Distances")]
    luts = {}
    for name in ("Lut0", "Lut1", "Lut2"):
        body = section[section.index(name + " :="):]
        body = body[body.index(":=") + 2:]
        values = [int(v) for v in re.findall(r"\d+", re.split(r"Lut\d :=|The lengths", body)[0])]
        luts[name] = values[:256]
    for name, crc in (("Lut0", 0x8E91EFB7), ("Lut1", 0xD01A32F4), ("Lut2", 0x0DD7A0D6)):
        assert zlib.crc32(bytes(luts[name])) == crc, f"{name} does not match its CRC-32"
    lsb6 = [p & 0x3F for p in range(256)] + [0] * 256
    msb6 = [p >> 2 for p in range(256)] + [0] * 256
    utf8 = luts["Lut0"] + luts["Lut1"]
    signed = [v << 3 for v in luts["Lut2"]] + luts["Lut2"]
    return lsb6 + msb6 + utf8 + signed


def rows(values, per_line, width):
    return ",\n".join("    " + ", ".join(f"0x{v:0{width}x}" for v in values[i:i + per_line])
                      for i in range(0, len(values), per_line)) + ","


def main():
    binary = Path(sys.argv[1]) if len(sys.argv) > 1 else DONORS / "brotli/c/common/dictionary.bin"
    rfc = Path(sys.argv[2]) if len(sys.argv) > 2 else DONORS / "rfc/rfc7932.txt"
    data = binary.read_bytes()
    text = rfc.read_text(encoding="latin-1")
    offsets = [0]
    for length in range(24):
        offsets.append(offsets[-1] + length * ((1 << NDBITS[length]) if length >= 4 else 0))
    size = offsets[24] + 24 * (1 << NDBITS[24])
    assert len(data) == size == 122784 and zlib.crc32(data) == 0x5136CB04, "not the RFC 7932 dictionary"
    assert data == rfc_dictionary(text), "dictionary.bin differs from RFC 7932 appendix A"
    transforms = rfc_transforms(text)
    lookup = rfc_context_lookup(text)
    # Affixes are stored once each, in first-use order.
    affixes, places = bytearray(), {}
    for prefix, _, suffix in transforms:
        for affix in (prefix, suffix):
            if affix not in places:
                places[affix] = len(affixes)
                affixes += affix
    table = []
    for prefix, kind, suffix in transforms:
        table += [places[prefix], len(prefix), kind, places[suffix], len(suffix)]
    words = [int.from_bytes(data[i:i + 8], "little") for i in range(0, len(data), 8)] + [0]
    license_lines = "\n".join(f"#       {line}".rstrip() for line in LICENSE.splitlines())
    OUTPUT.write_text(f"""#==============================================================================================
#
#   brotli/dictionary - The static dictionary, its word transforms and the literal
#                       context lookups (generated)
#
#   DESCRIPTION:
#       Generated by tools/brotli_dictionary.py from c/common/dictionary.bin of Google's
#       brotli (checked against RFC 7932 appendix A, CRC-32 0x5136cb04) and the RFC's
#       appendix B and section 7.1; do not edit. The dictionary is Google's, under this
#       notice:
#
{license_lines}
#
#==============================================================================================

# mark: Words =================================================================================

## Bits of a word's index by its length (NDBITS); no words shorter than 4 bytes.
let word_bits: u8[25] = [{", ".join(str(b) for b in NDBITS)}]

## Where the words of each length begin in `words` (DOFFSET).
let word_offsets: u32[25] = [{", ".join(str(o) for o in offsets)}]

## The dictionary's {len(data)} bytes, eight to a word, least significant byte first, and
## a word of padding: a word is copied eight bytes at a time.
let words: u64[{len(words)}] = [
{rows(words, 6, 16)}
]

# mark: Transforms ============================================================================

## The 121 transforms: offset and length of the prefix in `affixes`, the elementary
## transform (0 identity, 1 ferment first, 2 ferment all, 3..11 omit the first 1..9
## bytes, 12..20 omit the last 1..9), and offset and length of the suffix.
let transforms: u8[{len(table)}] = [
{rows(table, 15, 2)}
]

## Every prefix and suffix once.
let affixes: u8[{len(affixes)}] = [
{rows(list(affixes), 15, 2)}
]

# mark: Literal contexts ======================================================================

## The literal context ID of each context mode (LSB6, MSB6, UTF8, signed), from RFC 7932
## section 7.1's Lut0, Lut1 and Lut2: `lookup[512 * mode + p1] | lookup[512 * mode + 256 +
## p2]`, where p1 is the last byte and p2 the one before it.
let context_lookup: u8[2048] = [
{rows(lookup, 16, 2)}
]
""")
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(data)} dictionary bytes, {len(transforms)} transforms, {len(affixes)} affix bytes")


if __name__ == "__main__":
    main()
