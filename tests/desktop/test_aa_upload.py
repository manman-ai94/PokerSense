"""Recordings uploaded with rclone or into a synced cloud folder, with
stand-ins for rclone and the cloud."""

from fnmatch import fnmatch
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

from fastapi.testclient import TestClient

from poker_engine.desktop import aa_after_session, aa_server, aa_upload

HEADERS = {"X-AA-Live": "1"}
ROOT = Path(__file__).resolve().parents[2]


class FakeRclone:
    """``run(args, timeout)`` the way rclone answers, with ``cloud`` as the
    remote ``pokersense-upload:``. ``failing`` makes every transfer fail the
    way rclone reports one (no real network is ever touched); ``remotes`` is
    what ``listremotes`` lists."""

    def __init__(self, cloud, remotes=("pokersense-upload",)):
        self.cloud = Path(cloud)
        self.remotes = list(remotes)
        self.failing = False
        self.calls = []

    def where(self, path):
        remote, _, rest = path.partition(":")
        assert remote in self.remotes
        return self.cloud / rest

    def __call__(self, args, timeout):
        self.calls.append(args)
        command = args[1]
        if command == "listremotes":
            return 0, "".join(f"{name}:\n" for name in self.remotes)
        if self.failing:
            return 1, ("2026/10/14 Failed to copy: dial tcp: lookup www.googleapis.com:"
                       " no such host\nrefresh token: secret-should-not-show\n")
        if command == "copy":
            source, target = Path(args[2]), self.where(args[3])
            for path in sorted(source.rglob("*")):
                rel = path.relative_to(source).as_posix()
                if path.is_file() and passes(args, rel):
                    (target / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target / rel)
            return 0, ""
        if command == "dedupe":
            check_dedupe(args)
            return 0, ""
        if command == "copyto":
            target = self.where(args[3])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(args[2], target)
            return 0, ""
        raise AssertionError(args)

    def copies(self):
        return [args for args in self.calls if args[1] in ("copy", "copyto")]


def passes(args, rel):
    """rclone's ``--include`` / ``--exclude``: the first rule that matches
    decides, and with any ``--include`` a file no rule matches is left out
    (a leading "/" anchors the rule at the folder's top)."""
    rules = [(args[at], args[at + 1]) for at in range(len(args) - 1)
             if args[at] in ("--include", "--exclude")]
    for flag, rule in rules:
        anchored = rule.startswith("/")
        rule = rule.lstrip("/")
        if (fnmatch(rel, rule) if anchored and "/" not in rule or "/" in rel
                and anchored else fnmatch(rel.rsplit("/", 1)[-1], rule)):
            return flag == "--include"
    return not any(flag == "--include" for flag, _ in rules)


def cloud_files(folder):
    return sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*")
                  if path.is_file()) if folder.is_dir() else []


# What rclone's ``dedupe --dedupe-mode`` accepts (fs/operations/dedupe.go,
# DeduplicateMode.Set, v1.75.2); anything else fails with "unknown mode for
# dedupe" before it looks at the remote.
DEDUPE_MODES = ("interactive", "skip", "first", "newest", "oldest", "rename",
                "largest", "smallest", "list")


def check_dedupe(args):
    """Fail the test where real rclone would refuse the command."""
    mode = args[args.index("--dedupe-mode") + 1]
    assert mode.lower() in DEDUPE_MODES, f"rclone: unknown mode for dedupe {mode!r}"
    int(args[args.index("--max-depth") + 1])


def recording(root, name, *, finished=True, sheet=True):
    folder = Path(root) / name
    folder.mkdir(parents=True)
    (folder / "segment_0000.mp4").write_bytes(b"\0" * 1000)
    (folder / "segments.csv").write_text("segment_0000.mp4,0,60\n", encoding="utf-8")
    (folder / "frames.jsonl").write_text('{"code": {"commit": "abc"}}\n',
                                         encoding="utf-8")
    if finished:
        (folder / "recording.json").write_text("{}", encoding="utf-8")
    if sheet:
        (folder / "flywheel").mkdir()
        (folder / "flywheel" / "体检单.txt").write_text("体检单\n", encoding="utf-8")
        (folder / "flywheel" / "package.json").write_text("{}", encoding="utf-8")
    return folder


def uploader(tmp_path, rclone, **options):
    base = tmp_path / "upload"
    base.mkdir(exist_ok=True)
    settings = base / "settings.json"
    if not settings.exists():
        settings.write_text(json.dumps({"machine": "du"}), encoding="utf-8")
    options.setdefault("cloud", tmp_path / "no-cloud-app")
    return aa_upload.Uploader(tmp_path / "recordings", base=base, run=rclone,
                              which=lambda name: "rclone", **options)


