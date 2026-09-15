# Deterministic allocation-failure contract

The test executable `src/luce_compress/failure_tests.lucb` is entirely Luce Base and
uses the existing `memory.Allocator` interface. It temporarily replaces the Base
heap **inside its own single-threaded test process**. Production code and either
language's sources are unchanged. Do not run this heap replacement concurrently:
`memory.heap` is process-global, and allocator witnesses must outlive their owners.

The interceptor forwards successful requests to the saved heap and records live
addresses, exact block sizes, alignment, counts and requested live bytes in a fixed
64-slot ledger. The ledger itself allocates nothing. Duplicate/foreign frees,
incorrect release sizes, duplicate live addresses and ledger exhaustion fail the
test. All audited allocations must be released before the original heap is restored.
Inputs/reference fixtures are owned by the saved allocator outside this scope.

Each observed allocation position is refused in two modes: exactly once, or from
that position onward. Tests require an actual refusal, the expected `memory.exhausted`
error, exact unwind to the live-allocation baseline and successful reuse once the
fault is disabled. Baseline allocation-count lower bounds prevent accidentally
turning a sweep into a no-op. A failpoint just beyond the observed one-shot trace
must not fire. This is deterministic fault injection, not probabilistic memory stress.

## Covered paths

- `Inflater`, `Deflater` and the native encoder factory, including failure of the
  second encoder allocation after the control/history allocation succeeds.
- Every allocation in representative whole-buffer encode/decode traces, including
  multiple buffer growths, the match table, native `Data` and interop reference
  shell. Empty results, output-budget errors and late checksum errors are included.
- Failed buffer growth preserves existing storage and bytes; a subsequent growth
  succeeds and frees the original storage exactly once.
- Both raw/zlib owning facades, with zero/one/larger output capacity and refusal at
  initial, intermediate and final draining steps. Exact counters/flags are unchanged
  on allocation refusal, and complete retried output matches the clean fixture.
- Failure of an EOF-bearing `feed` followed by a shorter **nonfinal** retry proves
  the original EOF declaration did not reach the native state machine.
- Failed result allocations after stream completion leave it finished; retry is
  still an empty finished result and never consumes a new stream.
- Invalid chunk sizes and closed handles reject before allocating.
- Later checksum/output-budget failures dispose the unpublished result but preserve
  earlier owning chunks; reset/close and repeated result close remain safe.
- Native encoder/decoder step, reset and close succeed with an armed allocator that
  would refuse its first request; the test requires **zero allocation attempts**.

There are 368 counted failure/retry cases plus direct buffer/native no-allocation
assertions and clean replay traces. Each compiler mode runs the separate executable,
as do the sanitizer and prebuilt VPS suites. The regular 5,072 codec fixture cases,
high-level Luce consumer and threaded/lifetime suites continue to run independently.

## Limits of this evidence

The interceptor tests Base-heap requests on these paths, including native ownership
shell allocation. It does not inject failures into OS/libc internals, process startup,
the sanitizer runtime or Luce managed-wrapper/GC allocations whose language policy
may be trap-on-exhaustion. It does not change the system allocator, exhaust host RAM,
or test concurrent mutation of the global heap. Thread safety is tested separately
with independent stream owners; no thread is started while this interceptor is active.

The ledger's peak is the sum of requested live bytes **within the audited scope**,
not process RSS, allocator metadata, stack use, unrelated buffers or an aggregate
server memory bound. Large/concurrent workload resource measurements and cooperative
work limits remain separate gates. A finite set of fault traces is not a claim of
exhaustive behavior for every possible input, memory condition or runtime path.

After bootstrapping the pinned compilers, a focused run is:

```sh
build/toolchain/luce-base build src/luce_compress/failure_tests.lucb --native --opt 0 -o build/failure-tests
build/failure-tests
```

Use `python3 tests/run.py` and `python3 tests/sanitize.py` for the full supported
matrix. Publication evidence belongs in [VALIDATION.md](VALIDATION.md).
