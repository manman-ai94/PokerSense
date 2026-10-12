"""In-app update: manifest, versions, share links, verified download, install."""

import hashlib
import http.server
import io
import json
import threading
import zipfile
from functools import partial

import pytest

from poker_engine.desktop import app_update
from poker_engine.desktop.app_update import UpdateError


INSTALLER = b"MZ" + bytes(range(256)) * 40


def manifest(version="0.3.0", data=INSTALLER, url="https://example.invalid/setup.exe",
             **changes):
    installer = {"url": url, "sha256": hashlib.sha256(data).hexdigest(),
                 "bytes": len(data)}
    installer.update(changes)
    return {"schema": "pokersense-update-v1", "product": "PokerSense-AA",
            "version": version, "notes": "n", "installer": installer}


class Files:
    """An opener serving fixed bytes per address, like a cloud folder."""

    def __init__(self, files, content_type=""):
        self.files, self.content_type, self.opened = files, content_type, []

    def __call__(self, url):
        self.opened.append(url)
        if url not in self.files:
            raise UpdateError("missing " + url)
        data = self.files[url]
        return app_update._Response(io.BytesIO(data), self.content_type, len(data))


def folder_with(latest, data=INSTALLER):
    return Files({"https://cloud/latest.json": json.dumps(latest).encode(),
                  latest["installer"]["url"]: data})


def test_versions_sort_with_dev_builds_before_their_release():
    order = ["0.2.0.dev1", "0.2.0.dev2", "0.2.0", "0.2.1", "0.10.0", "1.0.0"]
    assert sorted(order, key=app_update.parse_version) == order
    assert app_update.is_newer("0.3.0", "0.2.0.dev1")
    assert not app_update.is_newer("0.2.0.dev1", "0.2.0.dev1")
    for bad in ("v0.3.0", "0.3", "0.3.0-beta", "", None, "0.3.0.dev"):
        with pytest.raises(UpdateError):
            app_update.parse_version(bad)


def test_share_links_become_direct_downloads():
    direct = ("https://drive.usercontent.google.com/download?id=AbC_1-x"
              "&export=download&confirm=t")
    assert app_update.direct_url(
        "https://drive.google.com/file/d/AbC_1-x/view?usp=sharing") == direct
    assert app_update.direct_url("https://drive.google.com/open?id=AbC_1-x") == direct
    assert app_update.direct_url(
        "https://drive.google.com/uc?id=AbC_1-x&export=download") == direct
    assert app_update.direct_url(
        "https://www.dropbox.com/scl/fi/abc/latest.json?rlkey=k&dl=0") == (
        "https://www.dropbox.com/scl/fi/abc/latest.json?rlkey=k&dl=1")
    plain = "https://files.example.com/pokersense/latest.json"
    assert app_update.direct_url(plain) == plain


def test_check_reports_available_up_to_date_unconfigured_and_errors():
    files = folder_with(manifest("0.3.0"))
    result = app_update.check("https://cloud/latest.json", "0.2.0.dev1", files)
    assert (result["status"], result["latest"]) == ("AVAILABLE", "0.3.0")
    result = app_update.check("https://cloud/latest.json", "0.3.0", files)
    assert result["status"] == "UP_TO_DATE"
    assert app_update.check(None, "0.3.0")["status"] == "UNCONFIGURED"
    broken = Files({"https://cloud/latest.json": b"<html>sign in</html>"})
    result = app_update.check("https://cloud/latest.json", "0.3.0", broken)
    assert result["status"] == "ERROR" and "JSON" in result["error"]
    page = Files({"https://cloud/latest.json": b"{}"}, content_type="text/html")
    result = app_update.check("https://cloud/latest.json", "0.3.0", page)
    assert result["status"] == "ERROR" and "网页" in result["error"]


@pytest.mark.parametrize("change", [
    {"schema": "other"}, {"product": "Other"}, {"version": "latest"},
])
def test_a_manifest_for_something_else_is_refused(change):
    with pytest.raises(UpdateError):
        app_update.validate_manifest({**manifest(), **change})


