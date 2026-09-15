# Streaming resource and stress contract

This is a measured test workload, not a production server admission policy or a
claim that compression will meet a latency deadline on arbitrary hardware.
`tests/stress_driver.lucb` is entirely Base. It drives independent worker-owned
native encoders and decoders as a streaming pipeline; no source or result is kept
whole, written to disk or mapped as a source-sized allocation. Production codec
code and foreign-library dependencies do not change for this test.

Each worker constructs its own codec pair, then waits at a release/acquire start
barrier. All owners exist together before timing starts; no Luce managed
references cross threads. One or eight explicitly 512 KiB-stack workers generate
repeat or seeded xorshift bytes, feed bounded borrowed spans, decode the emitted
chunks and check every reconstructed byte immediately. Each direction has its own
generator state. Counts, final framing, work budgets and output canaries are checked;
consumed input and reconstructed output are overwritten before reuse. Reset reuses
owners across rounds. Raw EOB may arrive before the encoder's remaining zero-output
finalization steps, so the harness accounts for independent producer/consumer EOF.

Caller buffer payloads per worker total 98,306 bytes (three 32 KiB spans plus two
canaries), excluding layout/stack overhead, alongside fixed codec state and fixed
64-bucket timing histograms. They do not grow
with processed bytes. Native correctness/differential tests remain required: this
paired stress pipeline supplements, rather than replaces, the independent zlib and
stock-Git oracles. It is not a standalone proof of either codec's correctness.

## Reproducible profiles and gates

```sh
python3 tests/test_stress.py
python3 tests/check_stress.py build/native3/stress-driver
python3 tests/check_stress.py build/native3/stress-driver --full
```

The five-case quick profile runs in all six compiler modes, under ASan/UBSan and
in the isolated VPS bundle. It includes empty/reset streams, one-unit raw noise,
one/eight workers, raw/zlib framing, default/maximum allowances and repeated owner
reuse. Eight Python harness tests reject bad accounting/histograms, wrong platform
units, failed/signaled/sanitizer children, excessive output and timeout leaks.
Timeout cleanup kills and reaps only the freshly created child process group.

The eleven-case full profile additionally runs uninstrumented native-opt-3 on both
CI hosts. Workloads include two rounds of 16 MiB noise per worker with one/eight
workers, repeated-data streams growing from 16 to 128 MiB without corresponding
memory growth, and a single **4 GiB + 1 byte** zlib stream crossing 32-bit encoder
input and decoder output counters.
Neither a multi-gigabyte allocation nor a multi-gigabyte temporary file is required.
Full and quick runs emit JSON observations and histograms into retained CI logs.

Hard regression guards, chosen as generous test ceilings rather than capacity
promises:

- Every byte/count/EOF/work/canary assertion must pass. Repeated data must actually
  compress, and state-machine work must remain bounded in relation to input size.
- The driver process's reported peak RSS must be positive and at most
  `(64 + 8 * workers)` MiB: 72 MiB for one worker, 128 MiB for eight. Instrumented
  quick runs have a separate 512 MiB ceiling and are not performance baselines.
- Eightfold single-stream growth from 16 to 128 MiB may increase process peak RSS
  by at most 16 MiB. The >4 GiB case retains the one-worker 72 MiB ceiling.
- Each ordinary child has a 180-second wall-clock timeout. The full profile's
  >4 GiB child has an explicit 600-second limit. The VPS runs only quick cases
  inside its unchanged whole-suite 180-second, 25%-CPU, 512-MiB sandbox.

These ceilings are test failures, not a runtime memory reservation/limiter. A real
server still needs aggregate admission and owner lifetimes. Managed facade copying,
unbounded caller retention, network buffering and unrelated processes are outside
the measured native-driver footprint.

## Measurement meaning and limits

The Python observer uses [`os.wait4`](https://docs.python.org/3/library/os.html#os.wait4)
for the exact child. This avoids accumulating earlier children's high-water marks
or missing short peaks with polling. OS-reported peak RSS includes the driver's
threads, resident stacks, codec/caller buffers, allocator and process startup;
it excludes the Python observer and is not the sum of requested Base allocations.
It is also not virtual memory, a total-allocation count, or a cgroup/server total.
The runner normalizes [Darwin bytes](https://github.com/apple/darwin-xnu/blob/main/bsd/man/man2/getrusage.2)
and [Linux KiB](https://www.kernel.org/pub/linux/docs/man-pages/book/man-pages-6.9.pdf).
Host/runtime reporting and allocator behavior can differ; keep the platform and
exact compiler/source pins with measurements.

Pipeline throughput counts original source bytes once, divided by barrier-release
to final-join time. It includes generation, encoding, decoding, byte comparisons,
buffer overwrites, resets, timing and thread scheduling. It excludes initial codec
construction/start-barrier preparation; separate parent wall/child CPU measurements
include process startup and construction. This is **not** isolated encoder or
decoder throughput, nor a speed comparison against zlib or another implementation.

Step durations use the existing Base monotonic clock, with fixed power-of-two
histograms and observed maxima. Reported percentile ceilings bound the **recorded
durations**, not true execution time: clock granularity, timing overhead and OS
preemption affect them. Zero/sub-tick observations do not prove nanosecond latency.
No percentile or maximum is treated as a universal deadline. Work allowances remain
deterministic dispatch limits independently of these measurements.

The stress suite is finite, not exhaustive fuzzing, ThreadSanitizer or a security
review. Its Base round trips do not replace independent large-stream fixtures,
hostile-input fuzzing or later threaded Git/server integration.
