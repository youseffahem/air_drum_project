"""Phase 16 measurement helpers; diagnostics never select a deployment model."""

from __future__ import annotations

import ctypes as ct
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from _p10 import provenance, source_hashes, write_json
from _runlog import RunLog, git_dirty, git_sha

from spacedrums.config import load_config
from spacedrums.timing import wall_clock_iso


def distribution(seconds):
    values = np.asarray(seconds, dtype=float)
    if not len(values):
        return {"n": 0, "p50_ms": None, "p95_ms": None, "max_ms": None}
    return {
        "n": len(values),
        "mean_ms": float(values.mean() * 1000),
        "p50_ms": float(np.percentile(values, 50) * 1000),
        "p95_ms": float(np.percentile(values, 95) * 1000),
        "max_ms": float(values.max() * 1000),
    }


@contextmanager
def evidence(config_path, output, slug, task):
    cfg = load_config(config_path)
    with RunLog(
        phase="16",
        task=task,
        slug=slug,
        config=cfg,
        experiments_dir=Path(output),
        description="Development performance evidence; no participant or shipped-model claim",
    ) as run:
        initial = source_hashes()
        write_json(run.dir / "execution.json", provenance())
        write_json(run.dir / "source-hashes-start.json", initial)
        yield run, cfg
        final = source_hashes()
        audit = {
            "source_unchanged": initial == final,
            "git_sha_final": git_sha(),
            "git_dirty_final": git_dirty(),
            "finished_at": wall_clock_iso(),
        }
        write_json(run.dir / "audit.json", audit)
        if initial != final:
            raise RuntimeError("source changed during measurement")
        for p in run.dir.rglob("*"):
            if p.is_file() and p.name not in ("run.json", "stdout.log", "config.resolved.yaml"):
                run.add_artefact(p, "other")
        run.finish(audit, status="COMPLETED", notes="Dirty-tree values are development diagnostics only.")
        print(f"EVIDENCE: {run.dir}", flush=True)


def resources():
    """Current-process native thread CPU and working set, with no optional dependencies.

    Windows GetThreadTimes returns cumulative user+kernel CPU; this does not measure GIL wait.
    Threads that disappear between snapshots are explicitly outside the sampled coverage.
    """
    if sys.platform != "win32":
        return {"rss_bytes": None, "threads": {}, "reason": "native sampler implemented for HW-01 Windows"}
    from ctypes import wintypes as wt

    k = ct.WinDLL("kernel32", use_last_error=True)
    ps = ct.WinDLL("psapi", use_last_error=True)
    k.GetCurrentProcess.restype = wt.HANDLE
    k.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    k.CreateToolhelp32Snapshot.restype = wt.HANDLE
    k.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k.OpenThread.restype = wt.HANDLE
    k.CloseHandle.argtypes = [wt.HANDLE]
    k.GetThreadTimes.argtypes = [wt.HANDLE] + [ct.POINTER(wt.FILETIME)] * 4

    class Memory(ct.Structure):
        _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD)] + [
            (name, ct.c_size_t)
            for name in (
                "PeakWorkingSetSize",
                "WorkingSetSize",
                "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage",
                "PagefileUsage",
                "PeakPagefileUsage",
            )
        ]

    class ThreadEntry(ct.Structure):
        _fields_ = [
            (name, wt.DWORD)
            for name in (
                "dwSize",
                "cntUsage",
                "th32ThreadID",
                "th32OwnerProcessID",
            )
        ] + [("tpBasePri", wt.LONG), ("tpDeltaPri", wt.LONG), ("dwFlags", wt.DWORD)]

    ps.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ct.POINTER(Memory), wt.DWORD]
    k.Thread32First.argtypes = [wt.HANDLE, ct.POINTER(ThreadEntry)]
    k.Thread32Next.argtypes = [wt.HANDLE, ct.POINTER(ThreadEntry)]
    mem = Memory()
    mem.cb = ct.sizeof(mem)
    memory_ok = ps.GetProcessMemoryInfo(k.GetCurrentProcess(), ct.byref(mem), mem.cb)
    snapshot = k.CreateToolhelp32Snapshot(0x4, 0)
    threads = {}
    if snapshot != ct.c_void_p(-1).value:
        entry = ThreadEntry()
        entry.dwSize = ct.sizeof(entry)
        try:
            ok = k.Thread32First(snapshot, ct.byref(entry))
            while ok:
                if entry.th32OwnerProcessID == os.getpid():
                    handle = k.OpenThread(0x0800, False, entry.th32ThreadID)
                    if handle:
                        try:
                            a, b, c, d = (wt.FILETIME() for _ in range(4))
                            if k.GetThreadTimes(handle, ct.byref(a), ct.byref(b), ct.byref(c), ct.byref(d)):

                                def ticks(t):
                                    return (t.dwHighDateTime << 32) + t.dwLowDateTime

                                threads[f"{entry.th32ThreadID}:{ticks(a)}"] = (ticks(c) + ticks(d)) / 1e7
                        finally:
                            k.CloseHandle(handle)
                ok = k.Thread32Next(snapshot, ct.byref(entry))
        finally:
            k.CloseHandle(snapshot)
    return {"rss_bytes": int(mem.WorkingSetSize) if memory_ok else None, "threads": threads}


