#!/usr/bin/env python3
"""Write Mac Google Drive upload steps (see packaging/release_build.py)."""

import argparse
from pathlib import Path

import importlib.util

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "release_build", ROOT / "packaging/release_build.py")
_release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_release)
main = _release.main


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(main(["upload-commands", "--version", args.version,
                           "--out", str(args.out)]))
