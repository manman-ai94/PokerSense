"""Pack the private AA recognition bundle for the Windows installer.

Run on the machine that has the private data (the owner's Mac)::

    PYTHONPATH=src:. .venv/bin/python tools/pack_aa_recognition.py \\
        --profile configs/reproduction/aa8_candidate_v2/factory.json --out <folder>

Writes ``PokerSense-AA-recognition.zip`` (the portable bundle of
``aa_bundle.export_bundle``) and ``PokerSense-AA-recognition.json`` (zip size
and sha256, and the bundle manifest's sha256 the program trusts). Upload both
to the ``recognition/`` folder next to the release files; the next release
build checks them and installs the bundle next to the program. The files are
private data: never commit them.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

from poker_engine.desktop.aa_bundle import MANIFEST, export_bundle

SCHEMA = "pokersense-recognition-v1"
ZIP_NAME = "PokerSense-AA-recognition.zip"
JSON_NAME = "PokerSense-AA-recognition.json"
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def pack(bundle, out):
    """Zip an exported bundle folder (same bytes for the same files) and
    write its sidecar; returns the sidecar."""
    bundle, out = Path(bundle), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    archive = out / ZIP_NAME
    files = sorted(path for path in bundle.rglob("*") if path.is_file())
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(bundle).as_posix(), FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            handle.writestr(info, path.read_bytes())
    data = archive.read_bytes()
    sidecar = {
        "schema": SCHEMA,
        "zip_sha256": hashlib.sha256(data).hexdigest(), "zip_bytes": len(data),
        "manifest_sha256": hashlib.sha256(
            (bundle / MANIFEST).read_bytes()).hexdigest(),
        "files": len(files),
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (out / JSON_NAME).write_text(json.dumps(sidecar, indent=2) + "\n", "utf-8")
    return sidecar


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--profile", type=Path, required=True,
                        help="the live window's profile, e.g. "
                             "configs/reproduction/aa8_candidate_v2/factory.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="pokersense-recognition-") as folder:
        receipt = export_bundle(args.profile, Path(folder) / "bundle")
        sidecar = pack(Path(folder) / "bundle", args.out)
    print(json.dumps({"bundle": {k: receipt[k] for k in ("files", "bytes")},
                      **sidecar}, indent=2))


if __name__ == "__main__":
    main()
