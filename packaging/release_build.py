"""Release-build steps of the Windows workflow (.github/workflows/windows-release.yml).

    stamp       write the release version into the checkout (not committed)
    config      write update-config.json (the manifest address) next to the program
    manifest    write the version manifest for a built installer
    newer       fail unless a version is newer than the published manifest's
    recognition-check
                check the recognition bundle zip uploaded next to the release
                (tools/pack_aa_recognition.py) before the manifest lists it;
                the bundle is never put inside the installer
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

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


def normalize_download_url(url):
    """Turn an ``rclone link`` (or other share page) into a direct download URL
    for ``latest.json``."""
    return app_update.direct_url(url.strip())


def write_config(manifest_url, out):
    out = Path(out)
    out.write_text(json.dumps({"manifest_url": manifest_url}, indent=2) + "\n",
                   "utf-8")
    return out


def read_recognition(source):
    """The sidecar of the uploaded recognition zip, after checking the zip's
    size and sha256 against it."""
    source = Path(source)
    sidecar = json.loads((source / RECOGNITION_JSON).read_text("utf-8"))
    archive = source / RECOGNITION_ZIP
    if sidecar.get("schema") != RECOGNITION_SCHEMA:
        raise SystemExit("recognition sidecar schema mismatch")
    if (archive.stat().st_size != sidecar["zip_bytes"]
            or sha256_file(archive) != sidecar["zip_sha256"]):
        raise SystemExit("recognition zip does not match its sidecar")
    return sidecar


def check_recognition(source):
    """Unpack the uploaded zip as the program will and validate the bundle
    against the manifest digest it will trust."""
    from poker_engine.desktop.aa_bundle import validate_bundle
    sidecar = read_recognition(source)
    with tempfile.TemporaryDirectory(prefix="pokersense-recognition-") as folder:
        target = Path(folder) / "bundle"
        try:
            app_update.safe_extract(Path(source) / RECOGNITION_ZIP, target)
        except app_update.UpdateError as error:
            raise SystemExit(str(error)) from error
        receipt = validate_bundle(target / "profile.json", sidecar["manifest_sha256"])
    return {"zip_sha256": sidecar["zip_sha256"], "zip_bytes": sidecar["zip_bytes"],
            "manifest_sha256": sidecar["manifest_sha256"], "files": receipt["files"]}


def build_manifest(version, installer, url, commit="", notes="", now=None,
                   recognition=None, recognition_url=None):
    """``recognition``: folder with the uploaded zip and its sidecar, listed
    with ``recognition_url`` (its share link)."""
    installer = Path(installer)
    installer_url = normalize_download_url(url)
    manifest = {
        "schema": app_update.SCHEMA, "product": app_update.PRODUCT,
        "version": version,
        "published": (now or datetime.now(timezone.utc)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit, "notes": notes,
        "installer": {"url": installer_url, "sha256": sha256_file(installer),
                      "bytes": installer.stat().st_size},
    }
    if recognition is not None:
        sidecar = read_recognition(recognition)
        manifest["recognition"] = {
            "url": normalize_download_url(recognition_url),
            "sha256": sidecar["zip_sha256"],
            "bytes": sidecar["zip_bytes"],
            "manifest_sha256": sidecar["manifest_sha256"],
            "created": sidecar.get("created", "")}
    return app_update.validate_manifest(manifest)


def check_newer(current_path, version):
    """True when nothing valid is published yet or ``version`` is newer."""
    try:
        current = json.loads(Path(current_path).read_text("utf-8-sig"))
        published = app_update.validate_manifest(current)["version"]
    except (OSError, ValueError, app_update.UpdateError):
        return True, None
    return app_update.is_newer(version, published), published


def render_upload_commands(version):
    """Mac upload steps after a Wine/CI build (stdout or ``upload-commands``)."""
    return f"""# Mac 上传 PokerSense AA {version} 安装包到 Google Drive

前提：Mac 上已配置 rclone remote `pokersense`（`drive.file`，文件夹 `PokerSense-AA`）。
安装包在 `~/Downloads/PokerSense-AA-Setup.exe`，`latest.json` 由发版脚本生成。

**版本号：`{version}`**

## 1. 先传安装包（含版本归档）

```bash
VERSION="{version}"
SETUP="$HOME/Downloads/PokerSense-AA-Setup.exe"
test -f "$SETUP"

rclone copyto "$SETUP" \\
  "pokersense:PokerSense-AA/versions/PokerSense-AA-Setup-${{VERSION}}.exe" --progress
rclone copyto "$SETUP" "pokersense:PokerSense-AA/PokerSense-AA-Setup.exe" --progress
```