@pytest.mark.parametrize("change", [
    {"sha256": "abc"}, {"sha256": "A" * 64}, {"bytes": 0}, {"bytes": "12"},
    {"bytes": app_update.MAX_INSTALLER_BYTES + 1}, {"url": ""},
])
def test_a_manifest_without_a_usable_installer_is_refused(change):
    with pytest.raises(UpdateError):
        app_update.validate_manifest(manifest(**change))


def test_download_keeps_only_a_file_whose_size_and_hash_match(tmp_path):
    latest = manifest()
    (tmp_path / "PokerSense-AA-Setup-0.2.9.exe").write_bytes(b"old")
    seen = []
    path = app_update.download(latest, tmp_path, folder_with(latest),
                               lambda got, total: seen.append((got, total)))
    assert path.name == "PokerSense-AA-Setup-0.3.0.exe"
    assert path.read_bytes() == INSTALLER
    assert seen[-1] == (len(INSTALLER), len(INSTALLER))
    assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]


@pytest.mark.parametrize("served, message", [
    (INSTALLER[:-1] + b"X", "sha256"),        # same size, other bytes
    (INSTALLER[:-10], "不完整"),
    (INSTALLER + b"extra", "大"),
])
def test_a_wrong_download_is_deleted_and_not_returned(tmp_path, served, message):
    latest = manifest()
    with pytest.raises(UpdateError, match=message):
        app_update.download(latest, tmp_path, folder_with(latest, served))
    assert list(tmp_path.iterdir()) == []


def test_a_web_page_instead_of_the_installer_is_refused(tmp_path):
    latest = manifest()
    files = folder_with(latest)
    files.content_type = "text/html; charset=utf-8"
    with pytest.raises(UpdateError, match="网页"):
        app_update.download(latest, tmp_path, files)
    assert list(tmp_path.iterdir()) == []


def test_local_and_http_addresses_download_through_the_real_opener(tmp_path):
    cloud = tmp_path / "cloud"
    cloud.mkdir()
    (cloud / "setup.exe").write_bytes(INSTALLER)
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(cloud))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}/"
        latest = manifest(url=base + "setup.exe")
        (cloud / "latest.json").write_text(json.dumps(latest), "utf-8")
        result = app_update.check(base + "latest.json", "0.2.0")
        assert result["status"] == "AVAILABLE"
        assert app_update.download(result["manifest"], tmp_path / "a").read_bytes() == (
            INSTALLER)
        local = manifest(url=str(cloud / "setup.exe"))
        (cloud / "local.json").write_text(json.dumps(local), "utf-8")
        result = app_update.check(str(cloud / "local.json"), "0.2.0")
        assert result["status"] == "AVAILABLE"
        assert app_update.download(result["manifest"], tmp_path / "b").read_bytes() == (
            INSTALLER)
        assert app_update.check(base + "missing.json", "0.2.0")["status"] == "ERROR"
    finally:
        server.shutdown()


