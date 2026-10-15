"""Pulling recordings other computers uploaded, and the ledger by machine."""

import json
import os
from pathlib import Path
import shutil

import pytest

from poker_engine.desktop import aa_upload
from tools import flywheel_session as fly
from tools import flywheel_sync as sync

from tests.desktop.test_aa_upload import FakeRclone, recording, uploader

SUMMARY = {"label": "20261014-201500-live", "code": {"commit": "0a56c66"},
           "stakes": ["2/4/8"], "decisions": 3, "advised": 3, "fully_advised": 3,
           "followed": 2, "stalls_over_2s": 0}
HANDS = [{"bb": -10.0, "bomb_pot": False, "spot": "x"},
         {"bb": 4.0, "bomb_pot": False, "spot": "x"}]


def uploaded(tmp_path, name="20261014-201500-live", *, sheet=True):
    """A tester's recording, uploaded through the stand-in rclone."""
    folder = recording(tmp_path / "recordings", name)
    if sheet:
        (folder / "flywheel" / "summary.json").write_text(
            json.dumps({**SUMMARY, "label": name}), encoding="utf-8")
        (folder / "flywheel" / "hands.json").write_text(json.dumps(HANDS),
                                                        encoding="utf-8")
    assert uploader(tmp_path, FakeRclone(tmp_path / "cloud")).upload_all()
    return folder


def test_pull_brings_a_recording_back_whole_and_books_it_by_machine(tmp_path):
    folder = uploaded(tmp_path)
    cloud = sync.LocalSource(tmp_path / "cloud" / "PokerSense 同事数据")
    mac, ledger = tmp_path / "mac", tmp_path / "ledger.jsonl"
    said = []
    assert sync.pull(cloud, mac, ledger, out=said.append)["pulled"] == 1
    here = mac / f"du-{folder.name}"
    for name in ("segment_0000.mp4", "frames.jsonl", "recording.json",
                 "flywheel/hands.json"):
        assert (here / name).read_bytes() == (folder / name).read_bytes()
    pulled = json.loads((here / "pulled.json").read_text(encoding="utf-8"))
    assert pulled["machine"] == "du" and pulled["folder"] == folder.name
    assert fly.origin(here) == ("du", folder.name)
    line, = fly.read_ledger(ledger)
    assert line["label"] == here.name and line["machine"] == "du"
    assert line["normal"] == {"hands": 2, "bb": -6.0, "bb_squared": 116.0}
    found = fly.totals(fly.read_ledger(ledger))
    assert found["by_machine"]["du"]["all"]["hands"] == 2
    # Pulled again: nothing copied, nothing booked twice.
    assert sync.pull(cloud, mac, ledger, out=said.append) == {"same": 1}
    assert len(fly.read_ledger(ledger)) == 1
    # The pulled folder is never uploaded again from this computer.
    assert not aa_upload.finished(here)


def test_a_recording_still_on_its_way_is_left_for_the_next_pull(tmp_path):
    folder = uploaded(tmp_path)
    there = tmp_path / "cloud" / "PokerSense 同事数据" / "du" / folder.name
    cloud = sync.LocalSource(tmp_path / "cloud" / "PokerSense 同事数据")
    marker = there / "upload.json"
    text = marker.read_text(encoding="utf-8")
    marker.unlink()
    said = []
    assert sync.pull(cloud, tmp_path / "mac", None, out=said.append) == {"waiting": 1}
    assert "还没传完" in said[0]
    data = json.loads(text)
    data["files"] = [[rel, size + 1 if rel == "frames.jsonl" else size]
                     for rel, size in data["files"]]
    marker.write_text(json.dumps(data), encoding="utf-8")
    assert sync.pull(cloud, tmp_path / "mac", None, out=said.append) == {"failed": 1}
    assert not (tmp_path / "mac" / f"du-{folder.name}" / "pulled.json").exists()
    data["files"] = [["../../outside.txt", 1]]
    marker.write_text(json.dumps(data), encoding="utf-8")
    assert sync.pull(cloud, tmp_path / "mac", None, out=said.append) == {"bad": 1}
    assert not (tmp_path / "outside.txt").exists()


def test_a_recording_without_its_sheet_gets_one_here(tmp_path, monkeypatch):
    uploaded(tmp_path, sheet=False)
    made = []

    def report(folder, ledger):
        made.append((Path(folder).name, ledger))
        return []

    monkeypatch.setattr(fly, "report", report)
    cloud = sync.LocalSource(tmp_path / "cloud" / "PokerSense 同事数据")
    said = []
    sync.pull(cloud, tmp_path / "mac", tmp_path / "l.jsonl", out=said.append)
    assert made == [("du-20261014-201500-live", tmp_path / "l.jsonl")]
    assert "体检单在这里做好" in said[0]