class ResourceSampler:
    def __init__(self):
        self.samples = []
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="phase16-resource-sampler", daemon=True)

    def _sample(self):
        self.samples.append({"elapsed_s": time.perf_counter() - self.start, **resources()})

    def _loop(self):
        while not self.stop_event.wait(1):
            self._sample()

    def __enter__(self):
        self.start, self.cpu = time.perf_counter(), time.process_time()
        self._sample()
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop_event.set()
        self.thread.join()
        self._sample()
        self.wall_s = time.perf_counter() - self.start
        self.cpu_s = time.process_time() - self.cpu

    def report(self):
        spans = {}
        for sample in self.samples:
            for tid, cpu in sample["threads"].items():
                spans.setdefault(tid, [cpu, cpu])[1] = cpu
        return {
            "wall_s": self.wall_s,
            "process_cpu_s": self.cpu_s,
            "process_cpu_one_core_percent": 100 * self.cpu_s / self.wall_s,
            "native_thread_cpu_s": {tid: b - a for tid, (a, b) in spans.items()},
            "native_thread_one_core_percent": {
                tid: 100 * (b - a) / self.wall_s for tid, (a, b) in spans.items()
            },
            "samples": self.samples,
            "limitation": "1 s samples; short-lived threads may be missed; GIL wait is not measured",
        }


@contextmanager
def candidate(name):
    """Reversible research variants, never global deployment settings."""
    from spacedrums.app.main import Perception
    from spacedrums.hands.landmarker import HandLandmarker

    if name == "half-detection":
        original = HandLandmarker._input_image

        def half(self, view):
            pixels, placement = original(self, view)
            # Native coordinates remain normalized to the original spatial placement.
            return cv2.resize(pixels, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA), placement

        with patch.object(HandLandmarker, "_input_image", half):
            yield
    elif name == "perception-thread":
        from concurrent.futures import ThreadPoolExecutor

        original = Perception.__call__
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="perception") as pool:
            with patch.object(
                Perception, "__call__", lambda self, view: pool.submit(original, self, view).result()
            ):
                yield
    elif name == "image-mode":
        from dataclasses import replace

        original = HandLandmarker.__init__

        def image_init(self, settings, **kwargs):
            original(self, replace(settings, running_mode="IMAGE"), **kwargs)

        with patch.object(HandLandmarker, "__init__", image_init):
            yield
    elif name == "perception-process":
        from _p16_process import process_perception

        with process_perception():
            yield
    elif name == "none":
        yield
    else:
        raise ValueError(f"unknown candidate {name}")


CANDIDATES = ("none", "half-detection", "perception-thread", "image-mode", "perception-process")
