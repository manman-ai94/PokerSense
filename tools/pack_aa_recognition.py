"""Pack the private AA recognition bundle for the Windows installer.

Run on the machine that has the private data (the owner's Mac)::

    PYTHONPATH=src:. .venv/bin/python tools/pack_aa_recognition.py \\
        --profile configs/reproduction/aa8_candidate_v2/factory.json --out <folder>

Writes ``PokerSense-AA-recognition.zip`` (the portable bundle of
``aa_bundle.export_bundle``) and ``PokerSense-AA-recognition.json`` (zip size
and sha256, and the bundle manifest's sha256 the program trusts). Upload both
to the ``recognition/`` folder next to the release files
(docs/windows-distribution.md); the next release checks them and lists the zip
in latest.json, and the installed program downloads it (never inside the
installer). The files are private data: never commit them.

The out folder also gets ``aa_mushroom_bank.npz`` (the mushroom-pool digit
bank) when the private data has one. A second seat running from source
(docs/second-seat-windows.md) gets the whole folder and installs it::

    python tools/pack_aa_recognition.py --install <folder>/PokerSense-AA-recognition.zip

which checks the zip against its sidecar, unpacks it into the window's data
folder (``$POKERSENSE_DATA_ROOT/aa-live-state/recognition/``, where
``START-AA.cmd`` finds it), checks every file and only then makes it current,
and copies the mushroom bank to where the window reads it.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile

from poker_engine.data_paths import DATA_ROOT_ENV, data_root, private_root
from poker_engine.desktop.aa_bundle import MANIFEST, export_bundle, validate_bundle
from poker_engine.desktop.aa_mushroom import BANK as MUSHROOM_BANK
from poker_engine.desktop.app_update import (
    RECOGNITION_CURRENT, RECOGNITION_DIR, UpdateError, safe_extract)

SCHEMA = "pokersense-recognition-v1"
ZIP_NAME = "PokerSense-AA-recognition.zip"
JSON_NAME = "PokerSense-AA-recognition.json"
MUSHROOM_NAME = "aa_mushroom_bank.npz"
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


def install(archive, state, private=None):
    """Make the packed bundle ``archive`` (its sidecar next to it) the one the
    window in data folder ``state`` uses; copy the mushroom bank next to it,
    if any, under ``private``. Nothing changes unless every check passes.
    Returns what was installed."""
    archive, state = Path(archive), Path(state)
    sidecar = json.loads((archive.parent / JSON_NAME).read_text("utf-8"))
    if sidecar.get("schema") != SCHEMA:
        raise ValueError(f"{JSON_NAME} is not a recognition sidecar")
    data = archive.read_bytes()
    if (len(data) != sidecar["zip_bytes"]
            or hashlib.sha256(data).hexdigest() != sidecar["zip_sha256"]):
        raise ValueError(f"{archive.name} does not match {JSON_NAME} "
                         "(damaged or a different pack): send both again")
    digest = sidecar["manifest_sha256"]
    root = state / RECOGNITION_DIR
    root.mkdir(parents=True, exist_ok=True)
    staging = root / (digest + ".new")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        safe_extract(archive, staging)
        validate_bundle(staging / "profile.json", digest)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    final = root / digest
    shutil.rmtree(final, ignore_errors=True)
    os.replace(staging, final)
    pointer = root / (RECOGNITION_CURRENT + ".part")
    pointer.write_text(json.dumps({"manifest_sha256": digest,
                                   "sha256": sidecar["zip_sha256"]}) + "\n", "utf-8")
    os.replace(pointer, root / RECOGNITION_CURRENT)
    for old in root.iterdir():
        if old.is_dir() and old.name != digest:
            shutil.rmtree(old, ignore_errors=True)
    result = {"profile": str(final / "profile.json"), "manifest_sha256": digest,
              "mushroom_bank": None}
    bank = archive.parent / MUSHROOM_NAME
    if bank.is_file():
        target = Path(private if private is not None else private_root()) / (
            MUSHROOM_BANK)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bank, target)
        result["mushroom_bank"] = str(target)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--profile", type=Path,
                        help="the live window's profile, e.g. "
                             "configs/reproduction/aa8_candidate_v2/factory.json")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--install", type=Path, metavar="ZIP",
                        help="install a received pack instead of making one")
    parser.add_argument("--state", type=Path,
                        help="with --install: the window's data folder "
                             "(default $POKERSENSE_DATA_ROOT/aa-live-state)")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        # Chinese lines must survive a pipe on Windows (an AI assistant runs this).
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if args.install:
        if args.state is None and not os.environ.get(DATA_ROOT_ENV, "").strip():
            parser.error(f"set {DATA_ROOT_ENV} first (the data folder) or pass --state")
        state = args.state or data_root() / "aa-live-state"
        try:
            result = install(args.install, state)
        except (OSError, ValueError, KeyError, UpdateError,
                zipfile.BadZipFile) as error:
            print(f"[识别资源] 没装上：{error}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("[识别资源] 装好了：双击 launch\\aa\\START-AA.cmd，窗口里就能选“采集卡”。")
        return 0
    if args.profile is None or args.out is None:
        parser.error("--profile and --out are required (or --install ZIP)")
    with tempfile.TemporaryDirectory(prefix="pokersense-recognition-") as folder:
        receipt = export_bundle(args.profile, Path(folder) / "bundle")
        sidecar = pack(Path(folder) / "bundle", args.out)
    bank = private_root() / MUSHROOM_BANK
    if bank.is_file():
        shutil.copyfile(bank, Path(args.out) / MUSHROOM_NAME)
    print(json.dumps({"bundle": {k: receipt[k] for k in ("files", "bytes")},
                      **sidecar, "mushroom_bank": bank.is_file()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
