"""Tests for the macOS Quartz capture backend.

Split in two:
- Mocked logic tests (window resolution / error paths): run everywhere,
  independent of whether pyobjc is actually installed.
- A real capture smoke test: only runs when ``Quartz`` is importable (i.e.
  on macOS with the ``perceptual`` extra installed), and skips (rather than
  fails) if the Screen Recording permission hasn't been granted yet -- that
  permission can only be granted interactively by a human, not by a test.
"""

from __future__ import annotations

import pytest

import poker_engine.perceptual.capture.quartz_backend as qb
from poker_engine.perceptual.capture.base import CaptureError, CaptureTarget


@pytest.fixture(autouse=True)
def _screen_permission_granted(request, monkeypatch):
    """Mocked tests model a granted permission; the real smoke test checks it."""
    if request.node.name != "test_real_quartz_capture_smoke":
        monkeypatch.setattr(qb, "has_screen_capture_permission", lambda: True)


class _FakeQuartz:
    """Minimal stand-in for the ``Quartz`` module's constants used here."""

    kCGWindowListExcludeDesktopElements = 1 << 4
    kCGWindowListOptionOnScreenOnly = 1 << 0
    kCGWindowListOptionIncludingWindow = 1 << 3
    kCGWindowImageBoundsIgnoreFraming = 1 << 0
    kCGNullWindowID = 0
    kCGImageAlphaPremultipliedFirst = 2
    kCGBitmapByteOrder32Little = 8192


def test_quartz_backend_requires_quartz_when_unavailable(monkeypatch):
    monkeypatch.setattr(qb, "_HAS_QUARTZ", False)
    with pytest.raises(RuntimeError):
        qb.QuartzBackend()


def test_capture_type_check(monkeypatch):
    monkeypatch.setattr(qb, "_HAS_QUARTZ", True)
    be = object.__new__(qb.QuartzBackend)  # bypass __init__
    with pytest.raises(TypeError):
        be.capture("not-a-target")


def test_window_not_found(monkeypatch):
    monkeypatch.setattr(qb, "_find_window_matches", lambda title: ([], []))
    be = object.__new__(qb.QuartzBackend)
    with pytest.raises(CaptureError, match="not found or closed"):
        be._resolve_window(CaptureTarget(window_id="missing-window"))


def test_window_resolution_explains_missing_screen_permission(monkeypatch):
    monkeypatch.setattr(qb, "has_screen_capture_permission", lambda: False)
    be = object.__new__(qb.QuartzBackend)
    with pytest.raises(CaptureError, match="Screen Recording permission"):
        be._resolve_window(CaptureTarget(window_id="table"))


def test_window_ambiguous(monkeypatch):
    monkeypatch.setattr(
        qb,
        "_find_window_matches",
        lambda title: ([{"a": 1}, {"a": 2}], [{"a": 1}, {"a": 2}]),
    )
    be = object.__new__(qb.QuartzBackend)
    with pytest.raises(CaptureError, match="ambiguous"):
        be._resolve_window(CaptureTarget(window_id="dup-title"))


def test_window_minimized(monkeypatch):
    match = {
        "kCGWindowNumber": 7,
        "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 100, "Height": 50},
    }
    monkeypatch.setattr(qb, "_find_window_matches", lambda title: ([match], []))
    be = object.__new__(qb.QuartzBackend)
    with pytest.raises(CaptureError, match="active macOS Space"):
        be._resolve_window(CaptureTarget(window_id="hidden-window"))


def test_window_invalid_bounds(monkeypatch):
    match = {
        "kCGWindowNumber": 7,
        "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 0, "Height": 50},
    }
    monkeypatch.setattr(qb, "_find_window_matches", lambda title: ([match], [match]))
    be = object.__new__(qb.QuartzBackend)
    with pytest.raises(CaptureError, match="invalid bounds"):
        be._resolve_window(CaptureTarget(window_id="zero-width-window"))


def test_resolve_window_returns_number_and_rect(monkeypatch):
    match = {
        "kCGWindowNumber": 42,
        "kCGWindowBounds": {"X": 10, "Y": 20, "Width": 300, "Height": 200},
    }
    monkeypatch.setattr(qb, "_find_window_matches", lambda title: ([match], [match]))
    be = object.__new__(qb.QuartzBackend)
    number, rect = be._resolve_window(CaptureTarget(window_id="some-window"))
    assert number == 42
    assert rect.left == 10
    assert rect.top == 20
    assert rect.width == 300
    assert rect.height == 200


