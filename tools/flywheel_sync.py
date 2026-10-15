"""Recordings from other computers, back on this one (飞轮：录像回流).

On the owner's Mac, after a tester's window uploaded its recordings
(``poker_engine.desktop.aa_upload``):

    PYTHONPATH=src:. .venv/bin/python tools/flywheel_sync.py pull \\
        [--source <云盘里的“PokerSense 同事数据”文件夹，或 rclone 路径>] \\
        [--root <录像目录>] [--ledger <账本.jsonl>] [--no-report]

On a computer that uploads (once; the window does the rest by itself):

    PYTHONPATH=src:. .venv/bin/python tools/flywheel_sync.py setup --machine du
    PYTHONPATH=src:. .venv/bin/python tools/flywheel_sync.py status
    PYTHONPATH=src:. .venv/bin/python tools/flywheel_sync.py push   # upload now

``pull`` reads ``<source>/<机器名>/<录像文件夹名>/`` and copies each recording
whose ``upload.json`` is there (written last by the uploader) into
``<root>/<机器名>-<录像文件夹名>/`` (default root
``PokerSense_private/aa-mac-recordings``), only the files that are missing or
of another size, and checks every file's size against ``upload.json``. A
recording that is not all there yet is left for the next pull. A finished
copy gets ``pulled.json`` (machine, its own folder name, sizes) and its line
in the ledger with the machine's name (``flywheel_session.py ledger`` adds
them up by machine; ``rank`` counts them in). A recording that came without
its check-up sheet gets one made here, unless ``--no-report``.

Without ``--source`` the Google Drive desktop folder is used when there is one
(``~/Library/CloudStorage/GoogleDrive-*/<我的云端硬盘|My Drive>/PokerSense
同事数据``), otherwise rclone with the remote and folder of this computer's
upload settings. Everything pulled stays in the private data folder: it holds
other players' hands.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.data_paths import private_root  # noqa: E402
from poker_engine.desktop import aa_upload  # noqa: E402
from tools import flywheel_session as fly  # noqa: E402

NAME = re.compile(r"[\w\-. ]+")
CLOUD = Path("~/Library/CloudStorage")


def safe_name(name):
    name = str(name).strip().rstrip("/")
    return name if NAME.fullmatch(name) and name not in (".", "..") else None


def safe_file(rel):
    """A file path inside the recording, or None."""
    if not isinstance(rel, str) or not rel or "\\" in rel:
        return None
    path = PurePosixPath(rel)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        return None
    return path


def digest_of(files):
    """As ``aa_upload.manifest`` makes it from the same list."""
    return hashlib.sha256(json.dumps(files).encode("utf-8")).hexdigest()


class LocalSource:
    """A folder on this computer (the Google Drive desktop folder)."""

    def __init__(self, path):
        self.path = Path(path)

    def __str__(self):
        return str(self.path)

    def dirs(self, *parts):
        folder = self.path.joinpath(*parts)
        return sorted(child.name for child in folder.iterdir()
                      if child.is_dir()) if folder.is_dir() else []

    def read(self, *parts):
        try:
            return self.path.joinpath(*parts).read_text(encoding="utf-8")
        except OSError:
            return None

    def fetch(self, parts, files, dest):
        """Copy the files whose size here differs; None, or what went wrong."""
        source = self.path.joinpath(*parts)
        for rel, size in files:
            there, here = source / rel, dest / rel
            if not there.is_file() or there.stat().st_size != size:
                return f"{rel} 在云盘里还不全"
            if here.is_file() and here.stat().st_size == size:
                continue
            here.parent.mkdir(parents=True, exist_ok=True)
            part = here.with_name(here.name + ".part")
            shutil.copyfile(there, part)
            os.replace(part, here)
        return None


class RcloneSource:
    """``<remote>:<folder>`` through rclone."""

    def __init__(self, path, rclone, run=aa_upload.run_process):
        self.path, self.rclone, self.run = path.rstrip("/"), rclone, run

    def __str__(self):
        return self.path

    def _join(self, parts):
        return "/".join([self.path, *parts])

    def dirs(self, *parts):
        code, output = self.run([self.rclone, "lsf", "--dirs-only",
                                 self._join(parts)], 120)
        if code != 0:
            return []
        return sorted(line.strip().rstrip("/") for line in output.splitlines()
                      if line.strip().endswith("/"))

    def read(self, *parts):
        code, output = self.run([self.rclone, "cat", self._join(parts)], 120)
        return output if code == 0 else None

    def fetch(self, parts, files, dest):
        code, output = self.run([self.rclone, "copy", self._join(parts), str(dest),
                                 "--checksum", "--exclude", f"/{aa_upload.MARKER}",
                                 "--transfers", "2", "--retries", "3",
                                 "--stats", "0", "--log-level", "NOTICE"],
                                aa_upload.COPY_TIMEOUT)
        return None if code == 0 else (aa_upload.scrub(output, 1)
                                       or f"rclone 退出码 {code}")


def drive_folder(folder=aa_upload.FOLDER, cloud=CLOUD):
    """The Google Drive desktop copy of the cloud folder, if this Mac has one."""
    for account in sorted(Path(cloud).expanduser().glob("GoogleDrive-*")):
        for mine in ("我的云端硬盘", "My Drive"):
            path = account / mine / folder
            if path.is_dir():
                return path
    return None


def choose_source(text, settings, *, which=shutil.which, run=aa_upload.run_process,
                  cloud=CLOUD):
    if text:
        local = Path(text).expanduser()
        if local.is_dir() or ":" not in text or re.match(r"^[A-Za-z]:[\\/]", text):
            return LocalSource(local)
        rclone = settings["rclone"] or which("rclone")
        return RcloneSource(text, rclone, run) if rclone else None
    found = drive_folder(settings["folder"], cloud)
    if found is not None:
        return LocalSource(found)
    rclone = settings["rclone"] or which("rclone")
    if rclone:
        return RcloneSource(f"{settings['remote']}:{settings['folder']}", rclone, run)
    return None


def pull_one(source, machine, name, root, ledger, *, report=True):
    """(status, text) for one recording in the cloud folder."""
    text = source.read(machine, name, aa_upload.MARKER)
    if text is None:
        return "waiting", f"{machine}/{name}：还没传完，下次再拉"
    try:
        marker = json.loads(text)
        files = [[str(rel), int(size)] for rel, size in marker["files"]]
    except (ValueError, KeyError, TypeError):
        return "bad", f"{machine}/{name}：upload.json 读不懂，跳过"
    if any(safe_file(rel) is None for rel, _ in files):
        return "bad", f"{machine}/{name}：upload.json 里有不在文件夹里的路径，跳过"
    digest = digest_of(files)
    dest = Path(root) / f"{machine}-{name}"
    try:
        done = json.loads((dest / aa_upload.PULLED).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        done = {}
    if done.get("digest") == digest:
        return "same", f"{machine}/{name}：已经拉过"
    dest.mkdir(parents=True, exist_ok=True)
    problem = source.fetch([machine, name], files, dest)
    wrong = [rel for rel, size in files
             if not (dest / rel).is_file() or (dest / rel).stat().st_size != size]
    if problem or wrong:
        detail = problem or f"{len(wrong)} 个文件大小不对（如 {wrong[0]}）"
        return "failed", f"{machine}/{name}：没拉全，{detail}；下次再拉"
    aa_upload.write_json(dest / aa_upload.PULLED, {
        "machine": machine, "folder": name, "files": len(files),
        "bytes": sum(size for _, size in files), "digest": digest,
        "uploaded": marker.get("uploaded")})
    note = ledger_line(dest, machine, ledger, report=report)
    return "pulled", f"{machine}/{name} → {dest.name}（{note}）"


def ledger_line(dest, machine, ledger, *, report=True):
    """The pulled session in the ledger with its machine's name."""
    sheet = dest / fly.FOLDER
    try:
        item = json.loads((sheet / "summary.json").read_text(encoding="utf-8"))
        hands = json.loads((sheet / "hands.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        item = hands = None
    if item is not None and hands is not None:
        if ledger is not None:
            item.update(label=dest.name, machine=machine)
            fly.add_to_ledger(ledger, item, hands)
        return "体检单随录像来了，已记账"
    if not report or not (dest / "frames.jsonl").exists():
        return "没有体检单"
    try:
        fly.report(dest, ledger)
    except Exception as exc:          # the files are here; the sheet can wait
        return f"体检单没做成：{exc}"
    return "体检单在这里做好，已记账"


def pull(source, root, ledger, *, report=True, out=print):
    counts = {}
    for machine in source.dirs():
        if safe_name(machine) is None:
            continue
        for name in source.dirs(machine):
            if safe_name(name) is None:
                continue
            status, text = pull_one(source, machine, name, root, ledger,
                                    report=report)
            counts[status] = counts.get(status, 0) + 1
            if status != "same":
                out(text)
    out(f"新拉回 {counts.get('pulled', 0)} 场；已有 {counts.get('same', 0)} 场；"
        f"还没传完 {counts.get('waiting', 0)} 场；没拉全 {counts.get('failed', 0)} 场。")
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    take = commands.add_parser("pull")
    take.add_argument("--source")
    take.add_argument("--root", type=Path)
    take.add_argument("--ledger", type=Path)
    take.add_argument("--no-ledger", action="store_true")
    take.add_argument("--no-report", action="store_true")
    setup = commands.add_parser("setup")
    setup.add_argument("--machine")
    setup.add_argument("--remote")
    setup.add_argument("--folder")
    setup.add_argument("--bwlimit")
    setup.add_argument("--rclone")
    commands.add_parser("status")
    commands.add_parser("push")
    for command in (setup, commands.choices["status"], commands.choices["push"]):
        command.add_argument("--root", type=Path)
    args = parser.parse_args(argv)
    base = private_root() / "upload"
    root = args.root or fly.default_root()
    uploader = aa_upload.Uploader(root, base=base)
    if args.command == "pull":
        source = choose_source(args.source, uploader.settings())
        if source is None:
            print("找不到云盘：这台电脑没有 Google Drive 桌面版的“"
                  f"{aa_upload.FOLDER}”文件夹，也没有 rclone。用 --source 指定。")
            return 2
        print(f"从 {source} 拉到 {root}")
        ledger = None if args.no_ledger else (args.ledger or fly.default_ledger())
        counts = pull(source, root, ledger, report=not args.no_report)
        return 1 if counts.get("failed") or counts.get("bad") else 0
    if args.command == "setup":
        try:
            stored = json.loads(uploader.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        for key in ("machine", "remote", "folder", "bwlimit", "rclone"):
            value = getattr(args, key)
            if value is not None:
                stored[key] = (aa_upload.machine_name(value) if key == "machine"
                               else value)
        if not stored.get("rclone"):
            # The full path: a window started before rclone was on the
            # PATH finds it anyway.
            found = aa_upload.find_rclone(which=shutil.which)
            if found:
                stored["rclone"] = str(Path(found).resolve())
        aa_upload.write_json(uploader.settings_path, stored)
    if args.command == "push":
        settings = uploader.settings()
        if not uploader._check(settings):
            print(f"未配置上传：没有 rclone，或 rclone 里没有 {settings['remote']}。")
            return 2
        settings["enabled"] = True        # asked for by hand: the switch aside
        ok = all(uploader.upload(folder, settings) for folder in uploader.pending())
        print("都传好了。" if ok else f"没传完：{uploader.last_error}")
    status = uploader.status()
    status["waiting"] = len(uploader.pending())
    status["message"] = uploader.message(status)
    status["settings_file"] = str(uploader.settings_path)
    print(json.dumps(status, ensure_ascii=False, indent=1))
    return 0 if args.command != "push" or status["last_error"] is None else 1


if __name__ == "__main__":
    sys.exit(main())