def test_a_finished_recording_goes_up_whole_with_its_list_last(tmp_path):
    folder = recording(tmp_path / "recordings", "20261014-201500-live")
    recording(tmp_path / "recordings", "20261014-230000-live", finished=False)
    rclone = FakeRclone(tmp_path / "cloud")
    up = uploader(tmp_path, rclone)
    assert up.upload_all() is True
    there = tmp_path / "cloud" / "PokerSense 同事数据" / "du" / folder.name
    assert sorted(p.relative_to(there).as_posix() for p in there.rglob("*")
                  if p.is_file()) == ["flywheel/package.json", "flywheel/体检单.txt",
                                      "frames.jsonl", "recording.json",
                                      "segment_0000.mp4", "segments.csv",
                                      "upload.json"]
    marker = json.loads((there / "upload.json").read_text(encoding="utf-8"))
    assert marker["machine"] == "du" and marker["folder"] == folder.name
    assert marker["files"] == aa_upload.manifest(folder)["files"]
    *copies, last = rclone.copies()
    assert len(copies) == 3                   # the package first, the video last
    copy = copies[-1]
    assert copy[3] == f"pokersense-upload:PokerSense 同事数据/du/{folder.name}"
    assert "--checksum" in copy and copy[copy.index("--bwlimit") + 1] == "1M"
    assert last[1] == "copyto" and last[3].endswith("/upload.json")
    state = json.loads((tmp_path / "upload" / "state.json").read_text("utf-8"))
    assert list(state) == [folder.name]       # the one still recording waits
    status = up.status()
    assert status["configured"] and status["uploaded"] == 1
    assert status["message"].startswith("录像自动上传：开")
    up.upload_all()                           # nothing new: nothing sent
    assert len(rclone.copies()) == 4


def test_same_named_folders_are_merged_before_the_list_is_written(tmp_path):
    """Drive keeps two folders of one name (11 of them on 2026-10-15): they
    are merged after the files and before ``upload.json``; a failed merge
    does not stop the upload."""
    recording(tmp_path / "recordings", "20261015-102047-live")

    class Rclone(FakeRclone):
        merge_code = 0

        def __call__(self, args, timeout):
            if args[1] == "dedupe":
                check_dedupe(args)
                self.calls.append(args)
                return self.merge_code, "Failed to dedupe: rate limit"
            return super().__call__(args, timeout)

    rclone = Rclone(tmp_path / "cloud")
    up = uploader(tmp_path, rclone)
    assert up.upload_all() is True
    order = [args[1] for args in rclone.calls if args[1] != "listremotes"]
    assert order == ["copy", "copy", "copy", "dedupe", "copyto"]
    dedupe = next(args for args in rclone.calls if args[1] == "dedupe")
    # Down to <folder>/<machine>/<recording>/flywheel; "skip" merges folders
    # (only "list" does not) and leaves files that differ alone.
    assert dedupe[2:7] == ["--dedupe-mode", "skip", "--max-depth", "4",
                           "pokersense-upload:"]
    recording(tmp_path / "recordings", "20261015-120000-live")
    rclone.merge_code = 1
    assert up.upload_all() is True
    log = (tmp_path / "upload" / "upload.log").read_text(encoding="utf-8")
    assert "同名文件夹没合并" in log


def test_a_failed_merge_never_blocks_or_fails_the_upload(tmp_path):
    """rclone refusing or failing the merge (rate limit, timeout, a bad
    flag: 2026-10-15 every merge failed with "unknown mode for dedupe") still
    uploads every file and ``upload.json`` and counts the recording as done."""
    folder = recording(tmp_path / "recordings", "20261015-102047-live")

    class Rclone(FakeRclone):
        def __call__(self, args, timeout):
            if args[1] == "dedupe":
                self.calls.append(args)
                return 1, 'Failed to dedupe: unknown mode for dedupe "merge"'
            return super().__call__(args, timeout)

    rclone = Rclone(tmp_path / "cloud")
    up = uploader(tmp_path, rclone)
    assert up.upload_all() is True
    assert up.last_error is None
    sent = tmp_path / "cloud" / "PokerSense 同事数据" / "du" / folder.name
    marker = json.loads((sent / "upload.json").read_text(encoding="utf-8"))
    assert marker["files"] == aa_upload.manifest(folder)["files"]
    state = json.loads((tmp_path / "upload" / "state.json").read_text(encoding="utf-8"))
    assert folder.name in state
    copies = len(rclone.copies())
    assert up.upload_all() is True               # done: not sent again
    assert len(rclone.copies()) == copies


