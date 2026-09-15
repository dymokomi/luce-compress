#!/usr/bin/env python3
"""Run trusted prebuilt test binaries; no codec/compiler installation required."""
import argparse
from pathlib import Path
import subprocess
from check_codecs import check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binaries", type=Path)
    args = parser.parse_args()
    binaries = args.binaries.resolve()
    for name in ["native", "facade", "driver"]:
        if not (binaries / name).is_file():
            raise SystemExit(f"missing {name}")
    for name in ["native", "facade"]:
        subprocess.run([str(binaries / name)], check=True, timeout=90)
    check(binaries / "driver")
    print("PASS prebuilt compression suite", flush=True)


if __name__ == "__main__":
    main()
