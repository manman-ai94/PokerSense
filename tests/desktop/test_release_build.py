"""Release build steps, recognition packing and the installer/workflow contract."""

import importlib.util
import json
from pathlib import Path
import shutil
import zipfile

import pytest

from poker_engine.desktop import app_update
from poker_engine.desktop.aa_bundle import export_bundle
from tests.desktop import test_aa_bundle


ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load("release_build", "packaging/release_build.py")
packer = load("pack_aa_recognition", "tools/pack_aa_recognition.py")


def test_windows_file_versions_have_four_numbers():
    assert release.windows_version("0.3.0") == "0.3.0.0"
    assert release.windows_version("0.2.0.dev1") == "0.2.0.1"
    assert release.windows_version("1.12.7") == "1.12.7.0"


def test_stamp_writes_one_version_everywhere(tmp_path):
    for name in ("src/poker_engine/__init__.py", "pyproject.toml",
                 "packaging/windows-version.txt"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, tmp_path / name)
    assert release.stamp("0.3.1", tmp_path) == {"version": "0.3.1",
                                                "windows_version": "0.3.1.0"}
    assert '__version__ = "0.3.1"' in (
        tmp_path / "src/poker_engine/__init__.py").read_text("utf-8")
    assert '\nversion = "0.3.1"\n' in (tmp_path / "pyproject.toml").read_text("utf-8")
    windows = (tmp_path / "packaging/windows-version.txt").read_text("utf-8")
    assert "filevers=(0, 3, 1, 0)" in windows and "prodvers=(0, 3, 1, 0)" in windows
    assert "'ProductVersion', '0.3.1'" in windows
    assert "'FileVersion', '0.3.1'" in windows
    with pytest.raises(app_update.UpdateError):
        release.stamp("v0.3.1", tmp_path)


def test_the_manifest_matches_the_installer_and_passes_the_programs_check(tmp_path):
    installer = tmp_path / "PokerSense-AA-Setup.exe"
    installer.write_bytes(b"MZ" * 1000)
    manifest = release.build_manifest("0.3.0", installer, "https://cloud/setup.exe",
                                      commit="abc")
    assert manifest["installer"]["bytes"] == 2000
    assert manifest["installer"]["sha256"] == release.sha256_file(installer)
    assert app_update.validate_manifest(json.loads(json.dumps(manifest)))
    release.write_config("https://drive.google.com/open?id=x",
                         tmp_path / "update-config.json")
    assert app_update.configured_url(None, {}, tmp_path) == (
        "https://drive.google.com/open?id=x")


def test_a_release_must_be_newer_than_the_published_one(tmp_path):
    published = tmp_path / "latest.json"
    assert release.check_newer(published, "0.3.0") == (True, None)   # nothing yet
    published.write_text("{}", "utf-8")
    assert release.check_newer(published, "0.3.0") == (True, None)
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"x")
    published.write_text(json.dumps(release.build_manifest(
        "0.3.0", installer, "https://cloud/setup.exe")), "utf-8")
    assert release.check_newer(published, "0.3.1") == (True, "0.3.0")
    assert release.check_newer(published, "0.3.0") == (False, "0.3.0")
    assert release.check_newer(published, "0.2.9") == (False, "0.3.0")
    assert release.main(["newer", "--current", str(published), "--version",
                         "0.3.0"]) == 1


@pytest.fixture
def bundle(tmp_path):
    profile = test_aa_bundle.source.__wrapped__(tmp_path)
    export_bundle(profile, tmp_path / "bundle")
    return tmp_path / "bundle"


def test_an_uploaded_bundle_is_checked_and_listed_in_the_manifest(bundle, tmp_path):
    out = tmp_path / "upload"
    sidecar = packer.pack(bundle, out)
    again = packer.pack(bundle, tmp_path / "again")
    assert again["zip_sha256"] == sidecar["zip_sha256"]          # reproducible
    checked = release.check_recognition(out)
    assert checked["manifest_sha256"] == sidecar["manifest_sha256"]
    assert checked["files"] == sidecar["files"] - 1   # all but the manifest itself
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"MZ")
    manifest = release.build_manifest("0.3.0", installer, "https://cloud/setup.exe",
                                      recognition=out,
                                      recognition_url="https://cloud/rec.zip")
    assert manifest["recognition"] == {
        "url": "https://cloud/rec.zip", "sha256": sidecar["zip_sha256"],
        "bytes": sidecar["zip_bytes"], "manifest_sha256": sidecar["manifest_sha256"],
        "created": sidecar["created"]}
    assert "recognition" not in release.build_manifest(
        "0.3.0", installer, "https://cloud/setup.exe")