def test_the_merge_reaches_the_flywheel_folders_under_a_deeper_folder():
    assert aa_upload.merge_depth({"folder": "PokerSense 同事数据"}) == 4
    assert aa_upload.merge_depth({"folder": "Shared/PokerSense 同事数据"}) == 5


def test_a_failed_upload_leaves_the_recording_alone_and_is_tried_again(tmp_path):
    folder = recording(tmp_path / "recordings", "20261014-201500-live")
    before = aa_upload.manifest(folder)
    rclone = FakeRclone(tmp_path / "cloud")
    rclone.failing = True
    up = uploader(tmp_path, rclone, delay=0, retry_waits=(0.05,))
    assert up.upload_all() is False
    assert aa_upload.manifest(folder) == before        # the recording untouched
    assert not (tmp_path / "cloud").exists()
    status = up.status()
    assert "上次上传没成功" in status["message"] and "no such host" in status["message"]
    log = (tmp_path / "upload" / "upload.log").read_text(encoding="utf-8")
    assert "没传完" in log and "secret" not in log and "token" not in log
    # The thread tries again by itself; this time rclone succeeds.
    up.start()
    try:
        rclone.failing = False
        deadline = time.monotonic() + 5
        while (time.monotonic() < deadline
               and not (tmp_path / "upload" / "state.json").exists()):
            time.sleep(0.02)
    finally:
        up.stop()
    assert (tmp_path / "upload" / "state.json").exists()
    assert up.status()["last_error"] is None


def test_the_next_start_sends_what_the_last_one_did_not(tmp_path):
    root = tmp_path / "recordings"
    done = recording(root, "20261014-201500-live")
    rclone = FakeRclone(tmp_path / "cloud")
    uploader(tmp_path, rclone).upload_all()
    cut = recording(root, "20261014-213000-live")           # app closed before
    (done / "flywheel" / "hands.json").write_text("[]", encoding="utf-8")  # later
    pulled = recording(root, "du-20261013-101010-live")
    (pulled / aa_upload.PULLED).write_text("{}", encoding="utf-8")
    again = uploader(tmp_path, rclone)                     # a new start
    assert [folder.name for folder in again.pending()] == [done.name, cut.name]
    rclone.calls.clear()
    assert again.upload_all() is True
    assert [args[2] for args in rclone.copies() if args[1] == "copy"] == [
        str(done)] * 3 + [str(cut)] * 3
    assert again.pending() == []


def test_without_rclone_or_its_remote_the_window_only_says_so(tmp_path):
    recording(tmp_path / "recordings", "20261014-201500-live")
    rclone = FakeRclone(tmp_path / "cloud", remotes=("pokersense",))
    up = uploader(tmp_path, rclone)
    assert up.upload_all() is True and rclone.copies() == []
    status = up.status()
    assert status["configured"] is False and status["message"].startswith("未配置上传")
    none = aa_upload.Uploader(tmp_path / "recordings", base=tmp_path / "upload",
                              run=rclone, which=lambda name: None, places=[],
                              cloud=tmp_path / "no-cloud-app")
    assert none.status()["configured"] is False and none.upload_all() is True


def test_the_switch_is_kept_and_turning_it_on_sends_what_waits(tmp_path):
    recording(tmp_path / "recordings", "20261014-201500-live")
    rclone = FakeRclone(tmp_path / "cloud")
    up = uploader(tmp_path, rclone)
    assert up.set_enabled(False)["message"].startswith("录像自动上传：已关")
    stored = json.loads((tmp_path / "upload" / "settings.json").read_text("utf-8"))
    assert stored == {"machine": "du", "enabled": False}
    assert up.upload_all() is True and rclone.copies() == []
    assert up.set_enabled(True)["enabled"] is True
    up.upload_all()
    assert len(rclone.copies()) == 4


def test_settings_default_and_bad_values(tmp_path):
    path = tmp_path / "settings.json"
    settings = aa_upload.load_settings(path)
    assert settings["enabled"] is True and settings["remote"] == "pokersense-upload"
    assert settings["folder"] == "PokerSense 同事数据" and settings["machine"]
    path.write_text(json.dumps({"enabled": "no", "remote": "x:", "machine": "杜 的/PC"}),
                    encoding="utf-8")
    settings = aa_upload.load_settings(path)
    assert settings["enabled"] is True and settings["remote"] == "x"
    assert settings["machine"] == "杜-的-PC"
    path.write_text("not json", encoding="utf-8")
    assert aa_upload.load_settings(path)["enabled"] is True


