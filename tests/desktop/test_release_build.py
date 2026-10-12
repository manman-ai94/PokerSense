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


def test_a_packed_bundle_is_installed_next_to_the_program_and_validates(
        bundle, tmp_path):
    out = tmp_path / "upload"
    sidecar = packer.pack(bundle, out)
    again = packer.pack(bundle, tmp_path / "again")
    assert again["zip_sha256"] == sidecar["zip_sha256"]          # reproducible
    app = tmp_path / "PokerSense-AA"
    app.mkdir()
    result = release.embed_recognition(out, app)
    assert result["receipt"]["manifest_sha256"] == sidecar["manifest_sha256"]
    assert (app / "recognition.sha256").read_text("utf-8").strip() == (
        sidecar["manifest_sha256"])
    assert (app / "recognition" / "profile.json").is_file()
    entry = load("aa_entry_recognition", "packaging/aa_live_entry.py")
    assert entry.recognition_bundle(app) == (
        app / "recognition" / "profile.json", sidecar["manifest_sha256"])
    assert entry.recognition_bundle(tmp_path) is None
    assert entry.recognition_bundle(None) is None


def test_a_changed_or_unsafe_recognition_zip_is_refused(bundle, tmp_path):
    out = tmp_path / "upload"
    packer.pack(bundle, out)
    archive = out / packer.ZIP_NAME
    with zipfile.ZipFile(archive, "a") as handle:
        handle.writestr("extra.txt", "changed")
    with pytest.raises(SystemExit, match="sidecar"):
        release.embed_recognition(out, tmp_path / "app")
    evil = tmp_path / "evil"
    evil.mkdir()
    with zipfile.ZipFile(evil / packer.ZIP_NAME, "w") as handle:
        handle.writestr("../outside.txt", "x")
    data = (evil / packer.ZIP_NAME).read_bytes()
    (evil / packer.JSON_NAME).write_text(json.dumps({
        "schema": packer.SCHEMA, "zip_bytes": len(data),
        "zip_sha256": release.hashlib.sha256(data).hexdigest(),
        "manifest_sha256": "0" * 64}), "utf-8")
    with pytest.raises(SystemExit, match="unsafe"):
        release.embed_recognition(evil, tmp_path / "app2")
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
    assert workflow.count("if: steps.mode.outputs.upload == 'true'") >= 4
    assert "persist-credentials: false" in workflow
    assert "softprops/action-gh-release" not in workflow
    legacy = (ROOT / ".github/workflows/build-desktop.yml").read_text("utf-8")
    assert "action-gh-release" not in legacy and "tags:" not in legacy