def test_the_program_installs_what_the_release_lists(bundle, tmp_path):
    out = tmp_path / "upload"
    packer.pack(bundle, out)
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"MZ")
    manifest = release.build_manifest("0.3.0", installer, str(installer),
                                      recognition=out,
                                      recognition_url=str(out / packer.ZIP_NAME))
    state = tmp_path / "state"
    result = app_update.sync_recognition(None, state, manifest=manifest)
    assert result["status"] == "INSTALLED"           # real aa_bundle validation
    profile, digest = app_update.installed_recognition(state)
    assert digest == manifest["recognition"]["manifest_sha256"]
    assert json.loads(profile.read_text("utf-8"))["bundle_manifest"] == (
        "bundle-manifest.json")


def test_a_changed_or_unsafe_recognition_zip_is_refused(bundle, tmp_path):
    out = tmp_path / "upload"
    packer.pack(bundle, out)
    archive = out / packer.ZIP_NAME
    with zipfile.ZipFile(archive, "a") as handle:
        handle.writestr("extra.txt", "changed")
    with pytest.raises(SystemExit, match="sidecar"):
        release.check_recognition(out)
    evil = tmp_path / "evil"
    evil.mkdir()
    with zipfile.ZipFile(evil / packer.ZIP_NAME, "w") as handle:
        handle.writestr("../outside.txt", "x")
    data = (evil / packer.ZIP_NAME).read_bytes()
    (evil / packer.JSON_NAME).write_text(json.dumps({
        "schema": packer.SCHEMA, "zip_bytes": len(data),
        "zip_sha256": release.hashlib.sha256(data).hexdigest(),
        "manifest_sha256": "0" * 64}), "utf-8")
    with pytest.raises(SystemExit, match="不安全"):
        release.check_recognition(evil)
    assert not (tmp_path / "outside.txt").exists()


def test_the_installer_is_per_user_with_shortcuts_and_a_waiting_silent_update():
    raw = (ROOT / "packaging/pokersense.iss").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")         # Inno reads UTF-8 only with a BOM
    text = raw.decode("utf-8-sig")
    for line in ("PrivilegesRequired=lowest", "DefaultDirName={autopf}\\{#MyAppName}",
                 '#define MyAppExeName "PokerSense-AA.exe"',
                 'Name: "{autodesktop}\\{#MyAppName}"', 'Parameters: "--update-now"',
                 "{param:WAITPID|0}", "{param:RELAUNCH|0}",
                 "Check: RelaunchAfterUpdate",
                 'Type: filesandordirs; Name: "{app}\\_internal"',
                 'Source: "..\\dist\\PokerSense-AA\\*"'):
        assert line in text, line
    assert "{commondesktop}" not in text and "{commonpf}" not in text
    # The in-app updater's arguments are the ones the installer reads.
    command = app_update.installer_command("setup.exe", 1)
    assert "/WAITPID=1" in command and "/RELAUNCH=1" in command


def test_releases_come_only_from_main_and_uploads_need_the_secret():
    workflow = (ROOT / ".github/workflows/windows-release.yml").read_text("utf-8")
    assert "git merge-base --is-ancestor $env:GITHUB_SHA origin/main" in workflow
    assert '$env:REF -ne "refs/heads/main"' in workflow
    assert "secrets.RCLONE_CONFIG" in workflow
    assert "jobs:\n  windows:" in workflow or "  windows:" in workflow
    assert "  release:" in workflow
    assert "github.event_name != 'pull_request'" in workflow
    assert "needs.windows.outputs.upload == 'true'" in workflow
    windows_job = workflow.split("  release:")[0].split("jobs:")[1]
    assert "secrets.RCLONE_CONFIG" not in windows_job
    # The recognition bundle is a separate upload, listed in latest.json.
    assert "recognition-check" in workflow and "--recognition-url" in workflow
    assert "release_build.py recognition --" not in workflow
    assert "dist/PokerSense-AA/recognition" not in workflow
    assert "persist-credentials: false" in workflow
    assert "softprops/action-gh-release" not in workflow
    legacy = (ROOT / ".github/workflows/build-desktop.yml").read_text("utf-8")
    assert "action-gh-release" not in legacy and "tags:" not in legacy


def test_the_printed_manifest_has_no_download_links(tmp_path, capsys):
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"MZ")
    out = tmp_path / "latest.json"
    assert release.main(["manifest", "--version", "0.3.0",
                         "--installer", str(installer),
                         "--url", "https://cloud/secret-link", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "secret-link" not in printed and '"sha256"' in printed
    assert json.loads(out.read_text("utf-8"))["installer"]["url"] == (
        "https://cloud/secret-link")