def test_resolve_window_selects_explicit_visible_index(monkeypatch):
    matches = [
        {
            "kCGWindowNumber": 10,
            "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 100, "Height": 50},
        },
        {
            "kCGWindowNumber": 11,
            "kCGWindowBounds": {"X": 100, "Y": 0, "Width": 100, "Height": 50},
        },
    ]
    monkeypatch.setattr(qb, "_find_window_matches", lambda title: (matches, matches))
    be = object.__new__(qb.QuartzBackend)
    number, rect = be._resolve_window(CaptureTarget("dup-title", window_index=1))
    assert number == 11
    assert rect.left == 100


def test_resolve_window_rejects_out_of_range_index(monkeypatch):
    match = {
        "kCGWindowNumber": 7,
        "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 100, "Height": 50},
    }
    monkeypatch.setattr(qb, "_find_window_matches", lambda title: ([match], [match]))
    be = object.__new__(qb.QuartzBackend)
    with pytest.raises(CaptureError, match="out of range"):
        be._resolve_window(CaptureTarget("table", window_index=1))


def test_bitmap_layout_mismatch_raises(monkeypatch):
    fake = _FakeQuartz()
    fake.CGImageGetBitmapInfo = lambda ref: 0  # wrong layout
    monkeypatch.setattr(qb, "Quartz", fake)
    monkeypatch.setattr(qb, "_EXPECTED_BITMAP_INFO", 8194)
    with pytest.raises(CaptureError, match="unexpected CGImage bitmap layout"):
        qb._cgimage_to_bgr_ndarray(object())


def test_capture_raises_when_image_creation_fails(monkeypatch):
    match = {
        "kCGWindowNumber": 1,
        "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 100, "Height": 50},
    }
    monkeypatch.setattr(qb, "_find_window_matches", lambda title: ([match], [match]))

    fake = _FakeQuartz()
    fake.CGRectMake = lambda *a: a
    fake.CGWindowListCreateImage = lambda *a, **k: None
    monkeypatch.setattr(qb, "Quartz", fake)
    monkeypatch.setattr(qb, "_HAS_QUARTZ", True)

    be = object.__new__(qb.QuartzBackend)
    with pytest.raises(CaptureError, match="failed to capture image"):
        be.capture(CaptureTarget(window_id="some-window"))


def test_capture_uses_explicit_fullscreen_fallback_when_title_is_hidden(monkeypatch):
    be = object.__new__(qb.QuartzBackend)
    monkeypatch.setattr(qb, "has_screen_capture_permission", lambda: True)
    monkeypatch.setattr(
        be,
        "_resolve_window",
        lambda target: (_ for _ in ()).throw(CaptureError("not found or closed")),
    )
    expected = object()
    monkeypatch.setattr(be, "_capture_main_display", lambda target: expected)
    target = CaptureTarget("WePoker-H5", allow_fullscreen_fallback=True)
    assert be.capture(target) is expected


# --- real capture smoke test (only runs where Quartz is actually usable) ---


def test_real_quartz_capture_smoke():
    pytest.importorskip("Quartz")

    onscreen = qb._list_windows(on_screen_only=True)
    # Windows with a reasonably large, on-screen bounding box and a title
    # that is unique among on-screen windows -- excludes ambiguous system
    # menu-bar/status items (e.g. multiple "StatusIndicator" windows).
    titles_seen = [w.get("kCGWindowName") for w in onscreen]
    candidates = [
        w
        for w in onscreen
        if w.get("kCGWindowName")
        and titles_seen.count(w.get("kCGWindowName")) == 1
        and w.get("kCGWindowBounds", {}).get("Width", 0) >= 100
        and w.get("kCGWindowBounds", {}).get("Height", 0) >= 100
    ]
    if not candidates:
        pytest.skip("no unambiguous, reasonably-sized on-screen window to capture")

    backend = qb.QuartzBackend()
    last_error: CaptureError | None = None
    for w in candidates:
        title = w["kCGWindowName"]
        try:
            frame = backend.capture(CaptureTarget(window_id=title))
        except CaptureError as exc:
            if "Screen Recording" in str(exc) or "permission" in str(exc).lower():
                pytest.skip(f"Screen Recording permission not granted: {exc}")
            last_error = exc
            continue

        assert frame.width > 0
        assert frame.height > 0
        assert frame.image.shape == (frame.height, frame.width, 3)
        assert frame.image.dtype.name == "uint8"
        return

    pytest.fail(f"no candidate window could be captured; last error: {last_error}")
