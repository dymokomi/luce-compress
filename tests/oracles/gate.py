#!/usr/bin/env python3
"""The self-check programs, drivers and oracles, run by tests/oracles/main.luc (`luc test`,
which runs the module tests itself): build them in one compiler mode (native, opt 0, by
default; --mode all for every mode) and check them, with zlib only as an independent oracle."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_codecs import check
from check_stream import check as check_stream
from check_git import check as check_git
from check_encode import check as check_encode
from check_work import check as check_work
from check_fuzz import check as check_fuzz
from check_large import check as check_large
from check_flate import check as check_flate
from check_brotli import check as check_brotli
from check_gzip import check as check_gzip
from check_zstd import check as check_zstd

ROOT = Path(__file__).resolve().parents[2]
MODES = {f"native{i}": ["--native", "--opt", str(i)] for i in range(4)}
MODES.update({"c": ["--backend=c"], "c-release": ["--backend=c", "--release"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=[*MODES, "all"], default="native0")
    args = parser.parse_args()
    args.base = Path(os.environ.get("LUCE_BASE", "luce-base"))
    args.luce = Path(os.environ.get("LUCE", "luce"))
    environment = dict(os.environ)
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
        for source, name in [(ROOT / "src/native_tests.lucb", "native"), (ROOT / "tests/driver.lucb", "driver"),
                             (ROOT / "src/stream_tests.lucb", "stream-tests"), (ROOT / "tests/stream_driver.lucb", "stream-driver"),
                             (ROOT / "src/encoder_tests.lucb", "encoder-tests"), (ROOT / "tests/encode_driver.lucb", "encode-driver"),
                             (ROOT / "src/failure_tests.lucb", "failure-tests"),
                             (ROOT / "src/work_tests.lucb", "work-tests"),
                             (ROOT / "tests/stress_driver.lucb", "stress-driver"),
                             (ROOT / "src/fuzz_tests.lucb", "fuzz-driver"),
                             (ROOT / "tests/file_driver.lucb", "file-driver"),
                             (ROOT / "tests/flate_driver.lucb", "flate-driver"),
                             (ROOT / "tools/codec_tool.lucb", "codec-tool")]:
            run([args.base, "build", source, *flags, "-o", output / name])
        run([args.luce, "build", ROOT / "tests/facade.luc", *flags, "-o", output / "facade"])
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
        # A fresh interpreter: on Linux a child's peak RSS starts at its
        # parent's (the mm it was forked from), and this one holds the oracles.
        run([sys.executable, ROOT / "tests/check_stress.py", output / "stress-driver"])
        check_fuzz(output / "fuzz-driver")
        check_large(output / "file-driver")
        check_flate(output / "flate-driver")
        check_brotli(output / "codec-tool")
        check_gzip(output / "codec-tool")
        check_zstd(output / "codec-tool")
        print(f"PASS {mode} ({time.monotonic() - started:.1f}s)", flush=True)


if __name__ == "__main__":
    main()