def test_the_upload_waits_for_the_check_up_sheet(tmp_path):
    folder = recording(tmp_path / "recordings", "20261014-201500-live")
    order = []

    class Sheet:
        def wait(self, timeout):
            order.append(("sheet", timeout))

    class Rclone(FakeRclone):
        def __call__(self, args, timeout):
            if args[1] == "copy":
                order.append(("copy", args[2]))
            return super().__call__(args, timeout)

    up = uploader(tmp_path, Rclone(tmp_path / "cloud"))
    got = aa_after_session.after_recording(folder, report=lambda path: Sheet(),
                                           uploader=up)
    assert isinstance(got, Sheet)
    up.upload_all()
    assert order == [("sheet", aa_upload.REPORT_WAIT)] + [("copy", str(folder))] * 3


def test_the_package_and_the_log_go_up_before_the_video(tmp_path):
    """The sheet and the session package are written first; then they and the
    other small files go up, the window's log next, the video segments last,
    and ``upload.json`` once everything is there."""
    folder = recording(tmp_path / "recordings", "20261016-102047-live", sheet=False)
    (folder / "segment_0001.mp4").write_bytes(b"\0" * 10)
    cloud = tmp_path / "cloud" / aa_upload.FOLDER / "du" / folder.name
    seen = []

    class Sheet:
        def wait(self, timeout):
            seen.append(["sheet"])
            (folder / "flywheel").mkdir()
            (folder / "flywheel" / "体检单.txt").write_bytes("体检单\n".encode())
            (folder / "flywheel" / "package.json").write_text("{}", encoding="utf-8")

    class Rclone(FakeRclone):
        def __call__(self, args, timeout):
            answer = super().__call__(args, timeout)
            if args[1] in ("copy", "copyto"):
                seen.append(cloud_files(cloud))
            return answer

    up = uploader(tmp_path, Rclone(tmp_path / "cloud"))
    up.submit(folder, wait_for=Sheet())
    assert up.upload_all() is True
    small = ["flywheel/package.json", "flywheel/体检单.txt", "recording.json",
             "segments.csv"]
    assert seen == [["sheet"], small, sorted(small + ["frames.jsonl"]),
                    sorted(small + ["frames.jsonl", "segment_0000.mp4",
                                    "segment_0001.mp4"]),
                    sorted(small + ["frames.jsonl", "segment_0000.mp4",
                                    "segment_0001.mp4", aa_upload.MARKER])]
    marker = json.loads((cloud / aa_upload.MARKER).read_text(encoding="utf-8"))
    assert ["flywheel/package.json", 2] in marker["files"]


def test_which_pass_a_file_goes_up_in():
    assert aa_upload.upload_pass("flywheel/package.json") == 0
    assert aa_upload.upload_pass("recording.json") == 0
    assert aa_upload.upload_pass("frames.jsonl") == 1
    assert aa_upload.upload_pass("segment_0012.mp4") == 2
    assert aa_upload.upload_pass("flywheel/segment_0000.mp4") == 0
    assert aa_upload.upload_pass("flywheel/frames.jsonl") == 0


def test_a_failed_pass_stops_before_the_video_and_the_list(tmp_path):
    folder = recording(tmp_path / "recordings", "20261016-102047-live")
    cloud = tmp_path / "cloud" / aa_upload.FOLDER / "du" / folder.name

    class Rclone(FakeRclone):
        def __call__(self, args, timeout):
            if args[1] == "copy" and "--include" in args:
                return 1, "Failed to copy: dial tcp: i/o timeout\n"
            return super().__call__(args, timeout)

    up = uploader(tmp_path, Rclone(tmp_path / "cloud"))
    assert up.upload_all() is False
    assert "i/o timeout" in up.last_error
    assert cloud_files(cloud) == ["flywheel/package.json", "flywheel/体检单.txt",
                                  "recording.json", "segments.csv"]
    assert up.pending() == [folder]           # tried again later


def drive(tmp_path, account="GoogleDrive-peng@example.com", mine="我的云端硬盘"):
    """A Google Drive for desktop folder the way macOS keeps it."""
    folder = tmp_path / "CloudStorage" / account / mine / aa_upload.FOLDER
    (folder / "du").mkdir(parents=True)
    return folder


