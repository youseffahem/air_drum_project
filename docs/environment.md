# Environment Specification

**Phase:** 00 — Task 00.3 · **Status:** IMPLEMENTED (environment only — a smoke import passed on the development machine; see §6). No project research quantity is measured by this document.
**Inputs:** [`../phases/README.md`](../phases/README.md) §11 (candidate stack), owner decision *Python-first* ([ADR-0001](decisions/ADR-0001-python-first-stack.md)).

## 1. Decisions

| Item | Decision | Why | Alternatives kept on record |
|---|---|---|---|
| Language | **Python** (CPython) | ADR-0001. Fast iteration for CV/ML research; every candidate library ships CPU wheels. | C++/Rust for a hot path only if Phase 16 profiling proves Python is the bottleneck (would need an ADR). |
| Python version | **3.11.x** (3.11.9 used for the first lock) | Oldest version still receiving fixes that has **binary wheels for every candidate** on Windows, including `mediapipe` and `torch`. 3.12 and 3.13 are also installed on the dev machine but were **not** verified. | 3.12 (re-verify wheels for `mediapipe`, `lightgbm`, `sounddevice` before switching). **Open Question:** final minor version is frozen at the Phase 01 gate. |
| Environment tool | `venv` + `pip` (standard library) | No extra tooling on a clean machine; sufficient for a single-developer project. | `uv` (faster resolver, same lock semantics) — may be adopted with a note in this file; `conda` rejected (mixes non-PyPI builds, harder to hash). |
| Lock strategy | `requirements.in` (intent, loose pins) → `requirements.lock` (`pip freeze` of a clean venv, exact `==` pins, includes the torch CPU index) | Exact reproducibility of the interpreter's package set; the lock's SHA-256 goes into every experiment-log record (`environment.lock_hash`). | `pip-tools` (`pip-compile`) if hash-pinned (`--generate-hashes`) locks are wanted before the dataset phases. |
| Accelerator | **CPU only** (`torch==*+cpu`, `onnxruntime` CPU provider) | Project is CPU-first (README §11). The dev laptop has an NVIDIA Quadro M620 and Intel HD 630 (see `hardware-inventory.md`), but **no GPU is assumed** for training or inference; GPU use would need an ADR and must never be used for latency claims. | — |
| OS | Windows 11 (development machine). | Hardware available. | A second OS is **not** covered by `requirements.lock` (see Open Question in §8). |

## 2. Dependency table

Versions are what `pip` resolved on **2026-09-20** into a clean `venv` from `requirements.in`; they are pinned in `requirements.lock`. Licences were read from each wheel's metadata (`importlib.metadata`) on the same date. "Benchmark phase" = the phase whose measurement decides whether the candidate stays.

