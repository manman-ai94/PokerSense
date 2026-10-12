"""Does a change need the test jobs? CI skips them when only prose changed.

Prose is a Markdown file at the top level or under ``docs/``, except the
Markdown files the tests read (``TEST_READ``). Anything else, a change that
cannot be worked out (no base commit, a base not fetched) or an explicit run
needs the tests: when in doubt they run.

Usage: python tools/ci_changes.py [BASE HEAD]
Prints ``code=true`` or ``code=false`` and adds it to ``$GITHUB_OUTPUT``.
"""

import os
from pathlib import PurePosixPath
import subprocess
import sys


# tests/strategy/test_mock_fixture_dataset.py reads these.
TEST_READ = {
    "docs/strategy-requirements-matrix.md",
    "docs/strategy-regression-test-matrix.md",
}


def is_prose(filename):
    path = PurePosixPath(filename.replace("\\", "/"))
    if path.suffix.lower() != ".md" or path.as_posix() in TEST_READ:
        return False
    return len(path.parts) == 1 or path.parts[0] == "docs"


def needs_tests(filenames):
    filenames = [name for name in filenames if name.strip()]
    return not filenames or not all(is_prose(name) for name in filenames)


def changed_files(base, head):
    """Files changed from ``base`` to ``head``, or None when that cannot be told."""
    if not base or not head or set(base) == {"0"}:
        return None
    try:
        subprocess.run(["git", "cat-file", "-e", f"{base}^{{commit}}"], check=True,
                       capture_output=True)
        listing = subprocess.run(["git", "diff", "--name-only", f"{base}...{head}"],
                                 check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return listing.stdout.splitlines()


def main(argv):
    files = changed_files(*argv) if len(argv) == 2 else None
    line = f"code={'true' if files is None or needs_tests(files) else 'false'}"
    print(line)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