def test_without_rclone_the_macs_google_drive_folder_is_used(tmp_path):
    """The owner's Mac: no rclone remote, but Google Drive for desktop keeps
    the cloud folder in sync; the recording is copied into ``peng/`` there in
    the same three passes, ``upload.json`` last, and no new sign-in."""
    synced = drive(tmp_path)
    folder = recording(tmp_path / "recordings", "20261016-201500-live")
    (tmp_path / "upload").mkdir()
    (tmp_path / "upload" / "settings.json").write_text(
        json.dumps({"machine": "peng", "player": "peng"}), encoding="utf-8")
    order = []
    real = aa_upload.copy_slowly

    def copy(source, target, limit, sleep=time.sleep, clock=time.monotonic):
        order.append(Path(target).relative_to(synced / "peng" / folder.name)
                     .as_posix())
        real(source, target, limit, sleep=sleep, clock=clock)

    rclone = FakeRclone(tmp_path / "cloud", remotes=())
    up = uploader(tmp_path, rclone, cloud=tmp_path / "CloudStorage",
                  sleep=lambda seconds: None)
    try:
        aa_upload.copy_slowly = copy
        assert up.upload_all() is True
    finally:
        aa_upload.copy_slowly = real
    assert rclone.copies() == []
    there = synced / "peng" / folder.name
    assert order == ["flywheel/package.json", "flywheel/体检单.txt", "recording.json",
                     "segments.csv", "frames.jsonl", "segment_0000.mp4"]
    marker = json.loads((there / aa_upload.MARKER).read_text(encoding="utf-8"))
    assert marker["machine"] == "peng"
    assert marker["files"] == aa_upload.manifest(folder)["files"]
    assert not list(there.rglob("*.part"))
    status = up.status()
    assert status["configured"] and status["way"] == "folder"
    assert status["destination"] == str(synced / "peng")
    assert up.pending() == []
    assert aa_upload.drive_folder(cloud=tmp_path / "CloudStorage") == synced
    assert aa_upload.drive_folder(cloud=tmp_path / "nothing") is None


def test_the_synced_folder_can_be_named_and_a_bad_one_is_not_used(tmp_path):
    named = tmp_path / "elsewhere" / aa_upload.FOLDER
    named.parent.mkdir()
    recording(tmp_path / "recordings", "20261016-201500-live")
    (tmp_path / "upload").mkdir()
    settings = tmp_path / "upload" / "settings.json"
    settings.write_text(json.dumps({"machine": "peng", "drive": str(named)}),
                        encoding="utf-8")
    up = uploader(tmp_path, FakeRclone(tmp_path / "cloud", remotes=()),
                  sleep=lambda seconds: None)
    assert up.upload_all() is True
    assert (named / "peng" / "20261016-201500-live" / aa_upload.MARKER).is_file()
    settings.write_text(json.dumps({"machine": "peng",
                                    "drive": str(tmp_path / "gone" / "x" / "y")}),
                        encoding="utf-8")
    again = uploader(tmp_path, FakeRclone(tmp_path / "cloud", remotes=()))
    assert again.status()["configured"] is False


def test_rclone_with_its_remote_comes_before_the_synced_folder(tmp_path):
    synced = drive(tmp_path)
    folder = recording(tmp_path / "recordings", "20261016-201500-live")
    rclone = FakeRclone(tmp_path / "cloud")
    up = uploader(tmp_path, rclone, cloud=tmp_path / "CloudStorage")
    assert up.upload_all() is True
    assert up.status()["way"] == "rclone" and len(rclone.copies()) == 4
    assert not (synced / "du" / folder.name).exists()


def test_recordings_before_since_stay_on_this_computer(tmp_path):
    root = tmp_path / "recordings"
    recording(root, "20261015-235900-live")
    new = recording(root, "20261016-090000-live")
    (tmp_path / "upload").mkdir()
    (tmp_path / "upload" / "settings.json").write_text(
        json.dumps({"machine": "peng", "since": "20261016"}), encoding="utf-8")
    up = uploader(tmp_path, FakeRclone(tmp_path / "cloud"))
    assert up.pending() == [new]


def test_the_copy_into_a_synced_folder_keeps_to_the_speed_limit(tmp_path):
    source = tmp_path / "big.mp4"
    source.write_bytes(b"x" * (3 * aa_upload.CHUNK + 5))
    now, slept = [0.0], []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    target = tmp_path / "out" / "big.mp4"
    aa_upload.copy_slowly(source, target, aa_upload.CHUNK, sleep=sleep,
                          clock=lambda: now[0])
    assert target.read_bytes() == source.read_bytes()
    assert now[0] >= 3.0 and len(slept) == 4      # one chunk a second
    assert not (tmp_path / "out" / "big.mp4.part").exists()
    slept.clear()
    aa_upload.copy_slowly(source, target, 0, sleep=sleep)
    assert slept == []


