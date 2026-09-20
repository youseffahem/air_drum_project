# ADR-0005 — ROI-normalized, y-down, 2-D coordinate convention

| Field | Value |
|---|---|
| Status | **Accepted** (Phase 01, Task 01.2 / 01.10) |
| Date | 2026-09-20 |
| Deciders | Project owner (Q21; roadmap README §7), recorded by Phase 01 |
| Related | `phases/README.md` §7; `docs/architecture/architecture.md` §9; `schemas/common.schema.json` (`point2`, `rect_px`, `rect_norm`); `docs/requirements/out-of-scope.md` REQ-206 note; REQ-021, REQ-036/037 |

## Context

Zone geometry, tracking, features, prediction, labels and metrics all need one spatial frame. The playing area is a fixed ROI inside the camera frame (Q19, Q26); the camera and resolution may change between sessions (Q22). Hand-landmark libraries use their own normalised image coordinates; "downward" (Q37) must have a fixed meaning. Depth is excluded from V1 (Q21) but the out-of-scope register asks that contracts do not make an optional depth channel impossible later.

## Decision

1. All positions in records are **ROI-normalized**: `x = (x_px − roi.x) / roi.w`, `y = (y_px − roi.y) / roi.h`, origin at the ROI's top-left, **y increasing downward**. Nominal range `[0,1]²`; values outside are legal and mean "outside the ROI" (a stick tip often is).
2. Velocities are ROI-normalized units per second; accelerations per second²; angles in radians from `+x` towards `+y`.
3. "Downward/inward" is expressed per zone by an explicit `inward_normal` (Phase 04); for a drum-like zone the impact surface is its upper boundary with normal `[0, 1]`. Nothing hard-codes "down".
4. `point2` has **exactly two components** in schema 1.x. A depth channel, if ever justified by experiment, is a schema-version bump adding an explicit third component or a separate field — not an overload of `point2`.
5. The `hands` module converts library coordinates to this frame at its boundary; no other module sees library coordinates. Pixel-space values are reported only alongside the ROI size and camera profile.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Full-frame normalized coordinates | Zone layouts and features would depend on the ROI's position in the frame; changing camera framing would invalidate configs and datasets. |
| Pixel coordinates | Not comparable across resolutions/cameras (Q22); every consumer would need the frame size. |
| y-up (mathematical) convention | Contradicts image libraries and would make "downward" `−y`, a standing source of sign bugs. |
| Aspect-ratio-preserving normalization (single scale) | Simpler velocities but ROI edges would not map to `[0,1]`; the ROI aspect ratio is recorded in `roi_px` so metric reporting can be derived anyway. |

## Consequences

- Velocities are anisotropic when the ROI is not square; any metric that needs isotropic units converts with `roi_px` (Phase 09 reports ADE/FDE in both normalized units and pixels).
- Changing the ROI invalidates derived records; raw video is authoritative and derived records are regenerated (architecture.md §12.3), which is the intended path.
- A capture helper `px_to_norm`/`norm_to_px` (Phase 02, Task 02.6) is the single implementation of the mapping and is unit-tested for orientation.