def test_the_installer_runs_silently_waits_for_the_program_and_reopens_it():
    assert app_update.installer_command("C:/u/setup.exe", 4242) == [
        "C:/u/setup.exe", "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
        "/WAITPID=4242", "/RELAUNCH=1"]
    started = []
    app_update.start_installer("setup.exe", pid=7, relaunch=False,
                               popen=lambda command, **kw: started.append(command))
    assert started == [["setup.exe", "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                        "/WAITPID=7", "/RELAUNCH=0"]]


def test_the_address_comes_from_the_flag_the_environment_or_the_install(tmp_path):
    assert app_update.configured_url("https://flag", {}, tmp_path) == "https://flag"
    env = {app_update.URL_ENV: " https://env "}
    assert app_update.configured_url(None, env, tmp_path) == "https://env"
    assert app_update.configured_url(None, {}, tmp_path) is None
    (tmp_path / "update-config.json").write_text(
        json.dumps({"manifest_url": "https://drive.google.com/open?id=x"}), "utf-8")
    assert app_update.configured_url(None, {}, tmp_path) == (
        "https://drive.google.com/open?id=x")
    (tmp_path / "update-config.json").write_text("not json", "utf-8")
    assert app_update.configured_url(None, {}, tmp_path) is None


def test_running_from_source_never_installs(monkeypatch):
    monkeypatch.delattr(app_update.sys, "frozen", raising=False)
    assert app_update.install_root() is None
    assert app_update.can_install() is False


def updater(tmp_path, latest, **kw):
    started, exits = [], []
    result = app_update.Updater(
        "https://cloud/latest.json", "0.2.0", tmp_path / "updates",
        opener=folder_with(latest, kw.pop("data", INSTALLER)),
        starter=started.append, allowed=kw.pop("allowed", lambda: True),
        exit_soon=lambda: exits.append(True), clock=lambda: 100.0)
    return result, started, exits


def test_the_window_installs_a_verified_update_and_then_exits(tmp_path):
    latest = manifest("0.3.0")
    tool, started, exits = updater(tmp_path, latest)
    assert tool.snapshot()["status"] == "NOT_CHECKED"
    state = tool.refresh()
    assert (state["status"], state["latest"], state["can_install"]) == (
        "AVAILABLE", "0.3.0", True)
    assert "manifest" not in state and state["checked_at"] == 100.0
    state = tool.install()
    assert state["status"] == "INSTALLING" and state["installing"] is True
    assert [path.read_bytes() for path in started] == [INSTALLER]
    assert exits == [True]


def test_a_failed_download_leaves_the_program_running(tmp_path):
    latest = manifest("0.3.0")
    tool, started, exits = updater(tmp_path, latest, data=b"tampered")
    state = tool.install()
    assert state["status"] == "ERROR" and state["installing"] is False
    assert started == [] and exits == []


def test_nothing_is_installed_when_up_to_date_or_not_allowed(tmp_path):
    tool, started, exits = updater(tmp_path, manifest("0.2.0"))
    assert tool.install()["status"] == "UP_TO_DATE"
    tool, started, exits = updater(tmp_path, manifest("0.3.0"), allowed=lambda: False)
    with pytest.raises(UpdateError):
        tool.install()
    assert started == [] and exits == []
    unconfigured = app_update.Updater(None, "0.2.0", tmp_path)
    assert unconfigured.snapshot()["status"] == "UNCONFIGURED"
    assert unconfigured.check_in_background() is None


def test_the_console_update_says_what_happened(tmp_path):
    lines, started = [], []
    latest = manifest("0.3.0")
    code = app_update.run_console_update(
        "https://cloud/latest.json", "0.2.0", tmp_path, opener=folder_with(latest),
        starter=started.append, allowed=lambda: True, out=lines.append)
    assert code == (0, True) and len(started) == 1
    assert any("校验通过" in line for line in lines)
    lines.clear()
    code = app_update.run_console_update(
        "https://cloud/latest.json", "0.3.0", tmp_path, opener=folder_with(latest),
        starter=started.append, allowed=lambda: True, out=lines.append)
    assert code == (0, False) and "最新" in lines[-1]
    code = app_update.run_console_update(
        "https://cloud/latest.json", "0.2.0", tmp_path,
        opener=folder_with(latest, b"bad"), starter=started.append,
        allowed=lambda: True, out=lines.append)
    assert code == (4, False) and len(started) == 1
    assert app_update.run_console_update(None, "0.2.0", tmp_path,
                                         out=lines.append) == (3, False)


def bundle_zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as handle:
        for name, data in files.items():
            handle.writestr(name, data)
    return buffer.getvalue()


BUNDLE = bundle_zip({"profile.json": b"{}", "bundle-manifest.json": b"{}",
                     "assets/heads_path.npz": b"model"})


def with_recognition(data=BUNDLE, digest="d" * 64, **changes):
    latest = manifest("0.3.0")
    latest["recognition"] = {"url": "https://cloud/recognition.zip",
                             "sha256": hashlib.sha256(data).hexdigest(),
                             "bytes": len(data), "manifest_sha256": digest,
                             **changes}
    return latest


def cloud(latest, data=BUNDLE):
    files = folder_with(latest)
    files.files["https://cloud/recognition.zip"] = data
    return files


class Validator:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def __call__(self, profile, digest):
        self.calls.append((profile.parent.name, digest))
        assert profile.is_file()
        if self.error:
            raise ValueError(self.error)
        return {"files": 3}


@pytest.mark.parametrize("change", [
    {"sha256": "x"}, {"manifest_sha256": "A" * 64}, {"bytes": 0}, {"url": ""},
])
def test_a_manifest_with_an_unusable_recognition_entry_is_refused(change):
    with pytest.raises(UpdateError, match="识别资源包"):
        app_update.validate_manifest(with_recognition(**change))


def test_the_recognition_bundle_is_fetched_validated_and_made_current(tmp_path):
    latest, check = with_recognition(), Validator()
    assert app_update.installed_recognition(tmp_path) is None
    result = app_update.sync_recognition("https://cloud/latest.json", tmp_path,
                                         opener=cloud(latest), validate=check)
    assert result == {"status": "INSTALLED", "manifest_sha256": "d" * 64}
    assert check.calls == [("d" * 64 + ".new", "d" * 64)]   # before made current
    profile, digest = app_update.installed_recognition(tmp_path)
    assert digest == "d" * 64 and profile == tmp_path / "recognition" / digest / (
        "profile.json")
    assert (profile.parent / "assets" / "heads_path.npz").read_bytes() == b"model"
    assert sorted(p.name for p in (tmp_path / "recognition").iterdir()) == [
        "current.json", "d" * 64]
    again = app_update.sync_recognition("https://cloud/latest.json", tmp_path,
                                        opener=cloud(latest), validate=check)
    assert again["status"] == "UP_TO_DATE" and len(check.calls) == 1


def test_a_new_bundle_replaces_the_old_one(tmp_path):
    app_update.sync_recognition("https://cloud/latest.json", tmp_path,
                                opener=cloud(with_recognition()), validate=Validator())
    newer = bundle_zip({"profile.json": b"{}", "v": b"2"})
    result = app_update.sync_recognition(
        "https://cloud/latest.json", tmp_path,
        opener=cloud(with_recognition(newer, "e" * 64), newer), validate=Validator())
    assert result["status"] == "INSTALLED"
    assert app_update.installed_recognition(tmp_path)[1] == "e" * 64
    assert sorted(p.name for p in (tmp_path / "recognition").iterdir()) == [
        "current.json", "e" * 64]


@pytest.mark.parametrize("served, validator, message", [
    (BUNDLE[:-1] + b"X", Validator(), "sha256"),
    (BUNDLE, Validator("bundle_file_hash_mismatch:profile.json"), "校验没通过"),
])
def test_a_wrong_bundle_is_not_made_current_and_the_old_one_stays(
        tmp_path, served, validator, message):
    app_update.sync_recognition("https://cloud/latest.json", tmp_path,
                                opener=cloud(with_recognition()), validate=Validator())
    other = with_recognition(digest="e" * 64)
    result = app_update.sync_recognition("https://cloud/latest.json", tmp_path,
                                         opener=cloud(other, served),
                                         validate=validator)
    assert result["status"] == "ERROR" and message in result["error"]
    assert app_update.installed_recognition(tmp_path)[1] == "d" * 64
    assert sorted(p.name for p in (tmp_path / "recognition").iterdir()) == [
        "current.json", "d" * 64]


@pytest.mark.parametrize("name", ["../outside.txt", "/abs.txt", "C:/x.txt",
                                  "a\\b.txt"])
def test_a_bundle_with_unsafe_paths_is_refused(tmp_path, name):
    evil = bundle_zip({"profile.json": b"{}", name: b"x"})
    result = app_update.sync_recognition(
        "https://cloud/latest.json", tmp_path / "state",
        opener=cloud(with_recognition(evil), evil), validate=Validator())
    assert result["status"] == "ERROR" and "不安全" in result["error"]
    assert not (tmp_path / "outside.txt").exists()
    assert app_update.installed_recognition(tmp_path / "state") is None


def test_no_recognition_without_an_address_an_entry_or_a_reachable_manifest(tmp_path):
    assert app_update.sync_recognition(None, tmp_path)["status"] == "UNCONFIGURED"
    result = app_update.sync_recognition("https://cloud/latest.json", tmp_path,
                                         opener=folder_with(manifest()))
    assert result["status"] == "NOT_PUBLISHED"
    result = app_update.sync_recognition("https://cloud/missing.json", tmp_path,
                                         opener=folder_with(manifest()))
    assert result["status"] == "ERROR"
    assert app_update.installed_recognition(tmp_path) is None
    (tmp_path / "recognition").mkdir()
    (tmp_path / "recognition" / "current.json").write_text('{"manifest_sha256": "x"}')
    assert app_update.installed_recognition(tmp_path) is None