def test_the_speed_limit_reads_like_rclones():
    assert aa_upload.rate("1M") == 1024 ** 2
    assert aa_upload.rate("512K") == 512 * 1024
    assert aa_upload.rate("100") == 100 * 1024     # rclone's unit is KiB/s
    assert aa_upload.rate("0") == 0 and aa_upload.rate("") == 0
    assert aa_upload.rate("08:00,512k 12:00,off") == 0


def test_a_configured_rclone_that_is_gone_is_passed_over(tmp_path):
    """Homebrew or winget upgraded rclone into a new folder: the saved path is
    gone, and uploads must not stay off for good."""
    gone = str(tmp_path / "Cellar" / "1.75.2" / "rclone")
    assert aa_upload.find_rclone(gone, which=lambda n: "/bin/rclone") == "/bin/rclone"
    assert aa_upload.find_rclone(gone, which=lambda n: None, places=[]) == ""
    assert aa_upload.find_rclone("rclone", which=lambda n: None) == "rclone"


def test_rclone_off_the_window_path_is_found(tmp_path):
    """A window started before rclone was put on the PATH (杜's PC, 2026-10-15)."""
    name = "rclone.exe" if os.name == "nt" else "rclone"
    nowhere = tmp_path / "empty"
    nowhere.mkdir()
    (tmp_path / name).write_bytes(b"")
    there = str(tmp_path / name)
    assert aa_upload.find_rclone(there, which=lambda n: "/bin/rclone") == there
    assert aa_upload.find_rclone(which=lambda n: "/bin/rclone") == "/bin/rclone"
    assert aa_upload.find_rclone(which=lambda n: None,
                                 places=[nowhere, tmp_path]) == str(tmp_path / name)
    assert aa_upload.find_rclone(which=lambda n: None, places=[nowhere]) == ""
    up = aa_upload.Uploader(tmp_path / "recordings", base=tmp_path / "upload",
                            run=FakeRclone(tmp_path / "cloud"),
                            which=lambda n: None, places=[tmp_path])
    assert up.status()["configured"] is True


def test_after_recording_hands_the_folder_over_even_when_the_sheet_fails(tmp_path):
    seen = []

    class Up:
        def submit(self, folder, wait_for=None):
            seen.append((folder, wait_for))

    def broken(folder):
        raise OSError("disk")

    try:
        aa_after_session.after_recording(tmp_path, report=broken, uploader=Up())
    except OSError:
        pass
    assert seen == [(tmp_path, None)]
    assert aa_after_session.after_recording(tmp_path, report=lambda f: None,
                                            uploader=None) is None


def test_the_started_uploader_is_the_one_recordings_reach(tmp_path):
    up = uploader(tmp_path, FakeRclone(tmp_path / "cloud"), delay=60)
    up.start()
    try:
        assert aa_upload.current() is up
        seen = threading.Event()
        up.submit = lambda folder, wait_for=None: seen.set()
        aa_after_session.after_recording(tmp_path, report=lambda f: None)
        assert seen.is_set()
    finally:
        up.stop()
    assert aa_upload.current() is None


def test_the_window_shows_and_keeps_the_switch(tmp_path):
    class Up:
        def __init__(self):
            self.on, self.started, self.stopped = True, 0, 0

        def start(self):
            self.started += 1

        def stop(self):
            self.stopped += 1

        def status(self):
            return {"available": True, "enabled": self.on, "message": "x"}

        def set_enabled(self, on):
            self.on = on
            return self.status()

    up = Up()
    app = aa_server.create_app(tmp_path / "missing.json", replay_pool=tmp_path,
                               uploader=up)
    with TestClient(app) as client:
        assert up.started == 1
        assert client.get("/api/upload").json()["enabled"] is True
        assert client.post("/api/upload", json={"on": False}).status_code == 403
        assert client.post("/api/upload", json={"on": "no"},
                           headers=HEADERS).status_code == 400
        answer = client.post("/api/upload", json={"on": False}, headers=HEADERS)
        assert answer.status_code == 200 and answer.json()["enabled"] is False
        assert client.get("/upload.js").status_code == 200
        page = client.get("/classic").text
        assert 'id="upload-on"' in page and "/upload.js" in page
    assert up.stopped == 1
    plain = aa_server.create_app(tmp_path / "missing.json", replay_pool=tmp_path)
    with TestClient(plain) as client:
        assert client.get("/api/upload").json()["available"] is False
        assert client.post("/api/upload", json={"on": True},
                           headers=HEADERS).status_code == 409


# -- closing the window (aa_live_entry, aa_after_session.after_close) -------------

class Ended(Exception):
    """The window's process ended by the system (its black window closed)."""


