# Incremental codec contract

The decoder implements this contract; incremental encoding and explicit allocator-
failure injection remain follow-up work. The underlying formats are [RFC 1950](https://www.rfc-editor.org/info/rfc1950/)
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
