# Incremental codec contract

The decoder and encoder implement this contract, including deterministic Base-heap
failure/retry tests. Cooperative work limits remain follow-up work. The underlying formats are [RFC 1950](https://www.rfc-editor.org/info/rfc1950/)
and [RFC 1951](https://www.rfc-editor.org/info/rfc1951/).

One decoder owns a fixed 32 KiB history window and bounded Huffman/bit state. It
borrows only the current, disjoint input/output spans; it never retains their pointers after
a step. A step reports consumed input, produced output, and exactly one of
`need_input`, `need_output`, `finished`. Empty spans are legal and cannot trigger
null-pointer arithmetic. No chunk is replayed from the beginning to simulate
streaming. The caller controls scheduling; there is no internal unbounded thread.

Input can end anywhere, including inside header/length/Huffman/repeat/distance or
checksum fields. Output can fill inside an overlapping match. The state resumes
without duplicating bytes or losing a symbol. A final-input marker distinguishes
temporary starvation from truncated data; a stream may still need output draining
after the caller has supplied its last byte. End-of-stream consumes no next-object
bytes. Raw-DEFLATE and zlib must have explicit framing modes, never autodetection.

Total compressed and expanded budgets use checked arithmetic and are checked
before consuming/emitting beyond the bound. A ratio alone is not a decompression
limit. Errors poison the current stream; reset/close creates a clear ownership
boundary. Bytes produced before final checksum validation are untrusted: consumers
must keep them quarantined until successful completion. No side effects may be
published merely because a step produced output.

The Luce facade uses owning byte chunks/results while the native core supports
borrowed spans. Each stream is worker-local; independent streams can run on bounded
worker pools. Cancellation may occur between steps, not by concurrently closing an
active stream from another worker. Test reset/close/error and allocation failures.

Required tests: every split position of short valid/malformed fixtures, randomized
chunk partitions, one-byte input and output, empty steps, exact full buffers,
matches across the 32 KiB wrap, repeated blocks, final empty blocks, unfinished
trailers, capacity/total-limit boundaries, multiple concatenated objects, and
equivalence to an independent streaming oracle. Inspect total retained state and
instrument sanitizer runs; a whole-buffer success is not streaming evidence.

## Encoder-specific state and EOF

Encoding uses a fixed-Huffman LZ77 policy and bounded 258-byte lookahead, a 32 KiB
history ring and a 65,536-entry absolute-position match table. It allocates state
and table once, does not allocate within native `step`, and does not retain caller
spans. Reset reuses both allocations; close releases them. Native `Encoder` is an
owning handle and must not be copied, unlike the decoder's self-contained value.

Fill lookahead to 258 bytes before selecting a symbol, except at declared EOF.
That policy makes output independent of input/output chunk partitions. Pending bits
are drained before selecting another symbol; a partial drain never repeats the
match/table/history/checksum update. All accepted input is represented exactly once.
Only an explicit final-input declaration permits EOB/padding/zlib trailer emission.
At the exact source budget, starvation may still request an empty final call; it
must reject extra bytes, not silently infer EOF from a caller-selected budget.

Input statistics count bytes accepted into retained state, which may include
lookahead not yet encoded; output counts only delivered bytes. Budget/EOF errors
poison the encoder just as decoder errors do. Encoder output remains unpublished
until successful completion and enclosing integrity/authorization checks.

Test independent Python/zlib streaming reads, deterministic partition equivalence,
real stock-Git loose/packed consumers, progress before EOF, empty final input,
lookahead/history wrap, output-limited finalization, source/output budgets, lifetime
and explicit 512 KiB worker stacks. Compression ratio checks distinguish actual
LZ77 matching from a stored-only implementation; they are not throughput claims.

## Allocation failure and publication

A failed native state allocation leaves no partially constructed public owner.
For the owning facade, the output buffer, native `Data` and reference shell must
all be acquired before calling the state machine. Refusal of any one leaves input
and output counters, failed/finished flags, pending bits/history and declared EOF
unchanged. The caller may retry that call; no hidden final-input declaration may
constrain a shorter, nonfinal retry. A core parse/budget failure is different: it
poisons the stream and the already-allocated result is released without publication.

Native step/reset/close need no allocations, including after the allocator starts
refusing all requests. Buffer growth refusal preserves the old pointer, capacity,
used length and bytes. Earlier owning chunks remain valid after later allocation
or parse errors and state close, but remain quarantined until stream validation.
The exact tested fault model and exclusions are in [ALLOCATION_FAILURES.md](ALLOCATION_FAILURES.md).
