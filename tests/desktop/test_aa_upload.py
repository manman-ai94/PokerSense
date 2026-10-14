"""Recordings uploaded with rclone, with a stand-in for rclone and the cloud."""

import json
from pathlib import Path
import shutil
import threading
import time

from fastapi.testclient import TestClient

from poker_engine.desktop import aa_after_session, aa_server, aa_upload

HEADERS = {"X-AA-Live": "1"}


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
            shutil.copytree(args[2], self.where(args[3]), dirs_exist_ok=True)
            return 0, ""
        if command == "copyto":
            target = self.where(args[3])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(args[2], target)
            return 0, ""
        raise AssertionError(args)

    def copies(self):
        return [args for args in self.calls if args[1] in ("copy", "copyto")]


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
    return folder


def uploader(tmp_path, rclone, **options):
    base = tmp_path / "upload"
    base.mkdir(exist_ok=True)
    settings = base / "settings.json"
    if not settings.exists():
        settings.write_text(json.dumps({"machine": "du"}), encoding="utf-8")
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
                  if p.is_file()) == ["flywheel/体检单.txt", "frames.jsonl",
                                      "recording.json", "segment_0000.mp4",
                                      "segments.csv", "upload.json"]
    marker = json.loads((there / "upload.json").read_text(encoding="utf-8"))
    assert marker["machine"] == "du" and marker["folder"] == folder.name
    assert marker["files"] == aa_upload.manifest(folder)["files"]
    copy, last = rclone.copies()
    assert copy[3] == f"pokersense-upload:PokerSense 同事数据/du/{folder.name}"
    assert "--checksum" in copy and copy[copy.index("--bwlimit") + 1] == "1M"
    assert last[1] == "copyto" and last[3].endswith("/upload.json")
    state = json.loads((tmp_path / "upload" / "state.json").read_text("utf-8"))
    assert list(state) == [folder.name]       # the one still recording waits
    status = up.status()
    assert status["configured"] and status["uploaded"] == 1
    assert status["message"].startswith("录像自动上传：开")
    up.upload_all()                           # nothing new: nothing sent
    assert len(rclone.copies()) == 2


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
        str(done), str(cut)]
    assert again.pending() == []


def test_without_rclone_or_its_remote_the_window_only_says_so(tmp_path):
    recording(tmp_path / "recordings", "20261014-201500-live")
    rclone = FakeRclone(tmp_path / "cloud", remotes=("pokersense",))
    up = uploader(tmp_path, rclone)
    assert up.upload_all() is True and rclone.copies() == []
    status = up.status()
    assert status["configured"] is False and status["message"].startswith("未配置上传")
    none = aa_upload.Uploader(tmp_path / "recordings", base=tmp_path / "upload",
                              run=rclone, which=lambda name: None)
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
    assert len(rclone.copies()) == 2


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
    assert order == [("sheet", aa_upload.REPORT_WAIT), ("copy", str(folder))]


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