| Concern | Candidate (import) | Resolved version | Licence (from metadata) | CPU support | Known Windows constraints / notes | Benchmark / decision phase |
|---|---|---|---|---|---|---|
| Numerics | `numpy` | 2.4.6 | BSD-3-Clause (+ 0BSD/MIT/Zlib/CC0 components) | yes | — | — |
| Numerics | `scipy` | 1.17.1 | BSD | yes | — | — |
| Camera capture, drawing | `opencv-python` (`cv2`) | 5.0.0.93 | Apache-2.0 (wheel bundles FFmpeg, LGPL) | yes | Backend selection matters: `CAP_DSHOW` vs `CAP_MSMF` differ in timestamp availability and FPS negotiation. Driver timestamps may be unreliable → README §11 alternative (`pyav`/`imageio-ffmpeg`) if Phase 02 shows it. | **02** (native FPS, timestamp mapping) — `Pending Benchmark` |
| Hand landmarks | `mediapipe` | 1.0.1 | Apache-2.0 | yes (CPU delegate) | Windows wheels historically lag Python releases; this is the main reason for pinning 3.11. Hand Landmarker task requires a `.task` model file to be downloaded once and stored locally (offline rule REQ-052/209: bundle it, hash it). Verbose glog/absl output on import (cosmetic). | **03** (landmark latency / accuracy) — `Pending Benchmark` |
| Stick detection | classical CV via `cv2` + `numpy` first | (as above) | — | yes | — | **03** — `Pending Benchmark` (learned segmentation only if classical fails) |
| Training | `torch` | 2.14.0+cpu | BSD-3-style (multi-component) | yes (CPU build; `cuda.is_available() == False` confirmed) | Must install from the PyTorch CPU index (`--extra-index-url https://download.pytorch.org/whl/cpu`) to avoid a CUDA wheel. Set `torch.set_num_threads` explicitly in benchmarks and record it. | 10 (model training) |
| Inference runtime | `onnxruntime` | 1.30.0 | MIT | yes (`CPUExecutionProvider`) | Also reports `AzureExecutionProvider` — **must not be used** (REQ-209 cloud exclusion). Thread count must be pinned per benchmark. | **13** (ONNX vs TorchScript vs eager) — `Pending Benchmark` |
| GBDT baseline | `lightgbm` | 4.7.0 | MIT | yes | Needs the MSVC runtime (present on Windows 10/11). | 09 (C-GBDT) — XGBoost / sklearn `HistGradientBoosting` remain alternatives |
| Audio output | `sounddevice` (PortAudio) | 0.5.6 | MIT (PortAudio: MIT) | yes | Host API choice matters for latency: **WASAPI (exclusive/shared)** vs MME vs DirectSound; ASIO only with a vendor driver. Callback-driven streaming required; block size tunable. | **04** (measured audio output latency) — `Pending Architecture Decision` if unacceptable |
| Sample loading | `soundfile` (libsndfile) | 0.14.0 | BSD-3 (libsndfile: LGPL) | yes | — | 04 |
| Config validation | `pydantic` | 2.13.5 | MIT | yes | — | 01 (config schema) |
| Config files | `PyYAML` | 6.0.3 | MIT | yes | Always `safe_load`. | 01 |
| JSON schemas | `jsonschema` | 4.26.0 | MIT | yes | Used for `schemas/experiment-log.schema.json`. | 00 (this phase) |
| Tests | `pytest` | 9.1.1 | MIT | yes | — | all |
| Lint / format | `ruff` | 0.16.8 | MIT | yes | dev-only | all |
| Import-layer linting *(added Phase 02)* | `import-linter` (`lint-imports`) | 2.15 (+ `grimp` 3.17, `click`, `rich`, `markdown-it-py`, `mdurl`) | BSD-2-Clause | yes | dev-only; runs the `.importlinter` contract in `tests/architecture/` (architecture.md section 2.4; Phase 01 follow-up F-3) | 02+ |

Not yet chosen (deliberately): plotting library for thesis figures (Phase 21 may pick `matplotlib`); UI toolkit beyond OpenCV windows (`Pending Architecture Decision`, Phase 15); experiment tracker beyond file manifests (`Pending Architecture Decision`, see `reproducibility-policy.md` §7).

## 3. Files

| File | Role |
|---|---|
| [`../requirements.in`](../requirements.in) | Human-edited list of direct dependencies with loose lower bounds and the CPU torch index. **Edit this** to add/remove a library. |
| [`../requirements.lock`](../requirements.lock) | Machine-generated exact pin set (`pip freeze`) from a clean venv. **Never hand-edit.** Regenerate with the procedure in §5 and record the new SHA-256 in §6. |
| [`../scripts/env_smoke.py`](../scripts/env_smoke.py) | Imports every candidate, prints versions, and runs the experiment-log schema test. The only source code permitted in Phase 00. |

## 4. Recreating the environment (clean machine, Windows)

```powershell
# 1. Install CPython 3.11.x (64-bit) from python.org; tick "py launcher".
# 2. From the repository root:
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e . --no-deps   # (Phase 02) the spacedrums package itself, editable
# 3. Verify:
.\.venv\Scripts\python.exe scripts\env_smoke.py     # must print RESULT: PASS
.\.venv\Scripts\python.exe -m pytest                 # (Phase 02) all suites must pass
```

