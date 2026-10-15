"""Shared pytest setup for the PokerSense test suite.

Installs a ``cv2.imread`` shim so fixture loading survives non-ASCII paths,
and gives every test its own capture-card lock file.
"""

import os

import cv2
import numpy as np
import pytest


_ORIGINAL_IMREAD = cv2.imread


def _imread_unicode(filename, flags=cv2.IMREAD_COLOR):
    """``cv2.imread`` that also works when the path contains non-ASCII text.

    On Windows ``cv2.imread`` silently returns ``None`` (after logging a
    decoder warning) for an absolute path containing non-ASCII characters --
    which describes every path in this checkout
    (``...\\WorkBuddy\\扑克\\PokerSense\\...``). Reading the bytes ourselves
    and decoding them with ``cv2.imdecode`` bypasses the filesystem-encoding
    path that breaks.

    ASCII paths keep the native fast path so the shim stays quiet and free.
    Installing it here (instead of editing every call site) keeps tests
    readable and makes new tests immune to the same trap for free.
    """
    try:
        path = os.fspath(filename)
    except TypeError:
        return _ORIGINAL_IMREAD(filename, flags)
    if not isinstance(path, str) or path.isascii():
        return _ORIGINAL_IMREAD(filename, flags)
    try:
        with open(path, "rb") as handle:
            data = np.frombuffer(handle.read(), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


cv2.imread = _imread_unicode


@pytest.fixture(autouse=True)
def _own_capture_lock(tmp_path_factory, monkeypatch):
    """Each test gets its own capture-card lock instead of the computer-wide one.

    The real lock (``aa_device_lock.DEFAULT_LOCK_PATH``, in the system temp
    folder) lets only one AA program hold the capture card. Tests that open a
    capture source without naming a lock would otherwise share it: CI runs the
    suite on several processes at once (``pytest -n auto``), and one test's
    source then finds the card "in use" by another's. A running AA window on a
    developer's machine would block them the same way.
    """
    from poker_engine.desktop import aa_device_lock
    path = tmp_path_factory.mktemp("capture-lock") / "pokersense-aa-capture.lock"
    monkeypatch.setattr(aa_device_lock, "DEFAULT_LOCK_PATH", path)
