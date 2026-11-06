from __future__ import annotations

import ctypes
import os
import threading
import time
from typing import Any


class ProcessTreeSampler:
    """Sample process-tree working set concurrently; peaks are same-sample sums."""

    def __init__(self, root_pid: int | None = None, interval_seconds: float = 0.20) -> None:
        self.root_pid = int(root_pid or os.getpid())
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._samples: list[dict[str, Any]] = []

    def start(self) -> "ProcessTreeSampler":
        self._thread = threading.Thread(target=self._sample_loop, name="benchmark-memory-sampler", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if not self._samples:
            return {"status": "UNAVAILABLE", "scope": "process tree", "sampleCount": 0}
        peak = max(self._samples, key=lambda row: row["combinedWorkingSetBytes"])
        root_peak = max(row["rootWorkingSetBytes"] for row in self._samples)
        child_peak = max(row["descendantWorkingSetBytes"] for row in self._samples)
        return {
            "status": "MEASURED",
            "scope": "root process plus currently live descendants; bytes are summed within each timestamp, peak is the maximum simultaneous sampled sum",
            "sampleIntervalSeconds": self.interval_seconds,
            "sampleCount": len(self._samples),
            "peakCombinedWorkingSetBytes": peak["combinedWorkingSetBytes"],
            "peakRootWorkingSetBytes": root_peak,
            "peakDescendantWorkingSetBytes": child_peak,
            "peakSampleAtMonotonic": peak["atMonotonic"],
            "samplingResolutionCaveat": "Short-lived child-process peaks between samples may be missed.",
        }

    def _sample_loop(self) -> None:
        while not self._stop.is_set():
            current = _process_tree_working_set(self.root_pid)
            if current is not None:
                self._samples.append({**current, "atMonotonic": time.perf_counter()})
            self._stop.wait(self.interval_seconds)


def _process_tree_working_set(root_pid: int) -> dict[str, int] | None:
    if os.name != "nt":
        try:
            import psutil  # type: ignore[import-not-found]
            root = psutil.Process(root_pid)
            rows = [root, *root.children(recursive=True)]
            values = [(process.pid, int(process.memory_info().rss)) for process in rows]
            root_bytes = next((rss for pid, rss in values if pid == root_pid), 0)
            total = sum(rss for _, rss in values)
            return {"rootWorkingSetBytes": root_bytes, "descendantWorkingSetBytes": total - root_bytes, "combinedWorkingSetBytes": total}
        except Exception:
            return None
    try:
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        PROCESS_MEMORY_COUNTERS = type("PROCESS_MEMORY_COUNTERS", (ctypes.Structure,), {
            "_fields_": [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                         ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                         ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                         ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                         ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)],
        })

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        invalid = ctypes.c_void_p(-1).value
        if snapshot == invalid:
            return None
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            rows: dict[int, int] = {}
            more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                rows[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)

        descendants: set[int] = set()
        frontier = {root_pid}
        while frontier:
            found = {pid for pid, parent in rows.items() if parent in frontier and pid not in descendants and pid != root_pid}
            if not found:
                break
            descendants.update(found)
            frontier = found
        ids = {root_pid, *descendants}
        bytes_by_pid: dict[int, int] = {}
        for pid in ids:
            handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
            if not handle:
                continue
            try:
                counters = PROCESS_MEMORY_COUNTERS()
                counters.cb = ctypes.sizeof(counters)
                if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                    bytes_by_pid[pid] = int(counters.WorkingSetSize)
            finally:
                kernel32.CloseHandle(handle)
        if root_pid not in bytes_by_pid:
            return None
        root_bytes = bytes_by_pid[root_pid]
        total = sum(bytes_by_pid.values())
        return {"rootWorkingSetBytes": root_bytes, "descendantWorkingSetBytes": total - root_bytes, "combinedWorkingSetBytes": total}
    except Exception:
        return None