Linux/macOS: same steps with `python3.11 -m venv .venv` and `.venv/bin/python`. **Not verified** — see §8.

## 5. Updating the lock

1. Edit `requirements.in`.
2. Delete `.venv`, recreate it per §4 step 2 but install from `requirements.in` instead of the lock.
3. `python -m pip freeze` → replace the body of `requirements.lock` below the header block; update the header date.
4. Run `scripts/env_smoke.py`; it must pass.
5. Record the new lock SHA-256 in §6 with the date, and note the change in `docs/decisions/` if a *candidate* (not just a version) changed.

Rule: experiment-log records carry `environment.lock_hash`; two runs are only comparable as a VALIDATED pair if their `lock_hash` is identical (see `reproducibility-policy.md` §6).

## 6. Verification record

| Date | Machine | Python | Lock SHA-256 | Smoke result | Verified by |
|---|---|---|---|---|---|
| 2026-09-20 | HW-01 (dev laptop, see `hardware-inventory.md`) | 3.11.9 | `f92a60c6dfcf036ddf2e28efcc2dd0aa68f8f57f1c9d95e82f87c1fe6aae86a8` | PASS (13/13 imports; schema accept + reject) | Claude (assistant), clean `venv` on the dev machine |
| 2026-09-21 | HW-01 | 3.11.9 | `1d6191320186c79f6221fb1238b1840f3dfb22f3a791ef5d9b579259e01c1eaa` | PASS (`env_smoke.py`; `pytest` all suites) | Claude (assistant), Phase 02: lock regenerated after `pip install import-linter` into the **existing** venv + `pip freeze --exclude-editable` (not from a deleted/recreated venv — §5 step 2 was not repeated; every previously pinned version is byte-identical, only the six import-linter packages were added). A clean regeneration remains part of the pending clean-machine row. |
| *pending* | second machine or clean VM | — | — | — | **Checklist item, not assumed** — required before any VALIDATED status (Acceptance Criterion 2 is met on the dev machine only). |

Note on the first verification: the venv was created fresh, but the *machine* was not clean (other Python versions and tools are installed). A true clean-machine verification is the pending row above.

## 7. Conventions all later phases must follow

- **Target-CPU naming:** every latency/FPS measurement names the hardware descriptor id (`HW-xx` from `hardware-inventory.md`) and the thread settings (`torch`, `onnxruntime`, OpenCV `cv2.setNumThreads`). "On the target CPU" without an `HW-xx` id is not a measurement.
- **No network at runtime:** any model or asset (e.g. the MediaPipe `.task` file) is downloaded once by a documented script, stored under `models/` or `assets/` with a SHA-256 in a manifest, and loaded from disk.
- **Thread pinning in benchmarks:** record `OMP_NUM_THREADS`, `torch.get_num_threads()`, and ORT `intra_op_num_threads` in the run's environment block.
- **Warnings:** MediaPipe/absl log noise on import is cosmetic; do not suppress warnings globally in project code.

## 8. Open Questions (carried in the Phase 00 gate record)

- **OQ-ENV-1:** Final Python minor version (3.11 vs 3.12). Decide at the Phase 01 gate after checking wheel availability for the exact `mediapipe` release that Phase 03 benchmarks.
- **OQ-ENV-2:** Can one `requirements.lock` cover Windows and a second OS? `pip freeze` output is platform-specific (e.g. `pywin32`-style transitive deps may appear). Candidate answer: keep one lock per platform (`requirements.win.lock`, `requirements.linux.lock`) only if a second OS is actually used; otherwise Windows-only is acceptable for the thesis, stated as a limitation.
- **OQ-ENV-3:** Whether to move to `pip-tools` hash-pinned locks before Phase 06 (dataset phases) for stronger supply-chain reproducibility.
