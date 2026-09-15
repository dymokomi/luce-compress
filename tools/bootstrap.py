#!/usr/bin/env python3
"""Build pinned sibling compilers into this package; never edit their sources."""
import os
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "toolchain"


def run(args):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    base, luce = ROOT.parent / "luce-base", ROOT.parent / "luce"
    host = {("Darwin", "arm64"): "arm64-macos",
            ("Linux", "x86_64"): "x86_64-linux"}.get((platform.system(), platform.machine()))
    if not host:
        raise SystemExit("Use explicit compiler paths on this platform.")
    for source, pin in ((base, "BASE"), (luce, "LUCE")):
        expected = (ROOT / "bootstrap" / pin).read_text().strip()
        actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        if actual != expected:
            raise SystemExit(f"{source}: expected {expected}, found {actual}")
    run([os.environ.get("CC", "cc"), "-std=gnu11", "-O2", "-w", "-fno-strict-aliasing",
         "-I", base / "runtime", base / "bootstrap" / f"luce-base-{host}.c",
         base / "runtime/lucb_rt.c", "-lm", "-pthread", "-o", OUT / "stage0"])
    run([OUT / "stage0", "build", base / "src/main.lucb", "--native", "-o", OUT / "luce-base"])
    run([OUT / "luce-base", "build", luce / "src/main.lucb", "--native", "-o", OUT / "luce"])


if __name__ == "__main__":
    main()
