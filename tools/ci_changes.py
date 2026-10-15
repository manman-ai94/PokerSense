"""Does a change need the test jobs? CI skips them when only prose changed.

Same intent as ``paths-ignore`` on doc-only commits, but implemented as a
hygiene step so required checks still complete (a workflow skipped entirely by
``paths-ignore`` leaves branch protection waiting forever).

Prose is a Markdown file at the top level or under ``docs/``, except the
Markdown files the tests read (``TEST_READ``). Anything else, a change that
cannot be worked out (no base commit, a base not fetched) or an explicit run
needs the tests: when in doubt they run.

On a pull request it also guards the evaluator: a change may touch the
strategy files or the evaluator files listed in
``configs/evaluator-protection.json`` (the simulated opponents and table,
their numbers and fits, the gates, this check), not both, so strategy work
cannot move its own goalposts. Touching both fails the step.

Usage: python tools/ci_changes.py [BASE HEAD]
Prints ``code=true`` or ``code=false`` and adds it to ``$GITHUB_OUTPUT``.
"""

from fnmatch import fnmatchcase
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys

GUARD = Path(__file__).resolve().parents[1] / "configs" / "evaluator-protection.json"


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
        listing = subprocess.run(["git", "diff", "--name-only", "--no-renames",
                                  f"{base}...{head}"],
                                 check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return listing.stdout.splitlines()


def touched(files, patterns):
    return sorted(name for name in files
                  if any(fnmatchcase(name.replace("\\", "/"), pattern)
                         for pattern in patterns))


def evaluator_conflict(files, guard=None):
    """(strategy files, evaluator files) when ``files`` touch both, else None."""
    guard = guard or json.loads(GUARD.read_text(encoding="utf-8"))
    strategy, evaluator = (touched(files, guard[side])
                           for side in ("strategy", "evaluator"))
    return (strategy, evaluator) if strategy and evaluator else None


def main(argv):
    files = changed_files(*argv) if len(argv) == 2 else None
    line = f"code={'true' if files is None or needs_tests(files) else 'false'}"
    print(line)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    conflict = (evaluator_conflict(files) if files is not None
                and os.environ.get("GITHUB_EVENT_NAME") == "pull_request" else None)
    if conflict:
        strategy, evaluator = conflict
        print("::error::This pull request changes both the strategy and the evaluator "
              "(configs/evaluator-protection.json). Split it into two pull requests.")
        print("strategy: " + ", ".join(strategy))
        print("evaluator: " + ", ".join(evaluator))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