def test_a_window_closed_during_a_slow_upload_leaves_no_half_package(tmp_path):
    """The video goes up slowly; the window is closed half way through a
    segment. In the cloud folder: the package and the sheet whole, the
    segment only as ``.part``, no ``upload.json`` (the pull leaves it alone).
    The upload that takes over finishes it, ``upload.json`` last."""
    synced = drive(tmp_path)
    folder = recording(tmp_path / "recordings", "20261016-210927-live")
    (folder / "segment_0000.mp4").write_bytes(b"\1" * (3 * aa_upload.CHUNK))
    (tmp_path / "upload").mkdir()
    (tmp_path / "upload" / "settings.json").write_text(
        json.dumps({"machine": "peng"}), encoding="utf-8")
    there = synced / "peng" / folder.name

    def closed(seconds):
        if (there / "segment_0000.mp4.part").exists():
            raise Ended()
    window = uploader(tmp_path, FakeRclone(tmp_path / "cloud", remotes=()),
                      cloud=tmp_path / "CloudStorage", sleep=closed)
    assert window.upload_once() is False
    assert not (there / aa_upload.MARKER).exists()
    assert not (there / "segment_0000.mp4").exists()
    for rel in ("flywheel/package.json", "flywheel/体检单.txt"):
        assert (there / rel).read_bytes() == (folder / rel).read_bytes()
    assert "Ended" in (tmp_path / "upload" / "upload.log").read_text(encoding="utf-8")

    after = uploader(tmp_path, FakeRclone(tmp_path / "cloud", remotes=()),
                     cloud=tmp_path / "CloudStorage", sleep=lambda seconds: None)
    assert after.upload_once() is True
    marker = json.loads((there / aa_upload.MARKER).read_text(encoding="utf-8"))
    assert marker["files"] == aa_upload.manifest(folder)["files"]
    assert (there / "segment_0000.mp4").read_bytes() == (
        folder / "segment_0000.mp4").read_bytes()
    assert not list(there.rglob("*.part"))


def test_a_recording_goes_up_only_once_its_package_is_made(tmp_path):
    """The window was closed as the recording stopped: its package is still
    being made (``flywheel/building``) when the upload that takes over comes
    to it. It waits, and the cloud gets the package with the rest."""
    folder = recording(tmp_path / "recordings", "20261016-210927-live", sheet=False)
    (folder / "flywheel").mkdir()
    (folder / aa_upload.BUILDING).write_text("")
    waited = []

    def sleep(seconds):
        waited.append(seconds)
        if len(waited) == 3:            # the package process is done
            aa_upload.write_json(folder / "flywheel" / "package.json", {"ok": 1})
            (folder / aa_upload.BUILDING).unlink()
    rclone = FakeRclone(tmp_path / "cloud")
    up = uploader(tmp_path, rclone, sleep=sleep)
    assert up.upload_once() is True
    assert len(waited) == 3
    there = tmp_path / "cloud" / "PokerSense 同事数据" / "du" / folder.name
    assert json.loads((there / "flywheel" / "package.json").read_text()) == {"ok": 1}
    marker = json.loads((there / aa_upload.MARKER).read_text(encoding="utf-8"))
    assert marker["files"] == aa_upload.manifest(folder)["files"]
    assert "flywheel/package.json" in [rel for rel, _ in marker["files"]]
    assert "flywheel/building" not in [rel for rel, _ in marker["files"]]


def test_one_upload_at_a_time_on_a_computer(tmp_path):
    """The upload after a closed window and a window opened again soon after
    never send at once (two copies into one folder)."""
    recording(tmp_path / "recordings", "20261016-210927-live")
    rclone = FakeRclone(tmp_path / "cloud")
    first, second = uploader(tmp_path, rclone), uploader(tmp_path, rclone)
    assert first.lock_file.acquire()
    try:
        assert second.upload_once() is False
        assert rclone.copies() == []
        clock = [0.0]
        waited = aa_upload.FileLock(tmp_path / "upload" / aa_upload.LOCK)

        def sleep(seconds):
            clock[0] += seconds
        assert waited.acquire(5, sleep=sleep, clock=lambda: clock[0]) is False
        assert clock[0] >= 5
    finally:
        first.lock_file.release()
    assert second.upload_once() is True
    assert len(rclone.copies()) == 4


