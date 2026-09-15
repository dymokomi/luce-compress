#!/usr/bin/env python3
"""Run trusted prebuilt test binaries; no codec/compiler installation required."""
import argparse
from pathlib import Path
import subprocess
from check_codecs import check
from check_stream import check as check_stream
from check_git import check as check_git
from check_encode import check as check_encode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binaries", type=Path)
    args = parser.parse_args()
    binaries = args.binaries.resolve()
    for name in ["native", "facade", "driver", "stream-tests", "stream-driver", "encoder-tests", "encode-driver", "failure-tests"]:
        if not (binaries / name).is_file():
            raise SystemExit(f"missing {name}")
    for name in ["native", "facade", "stream-tests", "encoder-tests", "failure-tests"]:
        subprocess.run([str(binaries / name)], check=True, timeout=90)
    check(binaries / "driver")
    check_stream(binaries / "stream-driver")
    check_git(binaries / "stream-driver")
    check_encode(binaries / "encode-driver")
    print("PASS prebuilt compression suite", flush=True)


if __name__ == "__main__":
    main()
