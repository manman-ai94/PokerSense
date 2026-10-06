"""OS-held exclusive ownership for AA capture processes on this computer.

The lock file remains on disk; only the operating-system lock indicates an AA
owner. Existing legacy recorder markers are checked conservatively, but that
recorder does not participate in this protocol and can still race a later start.
"""

import os
from pathlib import Path
import tempfile
import threading

from ..data_paths import private_root


DEFAULT_LOCK_PATH = Path(tempfile.gettempdir()) / "pokersense-aa-capture.lock"
LEGACY_RECORDER_LOCK = private_root() / ".aa-passive-capture-v1.device.lock"
_UNCERTAIN_RELEASES = []


class AACaptureDeviceLock:
    """Nonblocking global capture exclusion, independent of index/API aliases."""

    def __init__(self, path=None, *, legacy_lock_path=LEGACY_RECORDER_LOCK):
        self.path = Path(path) if path is not None else DEFAULT_LOCK_PATH
        self.legacy_lock_path = (Path(legacy_lock_path)
                                 if legacy_lock_path is not None else None)
        self._handle = None
        self._mutex = threading.RLock()
        self._quarantined = False

    def _check_legacy(self):
        if self.legacy_lock_path is not None and self.legacy_lock_path.exists():
            raise RuntimeError(
                "检测到 AA 旁观录制锁；请先结束原录制程序并核实其锁状态。"
                "本工具不会删除该锁。")

    def acquire(self):
        with self._mutex:
            if self._quarantined:
                raise RuntimeError("采集设备释放失败，请退出本程序后再重试")
            if self._handle is not None:
                return self
            self._check_legacy()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = self.path.open("a+b")
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                handle.close()
                raise RuntimeError(
                    "另一 AA 观察进程正在使用采集卡；请先停止或关闭它") from exc
            try:
                self._check_legacy()
            except Exception:
                handle.close()
                raise
            self._handle = handle
            return self

    def release(self):
        with self._mutex:
            if self._quarantined:
                return
            if self._handle is not None:
                # Closing the handle releases its OS lock even after a crash;
                # deleting the shared file would permit different lock inodes.
                self._handle.close()
                self._handle = None

    def retain_until_process_exit(self):
        """Keep ownership when backend cleanup cannot confirm device release."""
        with self._mutex:
            if self._handle is not None and not self._quarantined:
                self._quarantined = True
                _UNCERTAIN_RELEASES.append(self)


__all__ = ["AACaptureDeviceLock"]
