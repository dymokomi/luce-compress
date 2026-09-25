# luce-compress

Native Luce Base compression primitives with an owning Luce API.
MIT OR Apache-2.0; see [provenance](NOTICE.md) for the retained MIT source notice.
No zlib/C codec, foreign library or compression subprocess in the runtime.

**Experimental M1a work: whole-buffer zlib encoding/decoding and incremental
raw-DEFLATE/zlib encoding/decoding, with cooperative work budgets and deterministic
allocation-failure tests.** Resource, larger-stream and seeded fuzz tests are included;
this is not yet the completed compression milestone or a full zlib replacement.

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
there is no framing autodetection. `feed(input, capacity=65536, final_input=false,
work_limit=4096)` returns an owned `Data` chunk with `bytes()`, `consumed()`,
`status()` and `work_units()`:

- `need_input`: the offered input was consumed; supply the next bytes.
- `need_output`: the output chunk filled; reoffer the unconsumed input suffix with
  a positive output capacity. Do not resubmit bytes counted as consumed.
- `finished`: exactly one stream ended. Any unconsumed suffix belongs to the caller;
  reset or create a different decoder for the next stream.
- `yielded`: the operation allowance was used. Requeue the owner, then reoffer the
  unconsumed suffix. Zero consumed/produced bytes are legal; this is not a request
  for more input. All callers must handle this status, including with default limits.

The final-input flag declares an absolute end offset, not a promise that the stream
finishes in this call. It survives output backpressure; later calls can drain with
the unconsumed suffix without repeating the flag. Contradicting that declared end
is an error. Empty input/output chunks are supported. A finished decoder returns
`finished` with zero counts until reset. `reset()` preserves framing/budgets and
clears history, counters, end markers and error state; `close()` is idempotent.

Native zero-copy consumers use `compress_native.make_decoder(...)` and
`Decoder.step(input, output, final_input, work_limit)` with disjoint caller-owned spans.
The last two arguments default to `false` and `4096`. Its `Step` contains `consumed`,
`produced`, `status`, `work_units`. The core retains a 32 KiB history ring and
bounded bit/Huffman state, not caller pointers or the complete input/output. On the
initial 64-bit targets `sizeof(Decoder)` is 37,960 bytes. Independent streams may
run on separate bounded workers; never mutate/close one instance concurrently.

Streaming total budgets accept nonnegative signed 64-bit values and default to
1 GiB each. These are processed-byte bounds, not allocations of the budget size.
The owning facade limits each input chunk and output capacity to 1 MiB; native
callers control their own span sizes. The caller schedules calls and can stop/close
between them; there is no background worker or asynchronous cancellation.

