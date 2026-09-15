#!/usr/bin/env python3
"""Run the native API and complete independent oracle with ASan and UBSan."""
import argparse
import os
from pathlib import Path
import subprocess
from check_codecs import check
from check_stream import check as check_stream
from check_git import check as check_git

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=ROOT / "build/toolchain/luce-base")
    args = parser.parse_args()
    output = ROOT / "build/sanitize"
    output.mkdir(parents=True, exist_ok=True)
    runtime = ROOT.parent / "luce-base/runtime"
    os.environ["ASAN_OPTIONS"] = "halt_on_error=1:abort_on_error=1"
    os.environ["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    def run(command):
        subprocess.run([str(arg) for arg in command], cwd=ROOT, check=True, timeout=180)
    for source, name in [(ROOT / "src/luce_compress/native_tests.lucb", "native"), (ROOT / "tests/driver.lucb", "driver"),
                         (ROOT / "src/luce_compress/stream_tests.lucb", "stream-tests"), (ROOT / "tests/stream_driver.lucb", "stream-driver")]:
        generated, executable = output / f"{name}.c", output / name
        run([args.base.resolve(), "build", source, "--emit=c", "-o", generated])
        run([os.environ.get("CC", "cc"), "-std=gnu11", "-O1", "-g", "-w", "-fno-strict-aliasing",
             "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-I", runtime,
             generated, runtime / "lucb_rt.c", "-pthread", "-lm", "-o", executable])
        if name in ["native", "stream-tests"]:
            run([executable])
        elif name == "driver":
            check(executable)
        else:
            check_stream(executable)
            check_git(executable)
    print("PASS AddressSanitizer + UndefinedBehaviorSanitizer", flush=True)


if __name__ == "__main__":
    main()
