# Independent fuzz and larger-stream tests

These are finite, seeded differential tests, not exhaustive fuzz coverage, a
security audit or a production service. The codec and native drivers are Luce
Base. Python/zlib generates and checks disposable fixtures only; it is not linked
into, or called by, the production codec.

## Decoder mutations

```sh
python3 tests/check_fuzz.py build/native3/fuzz-driver
python3 tests/check_fuzz.py build/native3/fuzz-driver --seed 19510002 --cases 65536
```

Every compiler mode, the ASan/UBSan gate and the prebuilt suite run 4,096 cases
with seed 19510001. Both hosted platforms additionally run 65,536 cases with seed
19510002 against uninstrumented native-opt-3. Case counts describe a corpus, not
unique code paths or independently generated corpora in every compiler mode.

The generator starts with raw/zlib stored, fixed or dynamic streams at several
levels/strategies, using empty, repeated, ramp, text and random sources up to
65,536 bytes. Both framings exercise unchanged streams, bit flips, truncation,
replacement, insertion/deletion, random packets, swapped bytes, concatenation,
trailing bytes and invalid checksum/reserved-block mutations. Input/output budgets
vary independently. Mutations are not assumed invalid: independent zlib determines
whether the result is a valid first stream and, if so, its exact expanded bytes
and consumed boundary.

The [Python zlib streaming contract](https://docs.python.org/3/library/zlib.html#decompressobj-objects)
provides bounded expansion, explicit EOF and trailing-byte accounting. The oracle
requests at most the output budget plus one byte and requires complete EOF,
no unconsumed compressed tail, and an in-budget first-stream boundary. An error,
unfinished stream or exceeded budget means the native driver must reject normally.
It must never turn a signal, sanitizer report or assertion into an expected rejection.

The Base driver receives batches of at most 128 cases in a checked, little-endian
test format. Batch reads are capped at 16 MiB; packet metadata at 256 KiB and
expanded expectations at 64 KiB. Native borrowed spans are at most 257 bytes.
Seeded partitions include empty input/output, delayed EOF and work allowances from
one dispatch to the default allowance. Each call checks canaries, work/I/O bounds,
total counters, exact successful bytes/boundaries, poisoned errors and reset.
Borrowed input/output storage is overwritten between calls. Bounded calls/work
and a 30-second child timeout catch nontermination in this finite corpus.

The log records seed, counts, accepted/rejected totals, corpus SHA256 and Python/
zlib versions. Seed alone does not identify exact bytes across different zlib
versions. Local/CI failures retain the exact batch under the writable ignored
`build/fuzz-failures/` directory; CI uploads these files even after test failure.
Replay with:

```sh
build/native3/fuzz-driver build/fuzz-failures/seed-19510001-batch-N-HASH.bin
```

The driver prints the case ID before executing it. A read-only prebuilt deployment
cannot retain a failure batch in its input bundle: it logs the batch hash and
storage error without masking the original failure. Reproduce its logged seed and
versions in a writable test checkout. The VPS sandbox remains read-only and is
not relaxed for diagnostic output. Successful temporary batches are removed by
the harness. There is no coverage-guided search, automatic minimizer, persistent
production corpus ingestion or claim that all malformed Huffman trees are covered.

## Independent file streams

```sh
python3 tests/check_large.py build/native3/file-driver
python3 tests/check_large.py build/native3/file-driver --full
```

The quick profile runs 24 cases at 1 MiB + 1 byte in every compiler mode, sanitizers
and the prebuilt suite. The full native-opt-3 profile runs 48 cases, adding
16 MiB + 3 byte streams on both CI platforms. Raw/zlib framing and repeated/noise
patterns are tested in both directions: Base decodes independently encoded zlib
fixtures; zlib independently decodes Base output. Both compare every byte and
require exact counts and complete EOF. Four additional cases per profile require
normal rejection of insufficient encoder/decoder input/output budgets.

The Python side uses 64 KiB working chunks and the Base adapter uses 32 KiB spans,
with canary/work/ownership assertions. The bounded zlib verifier handles retained
output and unconsumed compressed bytes without accumulating a complete result.
The adapter accepts exactly one stream, rejecting a trailing suffix. Partial
negative outputs stay in a disposable fixture directory and are never published.
Each native child has a 90-second timeout; temporary files are reused between
profiles and cleaned on ordinary completion/failure. The full profile needs about
70 MiB peak scratch space, not multi-gigabyte files.

Seven harness tests check independent framing/boundary/limit expectations, bounded
expansion, seed determinism/metadata, exact failure-batch retention, crash/timeout/
sanitizer rejection, read-only failure reporting and the larger-stream verifier's
negative paths. These tests
validate the test infrastructure; they do not count as codec fuzz cases.

The separate [resource suite](RESOURCES.md) processes a logical 4 GiB + 1 byte
stream without a large file, but uses a paired Base encoder/decoder. It is not
independent >4 GiB oracle coverage. Threaded Git integration, aggregate server
admission, ThreadSanitizer and independent security review remain separate work.
