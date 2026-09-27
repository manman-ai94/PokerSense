"""Read-only learning diagnostics; a changed distribution is not poker strength."""
from __future__ import annotations

import os
import sys


def memory_usage():
    """Actual process measurements or explicit unknown; no additional dependency."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]

            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            get_process = ctypes.windll.kernel32.GetCurrentProcess
            get_process.restype = wintypes.HANDLE
            read = ctypes.windll.psapi.GetProcessMemoryInfo
            read.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            if not read(get_process(), ctypes.byref(counters), counters.cb):
                raise OSError("GetProcessMemoryInfo failed")
            return {"rss_bytes": counters.WorkingSetSize,
                    "peak_rss_bytes": counters.PeakWorkingSetSize,
                    "source": "Windows_GetProcessMemoryInfo"}
        import resource
        maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak = int(maximum * (1 if sys.platform == "darwin" else 1024))
        rss = None
        if sys.platform.startswith("linux"):
            with open("/proc/self/statm", encoding="ascii") as stream:
                rss = int(stream.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        return {"rss_bytes": rss, "peak_rss_bytes": peak,
                "source": "getrusage_and_proc"}
    except (ImportError, OSError, ValueError, AttributeError, IndexError):
        return {"rss_bytes": None, "peak_rss_bytes": None, "source": "UNKNOWN"}


def learning_summary(trainer, *, elapsed_seconds, threshold=1e-8):
    policy = trainer.average_policy()
    nonuniform, repeated_nonuniform, samples = 0, 0, []
    for key, distribution in sorted(policy.items()):
        uniform = 1 / len(distribution)
        distance = sum(abs(value - uniform) for value in distribution.values()) / 2
        repeated = trainer.visits.get(key, 0) >= 2
        if distance > threshold:
            nonuniform += 1
            repeated_nonuniform += int(repeated)
            if len(samples) < 10:
                samples.append({"information_key": key,
                                "committed_visits": trainer.visits.get(key, 0),
                                "total_variation_from_uniform": distance,
                                "distribution": distribution})
    return {
        "completed_sweeps": trainer.iterations,
        "committed_nodes": trainer.total_nodes,
        "committed_visits": sum(trainer.visits.values()),
        "visited_infosets": len(trainer.visits),
        "repeated_infosets": sum(value >= 2 for value in trainer.visits.values()),
        "exported_infosets": len(policy), "nonuniform_infosets": nonuniform,
        "repeated_exported_nonuniform_infosets": repeated_nonuniform,
        "nonuniform_threshold_tv": threshold, "distribution_samples": samples,
        "elapsed_seconds": elapsed_seconds,
        "committed_nodes_per_second": (trainer.total_nodes / elapsed_seconds
                                       if elapsed_seconds > 0 else None),
        "memory": memory_usage(), "update_regrets": trainer.update_regrets,
        "learning_signal": (trainer.update_regrets and trainer.iterations >= 2
                            and repeated_nonuniform > 0),
        "strategy_strength": "NOT_ASSESSED",
    }
