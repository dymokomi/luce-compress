# Provenance

`src/luce_compress/deflate.lucb` is adapted from the Luce Base implementation in
`dymokomi/luce-image`, revision `422e1cf3e580bfcdc72540ac41ef4f70a11a7451`, file
`src/luce_image/deflate.lucb`. That source is Copyright (c) 2026 Dy Mokomi and was
published under MIT; its permission/copyright notice is retained in LICENSE-MIT.
Changes here add bounded variable-size decoding, consumed-byte reporting and
stricter malformed Huffman-tree validation. No image-library source is modified.
The incremental decoder is new Base state-machine code sharing the validated
Huffman builder and format constants with that core; it adds raw/zlib framing,
bounded history, backpressure, end markers and cumulative byte budgets.
The incremental encoder is new Base state-machine code adapting the existing
fixed-Huffman/nearest-match policy to circular history/lookahead and partial output.
The original encoder's MIT provenance and notice above apply to that adaptation.

The bounded buffer and compiler-bootstrap approach are adapted from `luce-db`
revision `d13a1d1ce1116914e2b63bc9dff99dbde816f345` (MIT OR Apache-2.0).
New package work is MIT OR Apache-2.0. No C codec is linked, embedded or invoked by
the runtime. Python's zlib is an independent test oracle only.

Format references: [RFC 1950](https://www.rfc-editor.org/info/rfc1950/) (zlib) and
[RFC 1951](https://www.rfc-editor.org/info/rfc1951/) (DEFLATE). The format tables are
interoperability constants. No reference implementation's C source was copied.
