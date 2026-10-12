"""Release-build steps of the Windows workflow (.github/workflows/windows-release.yml).

    stamp       write the release version into the checkout (not committed)
    config      write update-config.json (the manifest address) next to the program
    manifest    write the version manifest for a built installer
    newer       fail unless a version is newer than the published manifest's
    recognition put a recognition bundle zip (tools/pack_aa_recognition.py)
                next to the program, after checking its hashes
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from poker_engine.desktop import app_update  # noqa: E402

RECOGNITION_SCHEMA = "pokersense-recognition-v1"
RECOGNITION_ZIP = "PokerSense-AA-recognition.zip"
RECOGNITION_JSON = "PokerSense-AA-recognition.json"


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def windows_version(version):
    """Four numbers for the Windows file version: 0.3.0 -> 0.3.0.0,
    0.2.0.dev1 -> 0.2.0.1."""
    parsed = app_update.parse_version(version)
    return ".".join(map(str, parsed[:3] + (parsed[4] if parsed[3] == 0 else 0,)))


def _replace(path, pattern, replacement):
    text = path.read_text("utf-8")
    new, count = re.subn(pattern, replacement, text, count=1, flags=re.M)
    if count != 1:
        raise SystemExit(f"{path}: version line not found")
    path.write_text(new, "utf-8")


def stamp(version, root=ROOT):
    app_update.parse_version(version)
    quad = windows_version(version)
    _replace(root / "src/poker_engine/__init__.py",
             r'^__version__ = ".*"$', f'__version__ = "{version}"')
    _replace(root / "pyproject.toml", r'^version = ".*"$', f'version = "{version}"')
    numbers = quad.replace(".", ", ")
    path = root / "packaging/windows-version.txt"
    text = path.read_text("utf-8")
    text = re.sub(r"filevers=\([^)]*\)", f"filevers=({numbers})", text)
    text = re.sub(r"prodvers=\([^)]*\)", f"prodvers=({numbers})", text)
    text = re.sub(r"'(FileVersion|ProductVersion)', '[^']*'",
                  lambda m: f"'{m.group(1)}', '{version}'", text)
    path.write_text(text, "utf-8")
    return {"version": version, "windows_version": quad}


def write_config(manifest_url, out):
    out = Path(out)
    out.write_text(json.dumps({"manifest_url": manifest_url}, indent=2) + "\n",
                   "utf-8")
    return out


def build_manifest(version, installer, url, commit="", notes="", now=None):
    installer = Path(installer)
    manifest = {
        "schema": app_update.SCHEMA, "product": app_update.PRODUCT,
        "version": version,
        "published": (now or datetime.now(timezone.utc)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit, "notes": notes,
        "installer": {"url": url, "sha256": sha256_file(installer),
                      "bytes": installer.stat().st_size},
    }
    return app_update.validate_manifest(manifest)


def check_newer(current_path, version):
    """True when nothing valid is published yet or ``version`` is newer."""
    try:
        current = json.loads(Path(current_path).read_text("utf-8-sig"))
        published = app_update.validate_manifest(current)["version"]
    except (OSError, ValueError, app_update.UpdateError):
        return True, None
    return app_update.is_newer(version, published), published


def _safe_member(name):
    path = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or path.is_absolute()
            or any(part in ("", ".", "..") for part in path.parts)):
        raise SystemExit(f"unsafe path in recognition zip: {name!r}")
    return path


def embed_recognition(source, app, validate=True):
    """Check the zip against its sidecar, unpack it to ``app/recognition`` and
    write the trusted manifest digest to ``app/recognition.sha256``."""
    source, app = Path(source), Path(app)
    sidecar = json.loads((source / RECOGNITION_JSON).read_text("utf-8"))
    archive = source / RECOGNITION_ZIP
    if sidecar.get("schema") != RECOGNITION_SCHEMA:
        raise SystemExit("recognition sidecar schema mismatch")
    if (archive.stat().st_size != sidecar["zip_bytes"]
            or sha256_file(archive) != sidecar["zip_sha256"]):
        raise SystemExit("recognition zip does not match its sidecar")
    target = app / "recognition"
    if target.exists():
        raise SystemExit(f"{target} already exists")
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            path = _safe_member(info.filename)
            if info.is_dir():
                continue
            destination = target.joinpath(*path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(bundle.read(info))
    (app / "recognition.sha256").write_text(sidecar["manifest_sha256"] + "\n",
                                            "utf-8")
    receipt = None
    if validate:
        from poker_engine.desktop.aa_bundle import validate_bundle
        receipt = validate_bundle(target / "profile.json", sidecar["manifest_sha256"])
    return {"files": len(list(p for p in target.rglob("*") if p.is_file())),
            "manifest_sha256": sidecar["manifest_sha256"], "receipt": receipt}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawTextHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("stamp")
    command.add_argument("--version", required=True)
    command = commands.add_parser("config")
    command.add_argument("--manifest-url", required=True)
    command.add_argument("--out", type=Path, required=True)
    command = commands.add_parser("manifest")
    command.add_argument("--version", required=True)
    command.add_argument("--installer", type=Path, required=True)
    command.add_argument("--url", required=True)
    command.add_argument("--commit", default="")
    command.add_argument("--notes", default="")
    command.add_argument("--out", type=Path, required=True)
    command = commands.add_parser("newer")
    command.add_argument("--current", type=Path, required=True)
    command.add_argument("--version", required=True)
    command = commands.add_parser("recognition")
    command.add_argument("--source", type=Path, required=True)
    command.add_argument("--app", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "stamp":
        result = stamp(args.version)
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            with open(output, "a", encoding="utf-8") as handle:
                handle.write(f"windows_version={result['windows_version']}\n")
        print(json.dumps(result))
    elif args.command == "config":
        print(write_config(args.manifest_url, args.out))
    elif args.command == "manifest":
        manifest = build_manifest(args.version, args.installer, args.url,
                                  args.commit, args.notes)
        args.out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                            "utf-8")
        print(json.dumps(manifest, ensure_ascii=False))
    elif args.command == "newer":
        newer, published = check_newer(args.current, args.version)
        print(json.dumps({"version": args.version, "published": published,
                          "newer": newer}))
        return 0 if newer else 1
    else:
        print(json.dumps(embed_recognition(args.source, args.app)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
