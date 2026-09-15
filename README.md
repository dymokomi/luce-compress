# luce-compress

Native Luce Base compression primitives with an owning Luce API.
MIT OR Apache-2.0; see [provenance](NOTICE.md) for the retained MIT source notice.
No zlib/C codec, foreign library or compression subprocess in the runtime.

**Experimental M1a work: whole-buffer zlib encoding/decoding and incremental
raw-DEFLATE/zlib decoding.** Incremental encoding remains unfinished; this is not
yet the completed streaming compression milestone or a full zlib replacement.

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
- `Data.status()` is `finished` for whole-buffer results and the current step
  status for incremental results.

Native callers release returned `interop.Reference[Data]` carriers. Luce owns them
through managed lifetime; `close()` is idempotent. Results and mutable state stay
worker-local. Independent operations may run on multiple threads; one DEFLATE
stream is not automatically parallelized.

## Incremental decoding

`Inflater(framing="zlib", max_input=1073741824, max_output=1073741824)` owns a native
decoder. Git loose objects and pack entries use **zlib** framing. Select
`framing="raw"` only for an enclosing format that specifies unwrapped DEFLATE;
there is no framing autodetection. `feed(input, capacity=65536, final_input=false)` returns an owned
`Data` chunk with `bytes()`, `consumed()` and `status()`:

- `need_input`: the offered input was consumed; supply the next bytes.
- `need_output`: the output chunk filled; reoffer the unconsumed input suffix with
  a positive output capacity. Do not resubmit bytes counted as consumed.
- `finished`: exactly one stream ended. Any unconsumed suffix belongs to the caller;
  reset or create a different decoder for the next stream.

The final-input flag declares an absolute end offset, not a promise that the stream
finishes in this call. It survives output backpressure; later calls can drain with
the unconsumed suffix without repeating the flag. Contradicting that declared end
is an error. Empty input/output chunks are supported. A finished decoder returns
`finished` with zero counts until reset. `reset()` preserves framing/budgets and
clears history, counters, end markers and error state; `close()` is idempotent.

Native zero-copy consumers use `compress_native.make_decoder(...)` and
`Decoder.step(input, output, final_input)` with disjoint caller-owned spans. Its `Step`
contains `consumed`, `produced`, `status`. The core retains a 32 KiB history ring and
bounded bit/Huffman state, not caller pointers or the complete input/output. On the
initial 64-bit targets `sizeof(Decoder)` is 37,960 bytes. Independent streams may
run on separate bounded workers; never mutate/close one instance concurrently.

Streaming total budgets accept nonnegative signed 64-bit values and default to
1 GiB each. These are processed-byte bounds, not allocations of the budget size.
The owning facade limits each input chunk and output capacity to 1 MiB; native
callers control their own span sizes. The caller schedules calls and can stop/close
between them; there is no background worker or asynchronous cancellation.

Parse/budget errors poison a decoder; reset or close it. The current failed call
returns no chunk, but earlier chunks are **untrusted until final validation**. Keep
them quarantined. Raw DEFLATE has no checksum at all and needs an integrity check
from its enclosing format. Successful zlib Adler32 is not cryptographic verification.
`statistics()` exposes processed input/output counts, `finished`, and `failed` for
diagnostics, not authorization or proof that bytes were published.

The facade allocates its output/carrier before stepping, so an allocation error
cannot discard a successfully advanced step. Invalid facade chunk sizes likewise
fail before advancing. Explicit allocation-failure injection is still a follow-up;
sanitizer/lifetime tests are not evidence of every allocator failure path.
See the [contract](docs/STREAMING_CONTRACT.md) and executable
[Luce example](tests/facade.luc) / [native tests](src/luce_compress/stream_tests.lucb).

## Bounds and errors

For the whole-buffer API, input is limited to 1 GiB; the output bound defaults to
64 MiB and may be set to
0–1 GiB. Zero permits an empty decoded result. Validation/limit failures return no
public partial result. The caller's input is never modified. Internal buffers are
released on failures, including result-owner allocation failure.

`invalid`: bad API bound; `corrupt`: malformed/truncated stream, bad checksum or
unexpected trailing bytes; `limit_exceeded`: input/output bound; `unsupported`:
preset dictionary; `closed`: use of a closed native result.

Bounds are per input/output, not an aggregate memory or CPU-time guarantee. The
whole-buffer API retains the complete input and result. Buffer growth can temporarily hold
old and new allocations, encoding also uses a 65,536-entry native-size match table,
and Luce byte copies add memory. Bound concurrency too. Do not use this API as an
unbounded public decompression service.

No gzip wrapper, preset dictionaries, incremental encoder, asynchronous cancellation,
dynamic-Huffman encoder or tuning levels yet. The one-shot encoder still emits zlib,
not raw streams. The image library is not migrated to this package in this slice.

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
Python 3.10+, its zlib module and stock Git are test-only independent oracles. CI runs macOS
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

Incremental tests add every first split and truncated prefix of short fixtures,
one-byte and varying input/output, overwritten borrowed buffers, end-marker
retention through backpressure, poisoned/reset/closed streams, exact total budgets,
32 KiB distance/wrap and cross-block history, raw trailing objects, checksum errors
after producing output and independent raw/zlib mutations. They run in every mode
and under the sanitizer gate, not only against the whole-buffer implementation.
Stock Git also creates loose objects and an undeltified pack in a disposable local
repository; the decoder checks exact zlib boundaries with later pack bytes still
present. This does not implement or validate a complete Git object/pack engine.

## Next commits

1. Incremental encoding with raw-DEFLATE/zlib framing, backpressure and hostile
   input/output chunk-boundary tests.
2. Allocator-failure injection, cooperative work budgets, measured peak memory/latency
   and further fuzzing. Full threaded Git-consumer integration follows in M2a.

M1a remains incomplete until those streaming/limit gates pass. The overall public
plan is in [luce-pkg-server](https://github.com/dymokomi/luce-pkg-server).
