"""Minimal experiment-log writer shared by the Phase 02 measurement scripts.

Writes one run directory per docs/repo-layout.md section 3.3 and docs/reproducibility-policy.md:

    experiments/<YYYYMMDD>-<HHMM>-<slug>/
        run.json              (validates against schemas/experiment-log.schema.json)
        config.resolved.yaml  (the exact document hashed into config_hash)
        stdout.log            (everything the script printed)
        <artefacts>           (listed in run.json with SHA-256)

``run.json`` is written with ``status: RUNNING`` at start and rewritten once at the end. Phase 09
replaces this helper with the ``eval`` experiment-log writer; scripts of later phases must not
grow a third one.

Every run records ``git_sha`` / ``git_dirty`` honestly: a dirty tree is allowed during
development but cannot be cited as MEASURED in a gate record (reproducibility-policy.md
section 4). The Phase 02 measurements were necessarily taken on a dirty tree (the code that
measures is the code being added); the gate record states this.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, TextIO

from spacedrums import timing
from spacedrums.config import ResolvedConfig, write_resolved
from spacedrums.contracts import schema as contract_schema

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ROOT / "experiments"
_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


# ----------------------------------------------------------------------------- provenance


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "0" * 40


def git_dirty() -> bool:
    """True if any tracked/untracked change exists outside data/, experiments/, .venv/."""
    try:
        out = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return True
    for line in out.splitlines():
        path = line[3:].strip().strip('"')
        if path.startswith(("data/", "experiments/", ".venv/")):
            continue
        return True
    return False


def lock_hash() -> str:
    return "sha256:" + sha256_file(ROOT / "requirements.lock")


def _powershell(cmd: str) -> str | None:
    if not sys.platform.startswith("win"):
        return None
    try:
        return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                              capture_output=True, text=True, timeout=30, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _ram_gb() -> float | None:
    if sys.platform.startswith("win"):
        class _MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        ms = _MS()
        ms.dwLength = ctypes.sizeof(_MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            return round(ms.ullTotalPhys / 2**30, 1)
    return None


def hardware_snapshot(camera_model: str = "Integrated Webcam (USB 0C45:6717)",
                      audio_device: str = "n/a (Phase 04)") -> dict[str, Any]:
    cpu = _powershell("(Get-CimInstance Win32_Processor).Name") or platform.processor()
    phys = _powershell("(Get-CimInstance Win32_Processor).NumberOfCores")
    snap: dict[str, Any] = {
        "cpu_model": cpu.strip(),
        "physical_cores": int(phys) if phys and phys.isdigit() else (os.cpu_count() or 1),
        "logical_cores": os.cpu_count() or 1,
        "os_build": platform.platform(),
        "camera_model": camera_model,
        "audio_device": audio_device,
    }
    ram = _ram_gb()
    if ram is not None:
        snap["ram_gb"] = ram
    power = _powershell("(Get-CimInstance -ClassName BatteryStatus -Namespace root/wmi | "
                        "Select-Object -First 1).PowerOnline")
    if power:
        snap["power_online"] = power.strip().lower() == "true"
    scheme = _powershell("powercfg /getactivescheme")
    if scheme:
        snap["power_scheme"] = scheme.strip()
    return snap


def environment_block() -> dict[str, Any]:
    libs: dict[str, str] = {}
    for mod in ("numpy", "cv2", "jsonschema", "yaml"):
        try:
            m = __import__(mod)
            libs[mod] = str(getattr(m, "__version__", "?"))
        except Exception:  # noqa: BLE001
            pass
    threads: dict[str, int] = {}
    try:
        import cv2

        threads["cv2"] = int(cv2.getNumThreads())
    except Exception:  # noqa: BLE001
        pass
    if os.environ.get("OMP_NUM_THREADS", "").isdigit():
        threads["OMP_NUM_THREADS"] = int(os.environ["OMP_NUM_THREADS"])
    return {"python": platform.python_version(), "lock_hash": lock_hash(), "libraries": libs,
            "threads": threads, "clock": timing.clock_info()}


# ----------------------------------------------------------------------------- run directory


class _Tee(TextIO):  # minimal stdout tee
    def __init__(self, *streams: TextIO) -> None:
        self._streams = streams

    def write(self, s: str) -> int:  # type: ignore[override]
        for st in self._streams:
            st.write(s)
            st.flush()
        return len(s)

    def flush(self) -> None:
        for st in self._streams:
            st.flush()


class RunLog:
    """Context manager: creates the run directory, tees stdout, writes run.json twice."""

    def __init__(
        self,
        *,
        phase: str,
        task: str,
        slug: str,
        description: str,
        config: ResolvedConfig,
        hardware_id: str = "HW-01",
        arm: str = "NA",
        seed: int = 0,
        experiments_dir: Path | None = None,
        camera_model: str = "Integrated Webcam (USB 0C45:6717)",
    ) -> None:
        if not _SLUG_RE.match(slug) or len(slug) > 40:
            raise ValueError(f"slug {slug!r} must match {_SLUG_RE.pattern} and be <= 40 chars")
        self.run_id = f"{timing.wall_clock_local_compact()}-{slug}"
        self.dir = (experiments_dir or EXPERIMENTS) / self.run_id
        self.phase, self.task, self.description = phase, task, description
        self.config = config
        self.hardware_id, self.arm, self.seed = hardware_id, arm, seed
        self.camera_model = camera_model
        self.artefacts: list[dict[str, Any]] = []
        self.record: dict[str, Any] = {}
        self._log_fh: TextIO | None = None
        self._orig_stdout: TextIO | None = None

    # -- lifecycle -------------------------------------------------------------------------
    def __enter__(self) -> RunLog:
        self.dir.mkdir(parents=True, exist_ok=False)
        write_resolved(self.config, self.dir / "config.resolved.yaml")
        self._log_fh = (self.dir / "stdout.log").open("w", encoding="utf-8")
        self._orig_stdout = sys.stdout
        sys.stdout = _Tee(self._orig_stdout, self._log_fh)
        self.record = {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "phase": self.phase,
            "task": self.task,
            "status": "RUNNING",
            "description": self.description,
            "arm": self.arm,
            "config_hash": self.config.config_hash,
            "config_path": "config.resolved.yaml",
            "dataset_version": "ds-none-v0.0",
            "dataset_hash": "sha256:" + "0" * 64,
            "split": {"scheme": "none"},
            "git_sha": git_sha(),
            "git_dirty": git_dirty(),
            "hardware_id": self.hardware_id,
            "hardware": hardware_snapshot(camera_model=self.camera_model),
            "environment": environment_block(),
            "seed": self.seed,
            "deterministic": False,
            "started_at": timing.wall_clock_iso(),
            "finished_at": None,
            "metrics": {},
            "artefacts": [],
            "parent_run_id": None,
            "notes": "dataset_version ds-none-v0.0: hardware measurement run, consumes no dataset.",
        }
        self._write()
        print(f"[run] {self.run_id} -> {self.dir}")
        print(f"[run] git_sha {self.record['git_sha']} dirty={self.record['git_dirty']} "
              f"config_hash {self.config.config_hash}")
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.record.get("status") == "RUNNING":
            self.finish({}, status="FAILED" if exc_type else "ABORTED",
                        notes=f"exited without finish(): {exc!r}" if exc else None)
        sys.stdout = self._orig_stdout or sys.__stdout__
        if self._log_fh:
            self._log_fh.close()

    # -- content ---------------------------------------------------------------------------
    def write_json_artefact(self, name: str, obj: Any, kind: str = "table") -> Path:
        path = self.dir / name
        path.write_text(json.dumps(obj, indent=2, allow_nan=False), encoding="utf-8")
        self.add_artefact(path, kind)
        return path

    def add_artefact(self, path: Path, kind: str) -> None:
        path = Path(path)
        self.artefacts.append({"path": str(path.relative_to(self.dir)) if path.is_relative_to(self.dir)
                               else str(path), "sha256": sha256_file(path), "kind": kind,
                               "bytes": path.stat().st_size})

    def finish(self, metrics: dict[str, Any], *, status: str = "COMPLETED",
               notes: str | None = None) -> Path:
        self.record["status"] = status
        self.record["finished_at"] = timing.wall_clock_iso()
        self.record["metrics"] = metrics
        self.record["artefacts"] = self.artefacts
        if notes:
            self.record["notes"] = self.record.get("notes", "") + " " + notes
        return self._write()

    def _write(self) -> Path:
        errs = contract_schema.errors("experiment-log", self.record)
        if errs:
            raise ValueError("run.json would not validate: " + "; ".join(errs))
        path = self.dir / "run.json"
        path.write_text(json.dumps(self.record, indent=2, allow_nan=False), encoding="utf-8")
        return path


__all__ = ["EXPERIMENTS", "ROOT", "RunLog", "environment_block", "git_dirty", "git_sha",
           "hardware_snapshot", "lock_hash", "sha256_file"]
