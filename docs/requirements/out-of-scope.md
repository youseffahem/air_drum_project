# Out-of-Scope Register (V1)

**Phase:** 00 — Task 00.2 · **Status:** PLANNED (policy document)
**Source:** [`../../project-discovery.md`](../../project-discovery.md) § "Important Scope Rules" and the individual answers cited below. Referenced by [`../../phases/README.md`](../../phases/README.md) §12 and by [`rtm.md`](rtm.md) §4.

## 1. Register

Each item is **excluded from V1**. Nothing in this table may be implemented, benchmarked, or claimed without the re-inclusion procedure in §2.

| REQ | Excluded item | Discovery source | What the exclusion means in practice | What the design must still allow |
|---|---|---|---|---|
| REQ-201 | **ESP32** | Q8, Scope Rules | No microcontroller on the sticks or elsewhere in the sensing path. | — |
| REQ-202 | **IMU sensors** | Q8, Scope Rules | No accelerometer/gyroscope on sticks, hands, or body. Kinematics come from vision only. | — |
| REQ-203 | **Electronic stick hardware** | Q7, Q8, Scope Rules | Sticks are ordinary wooden/nylon drumsticks; no batteries, LEDs, wireless links, or active markers. | — |
| REQ-204 | **Multiple users** | Q29, Q51, Scope Rules | One drummer per session. A second person in the background is a *robustness* condition (REQ-029), not a supported user. | Tracker may need to *reject* extra hands robustly (Phase 03/17). |
| REQ-205 | **Full-body tracking** | Q26, Scope Rules | Only hands, sticks, and their surrounding space are tracked. No pose/skeleton model in the pipeline. | ROI definition (Phase 02) may include arms/torso incidentally. |
| REQ-206 | **Mandatory depth estimation** | Q21, Scope Rules | Image-plane 2-D coordinates only (README §7). No stereo, ToF, or monocular-depth models required for operation. | Coordinate contracts (Phase 01) should not hard-code 2-D in a way that prevents an optional depth channel later. |
| REQ-207 | **Foot / Kick tracking** | Q17, Q26, Q55, Scope Rules | No foot detection, no kick zone in V1 zone layouts, no kick sample in the MVP/V1 kit mappings. | **Zone registry must not make a future kick zone impossible** (Q55; Phase 01/04 extensibility rule). |
| REQ-208 | **MIDI as a core requirement** | Q14, Q54, Scope Rules | Audio engine plays local samples directly; no MIDI output/input is required for any acceptance criterion. "MIDI-like velocity" (Q14) refers to a 0–127-style *scale for the intensity proxy*, not a MIDI interface. | Intensity proxy mapping (Phase 04) may be expressed on a velocity-like scale so a future MIDI output is a thin adapter. |
| REQ-209 | **Cloud processing** | Q52, Scope Rules | All capture, tracking, inference, audio, and storage are local. No network calls at runtime; no remote model serving; no cloud storage of recordings. | Phase 23 bundle must run with networking disabled. |
| REQ-210 | **Mandatory visual markers** | Q9, Q30, Scope Rules | Markerless tracking is the primary and default method. The system must be demonstrable and evaluated **without** tape or markers. | Marker-based `TipEstimator` (`MARKER`) may exist as a **fallback** or **benchmark/controlled condition** (REQ-211), always labelled as such. |

### Related "not required" items (not exclusions, but explicitly non-core)

| REQ | Item | Discovery source | Handling |
|---|---|---|---|
| REQ-015 | Articulation types (rim / center / edge) | Q15 | Future work unless it becomes research-relevant; zones only in V1. |
| REQ-056 | User-selectable drum sounds | Q56 | Later UI/config stage; not a research requirement. |
| REQ-020 | Realistic drum-kit visuals | Q20 | Later; must not change the detection/prediction architecture. |
| — | External / iPhone camera | Q22 | Possible later upgrade; V1 development uses the laptop webcam (see `docs/hardware-inventory.md`). |

## 2. Re-inclusion rule

An item in §1 may be brought into scope **only by explicit scope expansion**, which requires all of:

1. A written **ADR** in `docs/decisions/` (next free number) with context, the specific requirement being added, alternatives, and consequences for schedule and evaluation.
2. **Project-owner approval** recorded in that ADR (and supervisor approval where the institution requires it).
3. An **RTM update** (`rtm.md`): the item moves from `REQ-2xx` (type `X`) to a new functional/research requirement with an owning phase and verification method.
4. A statement of which **phase documents change**, and confirmation that already-passed Exit Gates are not invalidated (or a plan to re-run them).

Until all four exist, any code, data, experiment or thesis claim touching the item is a scope violation and is flagged by the integrity checklist (`docs/integrity-checklist.md`, item I-9).

## 3. Grep-able markers

To keep the audit mechanical, code and documents that deliberately touch an excluded area for a *permitted* reason (e.g. the extensibility hook for a kick zone, the marker fallback estimator) must carry the literal tag `OOS-REF:REQ-2xx` in a comment or note, so that `grep -r "OOS-REF"` lists every intentional contact with an out-of-scope item.
