"""Where PokerSense's private data lives on this machine.

Recordings, frames, labels and models are never in the repository. They sit
under one data root laid out like the old Windows ``G:`` drive:
``<root>/PokerSense_private`` and ``<root>/PokerSense_archive``.

The root is ``$POKERSENSE_DATA_ROOT`` when set; otherwise ``G:/`` on Windows
(unchanged legacy behaviour) and ``~/Projects/PokerSense_data`` elsewhere.

Configs written on the old Windows machine still carry absolute paths such as
``G:/PokerSense_private/...`` or ``C:/Users/Administrator/WorkBuddy/扑克/
PokerSense/...``. :func:`resolve_legacy_path` maps those onto this machine;
on Windows they are real absolute paths and are left alone.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

DATA_ROOT_ENV = "POKERSENSE_DATA_ROOT"
REPO_ROOT = Path(__file__).resolve().parents[2]

_LEGACY_REPO = "c:/users/administrator/workbuddy/扑克/pokersense"
_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _default_data_root() -> Path:
    return Path("G:/") if os.name == "nt" else Path("~/Projects/PokerSense_data")


def data_root() -> Path:
    """The directory holding ``PokerSense_private`` and ``PokerSense_archive``."""
    value = os.environ.get(DATA_ROOT_ENV, "").strip()
    return (Path(value) if value else _default_data_root()).expanduser()


def private_root() -> Path:
    return data_root() / "PokerSense_private"


def archive_root() -> Path:
    return data_root() / "PokerSense_archive"


def resolve_legacy_path(value: str) -> Path | None:
    """Map an old Windows absolute path onto this machine, or return None.

    ``G:/X`` becomes ``data_root()/X`` and paths inside the old checkout
    become paths inside this checkout. Anything else, including paths this
    machine already treats as absolute, is not a legacy path.
    """
    if not _DRIVE_PATH.match(value) or Path(value).is_absolute():
        return None
    text = value.replace("\\", "/")
    folded = text.casefold()
    if folded == _LEGACY_REPO or folded.startswith(_LEGACY_REPO + "/"):
        return REPO_ROOT / text[len(_LEGACY_REPO):].lstrip("/")
    if folded.startswith("g:/"):
        return data_root() / text[3:]
    return None


__all__ = [
    "DATA_ROOT_ENV",
    "REPO_ROOT",
    "archive_root",
    "data_root",
    "private_root",
    "resolve_legacy_path",
]