def test_pull_through_rclone_reads_lists_and_copies(tmp_path):
    folder = uploaded(tmp_path)
    rclone = FakeRclone(tmp_path / "cloud")
    base = rclone.where("pokersense-upload:PokerSense 同事数据")

    def run(args, timeout):
        command, path = args[1], args[-1] if args[1] == "lsf" else args[2]
        if command == "lsf":
            where = rclone.where(path)
            return 0, "".join(f"{p.name}/\n" for p in sorted(where.iterdir())
                              if p.is_dir())
        if command == "cat":
            where = rclone.where(path)
            return (0, where.read_text(encoding="utf-8")) if where.exists() else (
                3, "not found")
        if command == "copy":
            assert args[args.index("--exclude") + 1] == "/upload.json"
            shutil.copytree(rclone.where(path), args[3], dirs_exist_ok=True)
            (Path(args[3]) / "upload.json").unlink()
            return 0, ""
        raise AssertionError(args)

    assert base.is_dir()
    source = sync.RcloneSource("pokersense-upload:PokerSense 同事数据", "rclone", run)
    counts = sync.pull(source, tmp_path / "mac", None, out=lambda text: None)
    assert counts == {"pulled": 1}
    assert (tmp_path / "mac" / f"du-{folder.name}" / "segment_0000.mp4").exists()


def test_the_source_is_the_drive_folder_when_this_mac_has_one(tmp_path):
    settings = aa_upload.load_settings(tmp_path / "none.json")
    cloud = tmp_path / "CloudStorage"
    assert sync.choose_source(None, settings, which=lambda n: None, cloud=cloud) is None
    rclone = sync.choose_source(None, settings, which=lambda n: "/bin/rclone",
                                cloud=cloud)
    assert str(rclone) == "pokersense-upload:PokerSense 同事数据"
    drive = cloud / "GoogleDrive-x@example.com" / "我的云端硬盘" / "PokerSense 同事数据"
    drive.mkdir(parents=True)
    found = sync.choose_source(None, settings, which=lambda n: None, cloud=cloud)
    assert isinstance(found, sync.LocalSource) and found.path == drive
    given = sync.choose_source(str(tmp_path), settings, cloud=cloud)
    assert isinstance(given, sync.LocalSource)
    remote = sync.choose_source("other:folder", settings, which=lambda n: "rclone",
                                cloud=cloud)
    assert isinstance(remote, sync.RcloneSource) and str(remote) == "other:folder"


def test_rank_counts_pulled_recordings_by_their_own_date(tmp_path):
    for name, machine in (("20261012-1-live", None), ("du-20261014-1-live", "du"),
                          ("du-20261011-1-live", "du")):
        sheet = tmp_path / name / "flywheel"
        sheet.mkdir(parents=True)
        (sheet / "hands.json").write_text("[]", encoding="utf-8")
        if machine:
            (tmp_path / name / "pulled.json").write_text(json.dumps(
                {"machine": machine, "folder": name[len(machine) + 1:]}),
                encoding="utf-8")
    sessions, _, machines = fly.collect(tmp_path, since="20261012")
    assert sessions == ["20261012-1-live", "du-20261014-1-live"]
    assert dict(machines) == {"本机": 1, "du": 1}


def test_setup_keeps_the_full_path_of_rclone(tmp_path, monkeypatch):
    """So a window started before rclone was on the PATH still finds it."""
    found = tmp_path / "rclone-dir" / "rclone"
    found.parent.mkdir()
    found.write_bytes(b"")
    monkeypatch.setattr(sync, "private_root", lambda: tmp_path / "private")
    monkeypatch.setattr(sync.shutil, "which", lambda name: str(found))
    sync.main(["setup", "--machine", "du", "--root", str(tmp_path / "rec")])
    settings = json.loads((tmp_path / "private" / "upload" / "settings.json")
                          .read_text(encoding="utf-8"))
    assert settings == {"machine": "du", "rclone": str(found)}
    monkeypatch.setattr(sync.shutil, "which", lambda name: "/elsewhere/rclone")
    sync.main(["setup", "--root", str(tmp_path / "rec")])      # kept as it was
    assert json.loads((tmp_path / "private" / "upload" / "settings.json")
                      .read_text(encoding="utf-8"))["rclone"] == str(found)


@pytest.mark.skipif(os.name == "nt", reason="links need extra rights on Windows")
def test_setup_keeps_the_link_not_the_versioned_folder(tmp_path, monkeypatch):
    """Homebrew and winget put a link on the PATH to a folder named for the
    version; an upgrade removes that folder and keeps the link."""
    real = tmp_path / "Cellar" / "1.75.2" / "rclone"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"")
    link = tmp_path / "bin" / "rclone"
    link.parent.mkdir()
    link.symlink_to(real)
    monkeypatch.setattr(sync, "private_root", lambda: tmp_path / "private")
    monkeypatch.setattr(sync.shutil, "which", lambda name: str(link))
    sync.main(["setup", "--root", str(tmp_path / "rec")])
    assert json.loads((tmp_path / "private" / "upload" / "settings.json")
                      .read_text(encoding="utf-8"))["rclone"] == str(link)


def test_the_pull_passes_over_a_saved_rclone_that_is_gone(tmp_path):
    settings = {**aa_upload.load_settings(tmp_path / "none.json"),
                "rclone": str(tmp_path / "Cellar" / "1.75.2" / "rclone")}
    source = sync.choose_source(None, settings, which=lambda n: "/bin/rclone",
                                cloud=tmp_path / "CloudStorage")
    assert source.rclone == "/bin/rclone"