## 2. 更新 `latest.json` 里的安装包直链后再传清单（必须最后传）

`rclone link` 给出的是 `drive.google.com/open?id=…` 页面链接，浏览器会 400；
下面用 `release_build.py direct-url` 换成 `drive.usercontent.google.com` 直链再写入清单。

```bash
VERSION="{version}"
MANIFEST="$HOME/Downloads/latest.json"
test -f "$MANIFEST"
REPO=~/Projects/PokerSense   # 改成你的仓库路径

SHARE_URL="$(rclone link "pokersense:PokerSense-AA/PokerSense-AA-Setup.exe" \\
  | tr -d '\\r\\n')"
export INSTALLER_URL="$(cd "$REPO" && PYTHONPATH=src:. \\
  .venv/bin/python packaging/release_build.py direct-url --url "$SHARE_URL")"
python3 - <<'PY'
import json, os
path = os.path.expanduser("~/Downloads/latest.json")
data = json.load(open(path, encoding="utf-8"))
data["installer"]["url"] = os.environ["INSTALLER_URL"]
json.dump(data, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print(data["installer"]["url"])
PY

rclone copyto "$MANIFEST" "pokersense:PokerSense-AA/latest.json" --progress
```

识别资源包仍按 `docs/windows-distribution.md` 上传；需要时在 Mac 上用
`packaging/release_build.py manifest` 带上 `--recognition-dir` / `--recognition-url`
（识别包链接也会自动换成直链）重新生成 `latest.json` 后再执行第 2 步。

## 3. 上传后检查

```bash
rclone lsl "pokersense:PokerSense-AA" \\
  --include "PokerSense-AA-Setup.exe" --include "latest.json" \\
  --include "versions/PokerSense-AA-Setup-{version}.exe"
rclone copyto "pokersense:PokerSense-AA/latest.json" /tmp/pokersense-latest-check.json
python3 -m json.tool /tmp/pokersense-latest-check.json | head -30
sha256sum "$HOME/Downloads/PokerSense-AA-Setup.exe"
python3 - <<'PY'
import hashlib, json, pathlib
setup = pathlib.Path.home() / "Downloads/PokerSense-AA-Setup.exe"
manifest = json.load(open("/tmp/pokersense-latest-check.json", encoding="utf-8"))
digest = hashlib.sha256(setup.read_bytes()).hexdigest()
assert digest == manifest["installer"]["sha256"], (
    digest, manifest["installer"]["sha256"])
assert setup.stat().st_size == manifest["installer"]["bytes"]
assert manifest["version"] == "{version}"
print("installer sha256/bytes OK, version", manifest["version"])
PY
```
"""


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
    command.add_argument("--recognition-dir", type=Path)
    command.add_argument("--recognition-url")
    command.add_argument("--out", type=Path, required=True)
    command = commands.add_parser("newer")
    command.add_argument("--current", type=Path, required=True)
    command.add_argument("--version", required=True)
    command = commands.add_parser("recognition-check")
    command.add_argument("--source", type=Path, required=True)
    command = commands.add_parser("direct-url",
                                  help="normalize rclone / share link for downloads")
    command.add_argument("--url", required=True)
    command = commands.add_parser("upload-commands",
                                  help="write Mac upload steps (Google Drive)")
    command.add_argument("--version", required=True)
    command.add_argument("--out", type=Path, required=True)
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
        if (args.recognition_dir is None) != (args.recognition_url is None):
            parser.error("--recognition-dir and --recognition-url go together")
        manifest = build_manifest(args.version, args.installer, args.url,
                                  args.commit, args.notes,
                                  recognition=args.recognition_dir,
                                  recognition_url=args.recognition_url)
        args.out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                            "utf-8")
        print(json.dumps(manifest, ensure_ascii=False))
    elif args.command == "newer":
        newer, published = check_newer(args.current, args.version)
        print(json.dumps({"version": args.version, "published": published,
                          "newer": newer}))
        return 0 if newer else 1
    elif args.command == "direct-url":
        print(normalize_download_url(args.url))
    elif args.command == "upload-commands":
        text = render_upload_commands(args.version)
        args.out.write_text(text, encoding="utf-8")
        print(args.out)
    else:
        print(json.dumps(check_recognition(args.source)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
