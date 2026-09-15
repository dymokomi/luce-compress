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
