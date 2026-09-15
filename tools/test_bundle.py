#!/usr/bin/env python3
"""Bundle only public test binaries/scripts for isolated second-host validation."""
import argparse
import hashlib
import io
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binaries", type=Path, default=ROOT / "build/native3")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    programs = ["native", "facade", "driver", "stream-tests", "stream-driver", "encoder-tests", "encode-driver", "failure-tests", "work-tests"]
    scripts = ["run_prebuilt.py", "check_codecs.py", "check_stream.py", "check_git.py", "check_encode.py", "check_work.py"]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    manifest = []
    with tarfile.open(args.output, "w:gz") as bundle:
        def add(name, data, mode=0o644):
            item = tarfile.TarInfo(name)
            item.size, item.mode = len(data), mode
            bundle.addfile(item, io.BytesIO(data))
            manifest.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
        for name in programs: add(f"bin/{name}", (args.binaries / name).read_bytes(), 0o755)
        for name in scripts: add(f"tests/{name}", (ROOT / "tests" / name).read_bytes())
        for name in ["LICENSE", "LICENSE-MIT", "LICENSE-APACHE", "NOTICE.md"]:
            add(name, (ROOT / name).read_bytes())
        add("REVISION", (revision + "\n").encode())
        add("SHA256SUMS", "".join(manifest).encode())
    print(f"{hashlib.sha256(args.output.read_bytes()).hexdigest()}  {args.output.name}", flush=True)


if __name__ == "__main__": main()
