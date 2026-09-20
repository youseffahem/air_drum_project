# Hardware Inventory

**Phase:** 00 — Task 00.8 · **Status:** template IMPLEMENTED; values below are **inspected** (read from the OS / device metadata), **never measured**. Measured camera behaviour (native FPS, latency, timestamp quality) comes from Phase 02; measured audio output latency from Phase 04. Advertised specs are advertised, not verified.

Every MEASURED value anywhere in the project cites a descriptor id from this file (`HW-NN`) — see `reproducibility-policy.md` §4. Descriptors are append-only: if hardware changes, add `HW-02`, do not edit `HW-01`.

## HW-01 — Development laptop (primary target CPU)

| Field | Value | Inspected on | Method |
|---|---|---|---|
| Laptop model | Dell Inc. Precision 3520 | 2026-09-20 | `Win32_ComputerSystem` |
| CPU model | Intel Core i7-7820HQ @ 2.90 GHz (Kaby Lake, 4C/8T) | 2026-09-20 | `Win32_Processor` |
| Cores | 4 physical / 8 logical | 2026-09-20 | `Win32_Processor` |
| Base / boost clocks | 2.90 GHz base (advertised, from CPU name string); boost **not inspected** (spec sheet says up to 3.9 GHz — *advertised, unverified*) | 2026-09-20 | CPU name string |
| RAM | 15.9 GiB total physical | 2026-09-20 | `Win32_ComputerSystem` |
| OS build | Windows 11 Pro, version 10.0.22621 (build 22621) | 2026-09-20 | `Win32_OperatingSystem` |
| GPU(s) (record only; project is CPU-first, GPU not used) | Intel HD Graphics 630 (iGPU); NVIDIA Quadro M620 (dGPU); SuperDisplay Virtual Adapter (virtual) | 2026-09-20 | `Win32_VideoController` |
| Python used for HW-01 runs | CPython 3.11.9 in `.venv` (see `environment.md`) | 2026-09-20 | `env_smoke.py` |
| Power profile during benchmarks | **To be recorded per run** (plugged-in vs battery, Windows power mode) — affects clocks | — | — |
| Thermal note | Laptop; sustained CPU load may throttle. Phase 16 must record run duration and check for throttling. | — | — |

## Integrated webcam (belongs to HW-01)

| Field | Value | Inspected on | Method |
|---|---|---|---|
| Device name | "Integrated Webcam" | 2026-09-20 | `Get-PnpDevice` (class Camera) |
| USB VID:PID | `0C45:6717` (Sonix/Microdia controller, common in Dell integrated cameras) | 2026-09-20 | PnP instance id |
| Driver / version | **not yet inspected** — record from Device Manager before Phase 02 | — | — |
| Advertised resolutions / FPS modes | **not yet inspected** — Phase 02 enumerates modes via the capture backend and records them as *advertised by driver*; measured FPS is separate | — | — |
| Physical placement | Bezel above display; height/angle depend on laptop position → Phase 02 camera profile records placement | — | — |
| Expectation (not a measurement) | Typical Dell integrated cameras of this generation advertise 720p @ 30 FPS. **60 FPS native is unlikely from this device**; the Q23 60-FPS target probably needs an external camera. To be confirmed by Phase 02 measurement. | — | — |

## Audio (belongs to HW-01)

| Field | Value | Inspected on | Method |
|---|---|---|---|
| Audio codec / driver | Realtek Audio | 2026-09-20 | `Win32_SoundDevice` |
| Output endpoint | "Speakers / Headphones (Realtek Audio)" | 2026-09-20 | `Get-PnpDevice` (AudioEndpoint) |
| Other output devices present | Intel Display Audio (HDMI/DP); NVIDIA Virtual Audio Device (virtual — **do not use for latency work**) | 2026-09-20 | `Win32_SoundDevice` |
| Input endpoint | "Microphone Array (Realtek Audio)" — built-in; candidate for the pad+mic condition only if an external mic is unavailable (placement near the pad is impossible with a built-in array) | 2026-09-20 | `Get-PnpDevice` |
| Host APIs available to PortAudio | **not yet inspected** — Phase 04 lists them via `sounddevice.query_hostapis()` and picks one by measured latency | — | — |
| External audio interface | none known | — | — |

## Peripherals and consumables

| Item | Status | Notes |
|---|---|---|
| Tripod / camera mount | **Open Question** — not inventoried. Required by REQ-024 for an external camera; the integrated webcam is "fixed" by placing the laptop on a stable surface. | Owner to confirm availability before Phase 02. |
| Ordinary drumsticks (2) | **Open Question** — not inventoried. Record brand/size/colour/tip material (wood vs nylon) when available; matters for markerless detection (Phase 03). | |
| Practice pad (optional pad+mic condition, ADR-0002) | **Open Question** — not inventoried. | |
| External microphone (pad+mic condition) | **Open Question** — not inventoried. | |
| Coloured tape (fallback / benchmark condition only, REQ-211) | **Open Question** — not inventoried. | |
| External camera candidates | none inventoried. If acquired, add as `HW-02` with **advertised** specs only (resolution, FPS modes, interface, global vs rolling shutter, latency claims) and let Phase 02 measure. iPhone camera (Q22) would need a capture path (e.g. Continuity Camera is not available on Windows) — `Pending Architecture Decision` if pursued. | |

## Second machine (clean-install verification, `environment.md` §6)

| Field | Value |
|---|---|
| HW-02 | **not yet available** — required for the clean-environment checklist item and for the "second hardware" tolerance rows. |
