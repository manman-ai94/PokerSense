"""Fold the per-PR worklog files into the top of docs/WORKLOG.md.

Each merged change writes its entry as its own file,
``docs/worklog/<date>-<branch>.md``, so two PRs never touch the same file and
GitHub never flags a conflict. This tool moves those entries into the
"记录" section of ``docs/WORKLOG.md`` (newest first) and deletes the folded
files, so people still read one place. The nightly routine runs it as its own
PR.

Order: by the date in the file name, newest first; on the same date, the PR
merged last comes first (files git does not know yet count as newest). The
merge time is read from main's own history (``--first-parent``), so run this
on a checkout of main: an entry counts from the merge that brought it into
main, even when it was written earlier on its branch or inside a merge of main
into that branch.

Usage: python tools/worklog_rollup.py [--root DIR] [--dry-run]
"""

import argparse
from pathlib import Path
import re
import subprocess
import sys


ENTRY = re.compile(r"^(\d{4}-\d{2}-\d{2})-.+\.md$")
SECTION = "## 记录\n"


def entries(folder):
    return sorted(path for path in folder.glob("*.md") if ENTRY.match(path.name))


def added_at(root, path):
    """Seconds since the epoch when ``path`` came into the checked-out branch
    (for main: when its PR merged); None if unknown.

    ``--first-parent`` compares each merge with the branch it landed on, so the
    merge that brought the file in is the one that adds it."""
    try:
        out = subprocess.run(
            ["git", "log", "--first-parent", "--diff-filter=A", "--format=%ct",
             "-1", "--", path.relative_to(root).as_posix()],
            cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return int(out) if out else None


def newest_first(root, paths):
    def key(path):
        stamp = added_at(root, path)
        return (ENTRY.match(path.name).group(1),
                float("inf") if stamp is None else stamp, path.name)
    return sorted(paths, key=key, reverse=True)


def fold(worklog_text, blocks):
    """Insert ``blocks`` right under the "记录" heading."""
    at = worklog_text.find(SECTION)
    if at < 0:
        raise ValueError("docs/WORKLOG.md has no '## 记录' section")
    head = worklog_text[:at + len(SECTION)]
    rest = worklog_text[at + len(SECTION):].lstrip("\n")
    body = "\n\n".join(block.strip("\n") for block in blocks)
    return head + "\n" + body + "\n\n" + rest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be folded, change nothing")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    worklog = root / "docs" / "WORKLOG.md"
    paths = newest_first(root, entries(root / "docs" / "worklog"))
    if not paths:
        print("nothing to fold")
        return 0
    blocks = [path.read_text(encoding="utf-8") for path in paths]
    if any(not block.strip() for block in blocks):
        print("empty entry file; fix it first", file=sys.stderr)
        return 1
    text = fold(worklog.read_text(encoding="utf-8"), blocks)
    for path in paths:
        print(("would fold " if args.dry_run else "folded ") + path.name)
    if args.dry_run:
        return 0
    worklog.write_text(text, encoding="utf-8")
    for path in paths:
        path.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
