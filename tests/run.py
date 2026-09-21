#!/usr/bin/env python3
"""Build/run every compiler mode, with zlib only as an independent test oracle."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
from check_codecs import check
from check_stream import check as check_stream
from check_git import check as check_git
from check_encode import check as check_encode
from check_work import check as check_work
from check_stress import check as check_stress
from check_fuzz import check as check_fuzz
from check_large import check as check_large

ROOT = Path(__file__).resolve().parents[1]
MODES = {f"native{i}": ["--native", "--opt", str(i)] for i in range(4)}
MODES.update({"c": ["--backend=c"], "c-release": ["--backend=c", "--release"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=[*MODES, "all"], default="all")
    parser.add_argument("--base", type=Path, default=ROOT / "build/toolchain/luce-base")
    parser.add_argument("--luce", type=Path, default=ROOT / "build/toolchain/luce")
    args = parser.parse_args()
    environment = dict(os.environ, LUCE_BASE=str(args.base.resolve()),
                       LUCE_STD=str(ROOT.parent / "luce-base/src/std"),
                       LUCE_CACHE=str(ROOT / "build/cache"))
    def run(command):
        subprocess.run([str(arg) for arg in command], cwd=ROOT, env=environment, check=True, timeout=180)
    run([sys.executable, ROOT / "tests/test_stress.py"])
    run([sys.executable, ROOT / "tests/test_oracles.py"])
    for mode, flags in MODES.items():
        if args.mode != "all" and args.mode != mode:
            continue
        started = time.monotonic()
        output = ROOT / "build" / mode
        output.mkdir(parents=True, exist_ok=True)
        print(f"MODE {mode}", flush=True)
        for source, name in [(ROOT / "src/luce_compress/native_tests.lucb", "native"), (ROOT / "tests/driver.lucb", "driver"),
                             (ROOT / "src/luce_compress/stream_tests.lucb", "stream-tests"), (ROOT / "tests/stream_driver.lucb", "stream-driver"),
                             (ROOT / "src/luce_compress/encoder_tests.lucb", "encoder-tests"), (ROOT / "tests/encode_driver.lucb", "encode-driver"),
                             (ROOT / "src/luce_compress/failure_tests.lucb", "failure-tests"),
                             (ROOT / "src/luce_compress/work_tests.lucb", "work-tests"),
                             (ROOT / "tests/stress_driver.lucb", "stress-driver"),
                             (ROOT / "src/luce_compress/fuzz_tests.lucb", "fuzz-driver"),
                             (ROOT / "tests/file_driver.lucb", "file-driver")]:
            run([args.base.resolve(), "build", source, *flags, "-o", output / name])
        run([args.luce.resolve(), "build", ROOT / "tests/facade.luc", *flags, "-o", output / "facade"])
        run([output / "native"])
        run([output / "stream-tests"])
        run([output / "encoder-tests"])
        run([output / "failure-tests"])
        run([output / "work-tests"])
        run([output / "facade"])
        check(output / "driver")
        check_stream(output / "stream-driver")
        check_git(output / "stream-driver")
        check_encode(output / "encode-driver")
        check_work(output / "stream-driver", output / "encode-driver")
        check_stress(output / "stress-driver")
        check_fuzz(output / "fuzz-driver")
        check_large(output / "file-driver")
        print(f"PASS {mode} ({time.monotonic() - started:.1f}s)", flush=True)


if __name__ == "__main__":
    main()
