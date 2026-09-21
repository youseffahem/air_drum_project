# spacedrums.stick

**Status:** IMPLEMENTED (Phase 03, Tasks 03.4–03.9; ADR-0015). Primary markerless method **provisionally `GEOM`** (the annotated tip-error benchmark is PENDING). Layer L2; imports L0, `capture` (ROI helper) and `hands` (grip).

| Module | Task | Content |
|---|---|---|
| `search_region.py` | 03.4 | rotated rectangle from the grip along the direction prior, scaled by the hand span; ROI clipping; debug polygon + mask |
| `segment.py` | 03.5 | Canny → closing → connected components → elongation + orientation gates; per-component reject reasons |
| `axis.py` | 03.6 | PCA / RANSAC (through the grip) / HOUGH; span-relative inlier band; grip-proximity gate; connected support; deterministic |
| `estimator.py` | 03.C | shared per-frame analysis, settings (`stick` config block), `make_tip_estimator(method_id)` factory |
| `tip_geom.py` | 03.7 | `GEOM`: tip = grip + L·axis_dir (L in ROI-height units) |
| `tip_axis_refined.py` | 03.8 | `AXIS_REFINED`: connected-support endpoint gated vs GEOM; GEOM fallback (counted) |
| `tip_marker.py` | 03.9 | `MARKER`: HSV blob — **fallback / benchmark only**, WARNING logged, labelled everywhere (REQ-211, I-7) |

`tip_confidence ≤ handedness_score` for every method (ambiguous identity ⇒ DEGRADED downstream). Evidence: `docs/reports/phase-03-tip-benchmark.md`. Tests: `tests/stick/` (`TEST-STICK-1/2`, `TEST-CONFORM-1`). Scripts: `scripts/benchmark_tip_methods.py`, `tools/annotate_tip.py`.
