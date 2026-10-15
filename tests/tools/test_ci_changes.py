import subprocess

import pytest

from tools import ci_changes


@pytest.mark.parametrize("files", [
    ["docs/WORKLOG.md"],
    ["docs/worklog/2026-10-15-claude-ci-speedup-5yxfv0.md"],
    ["AGENTS.md", "docs/ROADMAP.md", "docs/archive/old.md",
     "docs/design/signal-window.md"],
])
def test_prose_only_skips_the_tests(files):
    assert not ci_changes.needs_tests(files)


@pytest.mark.parametrize("files", [
    ["docs/WORKLOG.md", "src/poker_engine/desktop/live.py"],
    ["docs/strategy-requirements-matrix.md"],              # a test reads it
    ["docs/strategy-regression-test-matrix.md"],
    ["docs/examples/frozen-postflop/root-oop-aa.json"],    # a test reads it
    ["src/poker_engine/strategy/assets/notes.md"],          # shipped with the package
    ["launch/mac/README.md"],
    [".github/workflows/ci.yml"],
    ["pyproject.toml"],
    [],                                                     # nothing to tell: run
])
def test_anything_else_runs_the_tests(files):
    assert ci_changes.needs_tests(files)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def test_the_diff_is_read_from_git_and_doubt_runs_the_tests(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "ci@example.invalid")
    git(tmp_path, "config", "user.name", "ci")
    (tmp_path / "a.py").write_text("x = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "code")
    base = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "WORKLOG.md").write_text("note\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "prose")
    head = git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.chdir(tmp_path)
    assert ci_changes.changed_files(base, head) == ["docs/WORKLOG.md"]
    assert ci_changes.changed_files("0" * 40, head) is None     # a new branch
    assert ci_changes.changed_files("f" * 40, head) is None     # base not fetched
    output = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    ci_changes.main([base, head])
    ci_changes.main([])                                         # workflow_dispatch
    assert output.read_text().splitlines() == ["code=false", "code=true"]


def test_a_code_file_renamed_into_docs_still_runs_the_tests(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "ci@example.invalid")
    git(tmp_path, "config", "user.name", "ci")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mod.py").write_text("x = 1\n" * 20)
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "code")
    base = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "docs").mkdir()
    git(tmp_path, "mv", "src/mod.py", "docs/mod.md")
    git(tmp_path, "commit", "-qm", "moved")
    head = git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.chdir(tmp_path)
    files = ci_changes.changed_files(base, head)
    assert "src/mod.py" in files
    assert ci_changes.needs_tests(files)