`work_limit` accepts 1–65,536 bounded state-machine dispatches per call; invalid
values reject before mutation or facade allocation. `yielded` reports exactly the
chosen allowance; already finished streams report zero work. Native steps allocate
nothing. This is an operation bound, **not a millisecond deadline**: constructor,
reset, facade allocation/managed copies, caller I/O and aggregate concurrency are
outside it. See the [precise counting and scheduling contract](docs/STREAMING_CONTRACT.md#cooperative-scheduling-contract).
The whole-buffer API is not cooperative; its result reports zero counted step work.

Parse/budget errors poison a decoder; reset or close it. The current failed call
returns no chunk, but earlier chunks are **untrusted until final validation**. Keep
them quarantined. Raw DEFLATE has no checksum at all and needs an integrity check
from its enclosing format. Successful zlib Adler32 is not cryptographic verification.
`statistics()` exposes processed input/output counts, `finished`, and `failed` for
diagnostics, not authorization or proof that bytes were published.

The facade allocates its output/carrier before stepping, so an allocation error
cannot discard a successfully advanced step. Invalid facade chunk sizes likewise
fail before advancing. Deterministic Base-heap failure tests now sweep the actual
construction/result/growth allocations, including the native reference shell;
see [failure coverage and its limits](docs/ALLOCATION_FAILURES.md).
See the [contract](docs/STREAMING_CONTRACT.md) and executable
[Luce example](tests/facade.luc) / [native tests](src/luce_compress/stream_tests.lucb).

## Incremental encoding

`Deflater(framing="zlib", max_input=1073741824, max_output=1073741824)` has the same
owning `feed`, `reset`, `close`, `statistics` and `Data` chunk interface as `Inflater`.
Native consumers use `compress_native.make_encoder(...)`, returning an owning
`Encoder` handle with `step(input, output, final_input=false, work_limit=4096)`. Do not copy this handle or
share it across workers; its `close()` releases its two native allocations and is
idempotent on that handle. The decoder remains a fixed-state value, not a handle.

The encoder retains a 65,536-entry match table, 32 KiB history, 258-byte circular
lookahead and bounded pending bits. `encoder_storage_bytes()` is 557,448 bytes on
the initial 64-bit targets, including the handle but excluding allocator metadata
and caller buffers. The table is a separate allocation to avoid a large struct
initializer on small worker stacks. There are no allocations during native `step`;
reset clears/reuses state. Eight independent 512 KiB-stack workers exercise this.

It emits one final fixed-Huffman block with LZ77 matches, with optional zlib framing.
For a given input and framing, compressed bytes do not depend on chunk partitions,
empty calls or output capacity; the match policy agrees with the whole-buffer
encoder. It starts producing output before EOF once it has sufficient lookahead,
without retaining the whole source. Fixed codes can expand incompressible inputs;
there is no claim of optimal compression or a stored-block fallback in this version.

An explicit final-input declaration is required: reaching `max_input` does not
implicitly end the source. After accepting exactly that budget, `need_input` can
mean that an empty final call is needed; an additional source byte is rejected.
EOF declarations survive output backpressure just as in the decoder. Successful
input counts include up to 258 bytes of retained lookahead; output counts include
only bytes delivered to the caller. Pending bits/lookahead can remain after a call.
The same per-chunk 1 MiB facade cap, poisoned-error and quarantine rules apply.
No sync/full-flush operation, dictionary, dynamic-Huffman encoder or tuning level
is exposed. Git compatibility tests cover zlib loose objects and undeltified pack
entries only, not a production Git engine.

## Fast whole-buffer DEFLATE for codecs (`flate`)

`import flate` (Base) is for callers that know their sizes and frame their own data,
as PNG, TIFF and OpenEXR do:

```luce
import flate

let out = try alloc u8[flate.deflate_bound(data.length) + 6] in memory.heap
let used = try flate.deflate_zlib(data, 6, out)          # a zlib stream at level 0..9
try flate.inflate_zlib(out[..<used], plain)              # into exactly the plain size

# Independent segments (a fresh window each), joined into one stream as pigz does:
var at = try flate.deflate_raw(first, 6, buffer, false)  # ends in a sync flush
at += try flate.deflate_raw(second, 6, buffer[at..], true)
let adler = flate.adler32_combine(flate.adler32(first), flate.adler32(second), second.length)
```

- `inflate_raw(data, output, progress = none, context = none) -> usize` decodes raw
  DEFLATE into exactly `output` through 12-bit lookup tables and a 64-bit bit buffer,
  returning the input it used; it stops after a final block or at the end of the
  input (a segment). `progress(context, bytes)` hears of every 256 KiB, for callers
  that work on the output as it arrives. `inflate_zlib` adds the header and Adler-32.
- `deflate_raw(input, level, output, last) -> usize` is zlib's algorithm and level
  table with four-byte hash chains: greedy matching at levels 1..3, lazy at 4..9,
  and each block written dynamic, fixed or stored, whichever is smallest. Files come
  out within a percent of zlib's at the same level (usually smaller) in less time.
- `crc32(data, crc = 0)` (slicing by eight), `adler32(data, adler = 1)` and
  `adler32_combine` run several bytes a step.

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

No gzip wrapper, preset dictionaries, asynchronous cancellation,
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

Encoder tests independently stream-decode Base output through Python/zlib, compare
compressed bytes across partitions and against the previous deterministic policy,
exercise every first split around short/lookahead fixtures, exact and insufficient
budgets, overwritten spans, canaries, reset/close and concurrent independent owners.
Stock Git reads Base-encoded loose objects and validates/indexes a separately framed
pack; a second empty repository verifies packed reads cannot fall back to loose data.

An additional 928 independent work-budget cases run one-unit, varying and default
allowances across raw/zlib stored/fixed/dynamic fixtures, exact splits/truncations,
empty-block chains, checksum/limit errors and deterministic encoder output. Together
the five oracle groups contain 6,000 cases per mode. Native and Luce suites cover
zero-I/O yields, cancellation/reset, retained chunks and eight independent workers.

The separate single-threaded allocation test executable runs 388 failure/retry
cases. It replaces the test process's Base heap with a fixed-size tracking allocator,
refuses each allocation in observed traces in both one-shot and persistent-failure
modes, and verifies exact frees and state-safe retries. It also exercises late
codec-error cleanup and proves native step/reset/close make no allocation attempts.
The production library has no test hooks or new allocator dependency. This does
not simulate process-wide OOM, Luce managed-runtime trap-on-exhaustion, OS resource
failures, or concurrent replacement of the process-global heap.

A generated-stream stress driver uses fixed 32 KiB spans, independent worker-owned
codec pairs and eight 512 KiB-stack workers. Five cases run in every compiler mode,
under sanitizers and in the VPS bundle. The full native-opt-3 profile adds sustained
16/128 MiB workloads and a 4 GiB + 1 byte logical stream, without large temporary
files. It checks process peak RSS and records step-latency histograms and paired
pipeline throughput. See [RESOURCES.md](docs/RESOURCES.md) for exact ceilings,
measurement units, exclusions and commands; these are not production SLOs.

Independent decoder fuzzing adds 4,096 seeded cases per mode, under ASan/UBSan and
in the prebuilt suite. Independent larger-file tests add 24 exact-byte/budget cases
at 1 MiB + 1 byte. Both CI hosts also run 65,536 mutations with a second seed and
48 file-stream cases through 16 MiB + 3 bytes. Failures must be normal codec
rejections, never signals or sanitizer findings. See [FUZZING.md](docs/FUZZING.md)
for corpus identities, bounded oracle behavior, retained reproducers and exclusions.
See [VALIDATION.md](docs/VALIDATION.md) for completed revision-specific evidence;
test definitions alone are not a claim that every deployment gate has passed.

## Next commits

1. Close the remaining M0 contracts before marking the dependent M1a milestone
   complete. The expanded codec gates passed locally, on Linux/macOS CI and in the
   isolated VPS suite at `b04e20e`; see the revision-specific validation record.
2. Full threaded Git-consumer integration and aggregate server admission follow
   in M2a/M3a, after their crypto/storage prerequisites.

M1a remains incomplete while its M0 prerequisite is open. The overall public
plan is in [luce-pkg-server](https://github.com/dymokomi/luce-pkg-server).
