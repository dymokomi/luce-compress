#!/usr/bin/env python3
"""Bounded native streaming stress; per-child OS memory and instrumented step times."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

MIB = 1024 * 1024


def rss_bytes(value, host=sys.platform):
    if host == "darwin":
        return value
    if host.startswith("linux"):
        return value * 1024
    raise RuntimeError("resource measurements are defined only for Linux/macOS")


def measured(command, timeout=180):
    """wait4 for this exact child, not cumulative RUSAGE_CHILDREN or sampled RSS."""
    with tempfile.TemporaryFile() as output:
        began = time.monotonic()
        process = subprocess.Popen([str(item) for item in command], stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while True:
                pid, status, usage = os.wait4(process.pid, os.WNOHANG)
                if pid:
                    process.returncode = os.waitstatus_to_exitcode(status)
                    break
                if time.monotonic() - began >= timeout:
                    raise TimeoutError(f"stress child exceeded {timeout}s: {command}")
                time.sleep(0.01)
        finally:
            if process.returncode is None:
                # Own fresh session only; reap before discarding the handle.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass  # exited between the last observation and the kill
                _, status, _ = os.wait4(process.pid, 0)
                process.returncode = os.waitstatus_to_exitcode(status)
        wall = time.monotonic() - began
        output.seek(0)
        transcript = output.read(65537)
    assert len(transcript) <= 65536, "unexpectedly large stress output"
    assert process.returncode == 0, (process.returncode, transcript.decode(errors="replace"))
    for marker in [b"AddressSanitizer", b"UndefinedBehaviorSanitizer", b"runtime error:"]:
        assert marker not in transcript, transcript
    return transcript.decode(), {"wall_seconds": wall, "cpu_seconds": usage.ru_utime + usage.ru_stime,
                                 "peak_rss_bytes": rss_bytes(usage.ru_maxrss)}


def percentile(histogram, percent):
    total = sum(histogram)
    assert total > 0 and 1 <= percent <= 100
    target = (total * percent + 99) // 100
    seen = 0
    for bucket, count in enumerate(histogram):
        seen += count
        if seen >= target:
            return 1 << bucket
    raise AssertionError("incomplete histogram")


def parse(transcript, workers, amount, rounds, work):
    result = None
    calls, histograms = {}, {"encode": {}, "decode": {}}
    for line in transcript.splitlines():
        fields = line.split()
        assert fields, "empty report line"
        if fields[0] == "RESULT":
            assert result is None and len(fields) == 8, fields
            result = list(map(int, fields[1:]))
        elif fields[0] == "CALLS":
            assert len(fields) == 7 and fields[1] in histograms and fields[1] not in calls, fields
            calls[fields[1]] = list(map(int, fields[2:]))
        else:
            assert fields[0] == "HIST" and len(fields) == 4 and fields[1] in histograms, fields
            bucket, count = map(int, fields[2:])
            histogram = histograms[fields[1]]
            assert 0 <= bucket < 64 and bucket not in histogram and count >= 0, fields
            histogram[bucket] = count
    assert result is not None and result[:4] == [workers, amount, rounds, workers * amount * rounds], result
    assert result[4] > 0 and result[5] > 0 and result[6] == workers, result
    assert result[4] <= workers * rounds * (amount * 2 + 1024), result
    metrics = {"input_bytes": result[3], "encoded_bytes": result[4], "pipeline_nanoseconds": result[5],
               "pipeline_mib_per_second": result[3] / MIB / (result[5] / 1e9)}
    for name in ["encode", "decode"]:
        assert name in calls and len(histograms[name]) == 64
        histogram = [histograms[name][index] for index in range(64)]
        count, units, yields, elapsed, maximum = calls[name]
        assert count > 0 and count == sum(histogram) and count <= units <= count * work
        assert 0 <= yields < count and yields * work <= units and 0 <= maximum <= elapsed
        assert units <= workers * rounds * 64 * (amount + 1024), "unbounded dispatch growth"
        last = max(index for index, value in enumerate(histogram) if value)
        assert maximum <= 1 << last and (last == 0 or maximum > 1 << (last - 1))
        metrics[name] = {"calls": count, "work_units": units, "yields": yields,
                         "nanoseconds": elapsed, "maximum_ns": maximum,
                         "p50_upper_ns": percentile(histogram, 50),
                         "p95_upper_ns": percentile(histogram, 95),
                         "p99_upper_ns": percentile(histogram, 99), "histogram": histogram}
    return metrics


def check(driver, full=False, instrumented=False):
    driver = Path(driver).resolve()
    # Small cases also test many resets, tiny work limits and raw EOB delivery
    # before the producer's final zero-output transitions.
    cases = [(1, 0, 2, "raw", "repeat", 1), (1, 4097, 4, "raw", "noise", 1),
             (1, 262144, 2, "zlib", "noise", 4096),
             (8, 262144, 2, "raw", "noise", 4096),
             (8, 262144, 4, "zlib", "repeat", 65536)]
    if full:
        assert not instrumented, "full resource baselines use uninstrumented native3"
        cases += [(1, 16 * MIB, 2, "zlib", "noise", 4096),
                  (8, 16 * MIB, 2, "zlib", "noise", 4096),
                  (1, 16 * MIB, 2, "raw", "repeat", 4096),
                  (1, 128 * MIB, 2, "raw", "repeat", 4096),
                  (8, 16 * MIB, 2, "zlib", "repeat", 4096),
                  (1, 4 * 1024 * MIB + 1, 1, "zlib", "repeat", 4096)]
    results = []
    for workers, amount, rounds, framing, pattern, work in cases:
        # The full profile's one >4 GiB logical stream has an explicit ten-minute
        # cap; ordinary cases retain 180s. It allocates no source-sized buffer/file.
        timeout = 600 if amount > 1024 * MIB else 180
        transcript, resources = measured([driver, workers, amount, rounds, framing, pattern, work], timeout)
        metrics = parse(transcript, workers, amount, rounds, work)
        ceiling = (512 if instrumented else 64 + 8 * workers) * MIB
        assert 0 < resources["peak_rss_bytes"] <= ceiling, (resources, ceiling)
        if pattern == "repeat" and amount >= 262144:
            assert metrics["encoded_bytes"] < metrics["input_bytes"] // 50, "not actually compressing repeats"
        result = dict(workers=workers, bytes_per_stream=amount, rounds=rounds, framing=framing,
                      pattern=pattern, work_limit=work, instrumented=instrumented, **metrics, **resources)
        results.append(result)
        print("STRESS " + json.dumps(result, sort_keys=True), flush=True)
    if full:
        # An eightfold per-stream size increase must not imply source-sized memory.
        short, long = results[-4], results[-3]
        assert long["bytes_per_stream"] == short["bytes_per_stream"] * 8
        assert long["peak_rss_bytes"] <= short["peak_rss_bytes"] + 16 * MIB, (short, long)
    print(f"PASS {len(results)} bounded streaming stress/resource cases; per-child RSS, latency histograms, fixed buffers", flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("driver", type=Path)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--instrumented", action="store_true")
    args = parser.parse_args()
    check(args.driver, args.full, args.instrumented)
