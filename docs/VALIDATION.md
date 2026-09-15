# Compression validation history

## Initial codec core — 2026-09-14

Source revision: `1aeee566590e7b3d18182ace2da3629c0d53202b`.
[CI run 34921226527](https://github.com/dymokomi/luce-compress/actions/runs/34921226527)
passed on Ubuntu 24.04 x86-64 and macOS 15 arm64. Compiler revisions are pinned in
`bootstrap/`; both compiler source repositories and `luce-image` remained unchanged.

All six modes passed locally and on both CI hosts: native opt 0, 1, 2, 3 and C
debug/release. Each independently rebuilt and ran 646 zlib/corruption/limit/mutation
cases, a native checksum/ownership/empty-buffer suite, eight independent worker
contexts and a high-level Luce consumer. The full 646-case oracle and native suite
also passed AddressSanitizer + UndefinedBehaviorSanitizer locally and in both CI
jobs. Test-only Python/zlib is independent of the native Base codec implementation.
This is not ThreadSanitizer coverage or a claim of exhaustive fuzz/security review.

Coverage includes all input/output bounds tested by the fixtures, 32/64 KiB corpus
boundaries, level/strategy interoperability, checksums, exact consumed-byte counts,
strict/trailing/concatenated framing, all truncation offsets of a representative
stream, malformed code-length trees, valid one-symbol/empty-distance trees,
missing end marker, reserved codes, absent backreference history, invalid stored
lengths, unsupported dictionaries, bounded expansion and 256 seeded mutations.
Expected parse failures must exit normally; sanitizer findings/signals are failures.

The successful Linux job produced a public prebuilt native-opt-3 test bundle:
SHA256 `aa9a136c71cf423462f0ecc2b2c2eea14f1e91f2dd514596e2250529b0e60c1c`.
After verifying the revision and archive/per-file hashes, the full prebuilt suite
passed on the owner's existing Ubuntu 24.04 Lightsail VPS. It ran as a transient
dynamic user with private networking/tmp, read-only host/input, inaccessible live
application/home paths, no capabilities, 512 MiB memory maximum, no swap, 25% CPU
quota, 64-task limit, idle I/O priority and a 180-second deadline. No compiler or
dependency installation occurred. Systemd reported 6.506 seconds elapsed and 1.634
seconds CPU for the complete suite; these are smoke-test observations, not codec
throughput or production capacity measurements.

The staging directory was removed and the transient service was absent/inactive.
All 32 previous services remained running. Caddy's PID/activation/configuration hash
were unchanged, and the existing site still returned HTTPS 200 with the same ETag.
No DNS, proxy, firewall, production data or live service configuration was modified.

At this initial checkpoint M1a was incomplete: the evidence covered a bounded
whole-buffer core, not incremental streaming, raw-DEFLATE framing, Git-pack
integration, cancellation, aggregate memory guarantees, performance targets or
production security. The next checkpoint below adds incremental decoding.

## Incremental raw-DEFLATE/zlib decoder — 2026-09-14 PDT / 2026-09-15 UTC

Source revision: `0752de3a30e431b076eb21c32978bbaf0909ce02`.
[CI run 34922729249](https://github.com/dymokomi/luce-compress/actions/runs/34922729249)
passed on Ubuntu 24.04 x86-64 and macOS 15 arm64, using the same pinned compiler
sources. No language or image source changes were needed.

The native state machine resumes partial fields, Huffman symbols, stored blocks
and overlapping matches without replaying input. It retains 37,960 bytes of state
on both initial 64-bit targets, including a 32 KiB history ring; the core performs
no heap allocation and retains no caller pointers. Explicit raw/zlib framing,
consumed/produced counts, input/output backpressure, sticky absolute final-input
offsets, checked total budgets, poisoned errors and reset/close are implemented.
The owning `Inflater` exposes this to Luce and allocates each result before stepping.

Local and both hosted CI runs passed all six compiler modes. Every mode runs:

- The previous 646 whole-buffer oracle/corruption/limit/mutation cases.
- 1,846 incremental cases: raw/zlib, stored/fixed/dynamic blocks, every first split
  and truncated prefix of representative short fixtures, one-byte and seeded
  varying partitions, empty output spans, overwritten borrowed buffers, output
  canaries, exact/insufficient budgets, checksum failure after partial output,
  malformed trees, cross-block history, distance 32,768 and ring wrap, concatenated
  objects and independent mutation outcomes.
- 24 stock-Git loose/packed object cases with exact consumed zlib boundaries while
  later pack entries and the trailer are still present. Git generates four public
  synthetic blobs in a disposable bare repository; inherited Git configuration and
  environment overrides are excluded. Python/zlib independently identifies the
  stream boundaries. Git is a test oracle only, never a runtime codec/backend.
- Native lifecycle/ownership tests, eight independent streaming workers (16
  operations each), the previous worker suite and a high-level Luce consumer that
  retains result bytes across decoder reset/close.

The native suites and all three oracle groups also passed AddressSanitizer plus
UndefinedBehaviorSanitizer locally and on both CI hosts. Negative fixtures require
explicit normal rejection; a crash or sanitizer report is not an accepted failure.
Git versions observed were 2.50.1 locally, 2.55.0 on both CI hosts and 2.43.0 on the
VPS. Git loose objects and pack entries use zlib, not unwrapped DEFLATE; this slice
corrects the earlier misleading raw-framing/Git wording. It does not implement a
complete Git object/pack parser, delta engine or pack writer.

The public Linux native-opt-3 bundle has SHA256
`439675f09b01d4371b8b09607de1ad254cacb789dff621935d6d80316f3cd000`.
After archive-member, revision and per-file hash verification, its five executables
and four test scripts passed the full prebuilt suite on the existing Ubuntu 24.04
VPS. The same transient dynamic-user isolation and resource limits described above
were used; no dependencies were installed. Systemd reported 24.008 seconds elapsed
and 6.014 seconds CPU. These are bounded smoke-suite observations, not throughput,
concurrent-service capacity or aggregate process-memory guarantees.

The exact staging directory was removed and its test service became absent/inactive.
All 32 running service names matched the pre-test baseline. Caddy PID, activation
timestamp and configuration hash were unchanged; the existing site returned HTTPS
200 with the same ETag. No production data, proxy, DNS or firewall changes occurred.
The bundle, Linux/macOS correctness logs and VPS log are retained in the owner's
ignored local build directory; the public CI run contains the hosted test evidence.

M1a remains incomplete. Next: incremental encoding in both framing modes, explicit
allocator-failure injection, cooperative work limits, measured peak memory/latency
and further fuzzing. Full Git-consumer integration belongs to the later M2a gate;
the stock-Git codec fixtures here do not complete it. There is no claim of
ThreadSanitizer coverage, multi-gigabyte stress coverage, asynchronous cancellation,
exhaustive allocation-failure handling or independent security review. No real
account or package-service deployment is enabled by these tests.

## Incremental raw-DEFLATE/zlib encoder — 2026-09-14 PDT / 2026-09-15 UTC

Source revision: `f11a20e6d5da33e57199557fe91eaf751d37a00b`.
[CI run 34924210219](https://github.com/dymokomi/luce-compress/actions/runs/34924210219)
passed all six compiler modes and AddressSanitizer/UndefinedBehaviorSanitizer on
Ubuntu 24.04 x86-64 and macOS 15 arm64. The same final suite passed locally. Source
pins are unchanged; neither language nor the image library was modified.

The encoder implements bounded fixed-Huffman LZ77 with raw/zlib framing, sticky
absolute EOF, input/output budgets, partial output, poisoned errors and reset/close.
It retains 557,448 bytes on both initial targets, including its owning handle,
65,536-entry match table, 32 KiB history, 258-byte lookahead and pending bits. The
table and smaller control/history state are two bounded heap allocations; native
`step` allocates nothing, and reset reuses both. The owning Luce `Deflater` allocates
each result before advancing the stream, matching the `Inflater` ownership policy.

Each compiler mode passed **5,072 codec fixture cases**: the existing 646
whole-buffer, 1,846 incremental decoder and 24 stock-Git boundary cases, plus 2,556
incremental encoder cases. Native lifecycle/eight-worker suites and the high-level
Luce consumer also passed. The sanitizer gate runs all four fixture groups and
native suites, including the new encoder tests. This is not ThreadSanitizer or an
independent security audit.

Encoder coverage includes explicit raw/zlib framing, exact/insufficient source and
output budgets, zero output space, one-byte/seeded/large partitions, every first
split of representative short and lookahead-boundary fixtures, overwritten input
and output scratch buffers, canaries, emitted output before EOF, empty final calls,
EOF retention through output backpressure, deterministic encoded bytes across
partitions, history wrap, output ownership after reset/close, poison/reset and eight
independent workers with explicitly capped 512 KiB stacks. An independent fixed
block inspector verifies actual length-258/distance-1 and length-258/distance-32768
matches; the repeated-source ratio check excludes a stored-only implementation.

Python/zlib independently stream-decodes every successful encoder fixture with
exact completion checks. Stock Git reads four Base-encoded loose objects, then
strictly indexes and reads four Base-encoded pack entries in a separate empty bare
repository so packed reads cannot silently use loose objects. Git and Python supply
only disposable test fixtures/consumers, not any production implementation. This
still does not validate a complete Git parser, delta/ref engine or server.

During development, a large inline heap-state initializer exhausted small macOS
worker stacks in native-opt-0 and C-debug. A separate minimal reproducer confirmed
failure at 512 KiB and success at 4 MiB. Generated C-debug stack-usage reports showed
557,936 bytes for that constructor. The package-only separate-table workaround
reduced it to 33,952 bytes, and the final capped-worker gates pass on both hosts.
The compiler follow-up is documented separately in the owner's workspace; no
language patch was made. These static frame sizes are not process-memory metrics.

The verified public Linux native-opt-3 bundle has SHA256
`400354729fc2aa0f4dd77cc635866abbf2540b9b4b0ef8cefd58c5a99622e98e`.
Its seven executables and five scripts passed the full prebuilt suite on the same
Ubuntu 24.04 VPS after archive-member, revision and per-file hash checks, using the
same transient dynamic-user isolation and resource caps as previous checkpoints.
No dependencies were installed. Git 2.43.0 was already present. Systemd reported
73.934 seconds elapsed and 18.498 seconds CPU under the 25% CPU quota; these are
whole-suite smoke observations, not throughput or production capacity measurements.

The exact staging directory was removed and the test unit was absent/inactive.
All 32 live service names, Caddy PID/activation/configuration hash and the site's
HTTPS 200/ETag were unchanged. No production data, proxy, DNS or firewall changes
occurred. The verified bundle, local/CI correctness logs and VPS log are retained
in the owner's ignored build directory; hosted evidence is linked above.

M1a is still incomplete: explicit allocator-failure injection, cooperative work
limits, aggregate/peak-memory and latency measurements, larger stress workloads and
further fuzzing remain. There is no sync/full flush, dictionary, gzip wrapper,
dynamic-Huffman encoder, tuning-level or asynchronous-cancellation claim. Full Git
integration is M2a work; registration, hosting and real language CLI acceptance
remain separate uncompleted gates.

## Deterministic allocation failures — 2026-09-14 PDT / 2026-09-15 UTC

Source/test revision: `bd1d0ec8928dcb527c15bd22d8102fb3efaae09d`.
[CI run 34925982563](https://github.com/dymokomi/luce-compress/actions/runs/34925982563)
passed all six compiler modes and AddressSanitizer/UndefinedBehaviorSanitizer on
Ubuntu 24.04 x86-64 and macOS 15 arm64. The same complete gates passed locally,
as did the local prebuilt runner. Production codec and language sources did not
change; this checkpoint adds the failure suite, runner/bundle wiring and contracts.

Each mode now runs **368 counted allocation-failure/retry cases**, in addition to
the existing **5,072 codec fixtures**, native lifecycle/eight-worker suites and Luce
consumer. The failure executable also runs under sanitizers and in the prebuilt
bundle. It uses the existing Base allocator interface in its own single-threaded
process; there are no production fault hooks or system allocator changes.

Successful allocation traces are replayed with every observed allocation position
refused once and persistently. A fixed ledger checks exact live pointers/sizes and
complete cleanup, including the native ownership shell, buffer growth, both encoder
constructor allocations and late codec-error cleanup. Raw/zlib facades cover initial,
intermediate/final draining steps, zero-capacity results and finished streams. OOM
before stepping preserves exact counters/flags and does not latch EOF; retrying
produces the clean reference bytes. Previously returned chunks survive later errors,
reset and close. Native step/reset/close make zero requests with an allocator armed
to refuse its first request. See [ALLOCATION_FAILURES.md](ALLOCATION_FAILURES.md)
for the precise model and covered paths.

The audited peak of 590,720 requested live bytes matched on both hosts and the VPS.
This is only the sum inside the test ledger, not RSS, stack/allocator overhead,
outside fixtures or an aggregate server memory bound. These finite traces do not
cover every input, OS/libc/startup allocation, managed Luce/GC exhaustion, concurrent
heap replacement or real host RAM exhaustion. No production defect was found that
required a codec patch; the separately documented compiler stack limitation remains
unfixed, and its package workaround now has second-allocation failure evidence.

The verified Linux native-opt-3 bundle has SHA256
`d736a357cfdf6884dd2cd255bafbb911aba8a2659e3a617148ac44c751e5c28d`.
Its eight executables and five scripts passed the full prebuilt suite on the existing
Ubuntu 24.04 VPS after archive-member, revision and per-file hash checks. The same
transient dynamic-user isolation/resource caps described above were used, without
dependency installation or network/live-application access. Systemd reported success,
74.498 seconds elapsed and 18.611 seconds CPU under the 25% quota. These are whole-suite
smoke observations, not codec performance or production capacity claims.

The exact staging directory was removed and its unit was absent/inactive. All 32
running service names, Caddy PID/activation/configuration hash and the site's HTTPS
200/ETag were unchanged. No live data, proxy, DNS or firewall changes occurred.
Local and hosted logs plus the verified bundle are retained in the owner's ignored
build directory; the public CI run is linked above.

M1a remains incomplete: cooperative work limits, measured aggregate/peak process
memory and latency, larger stress workloads and further fuzzing remain. Full Git
integration, registration, registry deployment and language CLI acceptance are
separate pending gates. This is not exhaustive OOM, thread-sanitizer or independent
security-review evidence.

## Cooperative work limits — 2026-09-14 PDT / 2026-09-15 UTC

Source/test revision: `37917350a4831285c6f419e3a86c9af3243629b7`.
[CI run 34928398223](https://github.com/dymokomi/luce-compress/actions/runs/34928398223)
passed all six compiler modes and AddressSanitizer/UndefinedBehaviorSanitizer on
Ubuntu 24.04 x86-64 and macOS 15 arm64. Final-source local modes 0–2 passed before
disk exhaustion interrupted mode 3 and a parallel sanitizer run. After removing
verified stale compiler-cache binaries, modes 3, C-debug and C-release were rebuilt
and passed; the full sanitizer and prebuilt suites were rerun successfully. The
interrupted logs remain failure evidence, not successful runs. No codec change was
needed for the host I/O failure, and neither language nor image source was changed.

Native `step` and owning `feed` now accept 1–65,536 bounded state-machine dispatches
per call, defaulting to 4,096, and report actual work. Exhaustion returns `yielded`
without replaying input or losing partial state/EOF. Completion on the final allowed
dispatch returns `finished`. A yield can consume and produce zero bytes; consumers
must handle this new status and reschedule the owner, not wait indefinitely for
input. This is a dispatch bound, not a wall-clock deadline or aggregate server
scheduling policy. See [STREAMING_CONTRACT.md](STREAMING_CONTRACT.md).

Each mode passed **6,000 codec fixture cases**, comprising the previous 5,072 plus
**928 cooperative-work cases**. The new cases cover raw/zlib framing, stored/fixed/
dynamic blocks, one-unit/varying/default/maximum allowances, exact resumed bytes,
partition-independent encoder output, all first splits/truncated prefixes of short
fixtures, sticky EOF, malformed streams and a 4,096-empty-block chain that produces
no expanded bytes. Drivers assert per-call work and I/O bounds. Python/zlib remains
an independent oracle; stock Git still reads Base-encoded loose and packed objects.

Native and owning tests cover invalid-work rejection before mutation/allocation,
closed/failed/finished precedence, owner-side reset or direct close at multiple
unfinished yield points, retained output ownership, and eight independent workers
with 512 KiB stacks. The real high-level Luce consumer resumes one-unit calls.
The allocation suite now counts **388 failure/retry cases**, with additional native
allocation-free and direct-unfinished-close assertions. Failed result allocation
after yielding preserves counters and EOF for retry. The audited peak is 590,736
requested live bytes, not RSS or process/aggregate memory. Retained decoder and
encoder state remain 37,960 and 557,448 bytes on the tested targets.

The verified public Linux native-opt-3 bundle has SHA256
`8b8075732919978dbf39a654f480c487ecbe1673ad5a97dd33f472d4c9c2300d`.
Its nine executables and six scripts passed the full prebuilt suite on the existing
Ubuntu 24.04 VPS after regular-member, revision and per-file hash verification.
The same transient dynamic-user/private-network/private-tmp isolation, read-only
host/input, inaccessible live applications/home, no capabilities and resource caps
were retained: 512 MiB RAM, no swap, 25% CPU, 64 tasks and 180 seconds. No dependency
installation occurred. Systemd reported success, 99.520 seconds elapsed and 24.878
seconds CPU. These are quota-limited whole-suite observations, not codec throughput
or production capacity measurements.

Removed only the exact staging directory after checking its revision and inactive
unit. The unit was then absent/inactive. All 32 live service names matched the
baseline; Caddy PID, activation/configuration hash and site HTTPS 200/ETag were
unchanged. No live application/data/proxy/DNS/firewall changes occurred. The verified
bundle and local/hosted/VPS logs are retained in the owner's ignored build directory.

M1a remains incomplete: measured process/aggregate memory and latency, larger
streaming stress workloads and further fuzzing are next. There is no claim of
asynchronous cross-thread close, ThreadSanitizer coverage, exhaustive allocation
failure handling or independent security review. Full Git service integration,
real registration, deployment and standalone `luc` acceptance remain separate gates.
