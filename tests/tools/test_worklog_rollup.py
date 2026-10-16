import os
import subprocess

from tools import worklog_rollup

HEADER = "# 工作记录\n\n说明。\n\n## 记录\n\n"
OLD = "**2026-10-14 · `old`（旧）**\n- 做了什么：旧的。\n"


def tree(tmp_path, files):
    (tmp_path / "docs" / "worklog").mkdir(parents=True)
    (tmp_path / "docs" / "WORKLOG.md").write_text(HEADER + OLD, encoding="utf-8")
    (tmp_path / "docs" / "worklog" / "README.md").write_text("规则\n", encoding="utf-8")
    for name, text in files.items():
        (tmp_path / "docs" / "worklog" / name).write_text(text, encoding="utf-8")


def worklog(tmp_path):
    return (tmp_path / "docs" / "WORKLOG.md").read_text(encoding="utf-8")


def entry(title):
    return f"### {title}\n- 做了什么：{title}。\n"


def git(tmp_path, *args, when=None):
    env = None
    if when:
        env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   cwd=tmp_path, check=True, capture_output=True, env=env)


def test_folds_newest_first_under_the_heading_and_deletes_the_files(tmp_path):
    tree(tmp_path, {"2026-10-15-claude-a.md": entry("A"),
                    "2026-10-16-claude-b.md": entry("B")})
    assert worklog_rollup.main(["--root", str(tmp_path)]) == 0
    text = worklog(tmp_path)
    assert text == HEADER + entry("B") + "\n" + entry("A") + "\n" + OLD
    assert [p.name for p in (tmp_path / "docs" / "worklog").iterdir()] == ["README.md"]


def test_same_day_the_entry_git_added_last_comes_first(tmp_path):
    tree(tmp_path, {})
    git(tmp_path, "init", "-q")
    # Name order would put z first; the later merge must win instead.
    for name, when in (("2026-10-15-z-merged-first.md", "2026-10-15T10:00:00"),
                       ("2026-10-15-a-merged-second.md", "2026-10-15T11:00:00")):
        (tmp_path / "docs" / "worklog" / name).write_text(entry(name), encoding="utf-8")
        git(tmp_path, "add", ".")
        git(tmp_path, "commit", "-q", "-m", name, when=when)
    (tmp_path / "docs" / "worklog" / "2026-10-15-b-not-merged.md").write_text(
        entry("new"), encoding="utf-8")
    paths = worklog_rollup.entries(tmp_path / "docs" / "worklog")
    assert [p.name for p in worklog_rollup.newest_first(tmp_path, paths)] == [
        "2026-10-15-b-not-merged.md", "2026-10-15-a-merged-second.md",
        "2026-10-15-z-merged-first.md"]


def test_an_entry_written_in_a_merge_commit_keeps_its_place(tmp_path):
    """Moving an entry into docs/worklog/ while resolving a merge with main
    adds the file in the merge commit itself (#60 and #67 did this on
    2026-10-15); it must not count as "not added yet" and jump to the top."""
    tree(tmp_path, {})
    git(tmp_path, "init", "-q", "-b", "main")
    folder = tmp_path / "docs" / "worklog"

    def commit(name, when):
        (folder / name).write_text(entry(name), encoding="utf-8")
        git(tmp_path, "add", ".")
        git(tmp_path, "commit", "-q", "-m", name, when=when)

    commit("2026-10-15-z-first.md", "2026-10-15T10:00:00")
    git(tmp_path, "checkout", "-q", "-b", "branch")
    (tmp_path / "branch.txt").write_text("b\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "branch work", when="2026-10-15T10:10:00")
    git(tmp_path, "checkout", "-q", "main")
    (tmp_path / "main.txt").write_text("m\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "main work", when="2026-10-15T10:20:00")
    git(tmp_path, "checkout", "-q", "branch")
    git(tmp_path, "merge", "-q", "--no-ff", "--no-commit", "main")
    (folder / "2026-10-15-m-in-merge.md").write_text(entry("m"), encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "merge main", when="2026-10-15T10:30:00")
    git(tmp_path, "checkout", "-q", "main")
    commit("2026-10-15-a-last.md", "2026-10-15T11:00:00")
    git(tmp_path, "merge", "-q", "--no-ff", "-m", "merge branch", "branch",
        when="2026-10-15T11:30:00")
    paths = worklog_rollup.entries(folder)
    assert [p.name for p in worklog_rollup.newest_first(tmp_path, paths)] == [
        "2026-10-15-a-last.md", "2026-10-15-m-in-merge.md", "2026-10-15-z-first.md"]


def test_dry_run_and_nothing_to_fold_change_nothing(tmp_path, capsys):
    tree(tmp_path, {"2026-10-15-claude-a.md": entry("A")})
    assert worklog_rollup.main(["--root", str(tmp_path), "--dry-run"]) == 0
    assert "would fold 2026-10-15-claude-a.md" in capsys.readouterr().out
    assert worklog(tmp_path) == HEADER + OLD
    (tmp_path / "docs" / "worklog" / "2026-10-15-claude-a.md").unlink()
    assert worklog_rollup.main(["--root", str(tmp_path)]) == 0
    assert "nothing to fold" in capsys.readouterr().out


def test_an_empty_entry_stops_without_changing_anything(tmp_path):
    tree(tmp_path, {"2026-10-15-claude-a.md": entry("A"),
                    "2026-10-15-claude-b.md": "\n"})
    assert worklog_rollup.main(["--root", str(tmp_path)]) == 1
    assert worklog(tmp_path) == HEADER + OLD
    assert (tmp_path / "docs" / "worklog" / "2026-10-15-claude-a.md").exists()