def test_the_upload_lock_goes_with_a_process_that_was_ended(tmp_path):
    lock = tmp_path / "upload" / aa_upload.LOCK
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sys, time\n"
         "from poker_engine.desktop.aa_upload import FileLock\n"
         f"held = FileLock({str(lock)!r})\n"
         "assert held.acquire()\n"
         "print('held', flush=True)\n"
         "time.sleep(60)\n"],
        stdout=subprocess.PIPE, text=True,
        env=dict(os.environ, PYTHONPATH=os.pathsep.join(
            [str(ROOT / "src"), str(ROOT)])))
    try:
        assert holder.stdout.readline().strip() == "held"
        assert aa_upload.FileLock(lock).acquire() is False
    finally:
        holder.kill()
        holder.wait(10)
        holder.stdout.close()
    mine = aa_upload.FileLock(lock)
    assert mine.acquire(5) is True
    mine.release()


def test_a_failed_pass_never_ends_the_upload_thread(tmp_path):
    """Anything going wrong in a pass (here a TypeError) is logged and tried
    again; the thread goes on."""
    folder = recording(tmp_path / "recordings", "20261016-210927-live")
    rclone = FakeRclone(tmp_path / "cloud")
    up = uploader(tmp_path, rclone, delay=0, retry_waits=(0.05,))
    real, calls = up.upload_all, []

    def upload_all():
        calls.append(1)
        if len(calls) == 1:
            raise TypeError("unsupported operand type(s) for /: 'NoneType' and 'str'")
        return real()
    up.upload_all = upload_all
    up.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and folder.name not in up._state():
            time.sleep(0.02)
        assert up.thread.is_alive()
    finally:
        up.stop()
    assert folder.name in up._state()
    log = (tmp_path / "upload" / "upload.log").read_text(encoding="utf-8")
    assert "TypeError" in log


def test_a_status_poll_during_an_upload_does_not_kill_the_upload_thread(tmp_path):
    """The window asks for the upload status while a recording is copied into
    the synced folder (the owner's Mac, rclone there without its remote): the
    check made for the answer never reaches the copy half done (nightly code
    check 2026-10-17)."""
    synced = drive(tmp_path)
    folder = recording(tmp_path / "recordings", "20261016-200000-live")
    (folder / "segment_0000.mp4").write_bytes(b"\0" * 200_000)
    (tmp_path / "upload").mkdir()
    (tmp_path / "upload" / "settings.json").write_text(
        json.dumps({"machine": "peng"}), encoding="utf-8")
    entered, release = threading.Event(), threading.Event()
    now = [0.0]

    def run(args, timeout):
        if threading.current_thread().name == "window-poll":
            entered.set()
            release.wait(10)
        return 0, "gdrive:\n"
    poller = []

    def sleep(seconds):
        if not poller:
            now[0] += 61
            thread = threading.Thread(target=up.status, name="window-poll")
            poller.append(thread)
            thread.start()
            entered.wait(10)
    up = aa_upload.Uploader(tmp_path / "recordings", base=tmp_path / "upload",
                            run=run, which=lambda name: "/opt/homebrew/bin/rclone",
                            places=[], delay=0, cloud=tmp_path / "CloudStorage",
                            sleep=sleep, clock=lambda: now[0])
    up.start()
    marker = synced / "peng" / folder.name / aa_upload.MARKER
    try:
        deadline = time.monotonic() + 10
        while (time.monotonic() < deadline and not marker.exists()
               and up.thread.is_alive()):
            time.sleep(0.05)
        alive = up.thread.is_alive()
    finally:
        release.set()
        up.stop()
        for thread in poller:
            thread.join(5)
    assert marker.exists(), "the recording never got its upload.json"
    assert alive, "the upload thread died"


def test_a_closing_window_ends_the_rclone_it_started():
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    answer = []
    thread = threading.Thread(target=lambda: answer.append(
        aa_upload.run_process(sleeper, 60)))
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not aa_upload._RUNNING:
        time.sleep(0.02)
    aa_upload.end_processes()
    thread.join(10)
    assert not thread.is_alive()
    assert answer and answer[0][0] != 0
    assert not aa_upload._RUNNING
    assert aa_upload.run_process([sys.executable, "-c", "print('ok')"], 30) == (
        0, "ok\n")


def test_the_upload_after_a_close_is_one_pass_waiting_for_the_lock(
        tmp_path, monkeypatch):
    made = []

    class One:
        def __init__(self, root, base=None, delay=None):
            made.append((root, base, delay))

        def upload_once(self, wait=0.0):
            made.append(wait)
            return True
    monkeypatch.setattr(aa_upload, "Uploader", One)
    assert aa_upload.main(["--root", str(tmp_path / "r"),
                           "--base", str(tmp_path / "u")]) == 0
    assert made == [(tmp_path / "r", tmp_path / "u", 0), aa_upload.LOCK_WAIT]
