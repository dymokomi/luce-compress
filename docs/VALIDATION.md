# Initial codec-core validation — 2026-09-14

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

M1a is still incomplete: this validates a bounded whole-buffer core, not incremental
streaming, raw-DEFLATE/Git packs, cancellation, aggregate memory guarantees,
performance targets or production security. See [STREAMING_CONTRACT.md](STREAMING_CONTRACT.md)
for the next implementation and its required boundary tests.
