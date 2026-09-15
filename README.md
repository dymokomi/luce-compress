# luce-compress

Native Luce Base compression primitives with an owning Luce API.
MIT OR Apache-2.0; see [provenance](NOTICE.md) for the retained MIT source notice.
No zlib/C codec, foreign library or compression subprocess in the runtime.

**Experimental first M1a slice: bounded, whole-buffer zlib encoding/decoding.**
This is not yet the streaming compression milestone or a full zlib replacement.

## API

Add a path dependency while the package installer is under construction:

```toml
[dependencies]
luce_compress = "../luce-compress"
```

```luce
from compress import encode, decode

pub func main(arguments: list[str]) -> int!:
    let packed = encode(b"Luce package source")
    let plain = decode(packed.bytes(), max_output = 1024)
    assert(plain.bytes() == b"Luce package source")
    plain.close()
    packed.close()
    return 0
```

- `encode(data, max_output=67108864)`: deterministic zlib stream using a bounded
  32 KiB LZ77 match window and fixed Huffman codes.
- `decode(data, max_output=67108864, allow_trailing=false)`: stored/fixed/dynamic
  DEFLATE blocks in one zlib stream; validates header, trees, backreferences and
  Adler32. Trailing bytes, including another stream, are rejected by default.
- Results own their bytes. `bytes()` borrows them in Base; the Luce bridge copies
  them. `consumed()` is the input-byte count, including zlib header/checksum. With
  `allow_trailing=true`, it stops at the first stream so a caller can frame the next
  object without guessing compressed length. No trailing bytes are decoded.
- `adler32(data)` / `crc32(data)` return nonnegative 64-bit values for Luce
  compatibility. These detect corruption; they are not cryptographic integrity.

Native callers release returned `interop.Reference[Data]` carriers. Luce owns them
through managed lifetime; `close()` is idempotent. Results and mutable state stay
worker-local. Independent operations may run on multiple threads; one DEFLATE
stream is not automatically parallelized.

## Bounds and errors

Input is limited to 1 GiB; the output bound defaults to 64 MiB and may be set to
0–1 GiB. Zero permits an empty decoded result. Validation/limit failures return no
public partial result. The caller's input is never modified. Internal buffers are
released on failures, including result-owner allocation failure.

`invalid`: bad API bound; `corrupt`: malformed/truncated stream, bad checksum or
unexpected trailing bytes; `limit_exceeded`: input/output bound; `unsupported`:
preset dictionary; `closed`: use of a closed native result.

Bounds are per input/output, not an aggregate memory or CPU-time guarantee. This
slice retains the complete input and result. Buffer growth can temporarily hold
old and new allocations, encoding also uses a 65,536-entry native-size match table,
and Luce byte copies add memory. Bound concurrency too. Do not use this API as an
unbounded public decompression service.

No raw-DEFLATE/gzip wrapper, preset dictionaries, incremental feed/drain, cancellation,
dynamic-Huffman encoder or tuning levels yet. These omissions are explicit; the
image library is not migrated to depend on this package in this slice.

## Tests

With pinned sibling `luce-base` and `luce` checkouts:

```sh
python3 tools/bootstrap.py
python3 tests/run.py --mode native0
python3 tests/run.py
python3 tests/sanitize.py
```

Bootstrap writes only this package's ignored build directory, never language
sources. Existing pinned compiler paths can be supplied with `--base` / `--luce`.
Python 3.10+ and its zlib module are test-only independent oracles. CI runs macOS
arm64 and Linux x86-64, all four native optimization modes plus C debug/release.
No Windows support claim is made yet.

Tests include independent encode/decode fixtures across levels/strategies and
32/64 KiB boundaries, exact output limits, checksums, all truncation offsets of a
fixture, malformed Huffman alphabets, empty distance alphabets, reserved symbols,
bad stored lengths, dictionaries, trailing/concatenated streams, bounded expansion,
seeded mutations, native ownership, Luce byte copies and eight independent workers.
AddressSanitizer/UndefinedBehaviorSanitizer run the native API and the full oracle.
Negative tests reject crashes/sanitizer reports rather than counting them as valid
parse failures. This is not a proof of complete coverage or a security review.

## Next commits

1. True incremental decoding with a 32 KiB history ring, explicit consumed/produced
   counts, input/output backpressure, end-of-input semantics and total budgets.
2. Incremental encoding, raw-DEFLATE framing for Git packs, cancellation/cooperative
   budgets and equivalent results across hostile input/output chunk boundaries.
3. Threaded consumer integration, measured peak memory/latency and further fuzzing.

M1a remains incomplete until those streaming/limit gates pass. The overall public
plan is in [luce-pkg-server](https://github.com/dymokomi/luce-pkg-server).
