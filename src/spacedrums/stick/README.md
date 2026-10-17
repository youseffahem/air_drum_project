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
| `red_tip.py` | ADR-0046 | red painted tips (`app.play --red-tips`): `RedTipSettings` for both detectors (`detector: redness` default, `colour`); the colour detector: one HSV pass over both sides of the hue wrap; seed/growth hysteresis (paint-core seeds, opened; growth only near seeds; reflections bridge only inside the paint's hull); colour-share (`OFF_COLOUR`), area and elongation rejects with counted reasons; the **cap point** (centre of the more saturated end of a long region, so a paint run on the shaft never moves it); weak-floor re-detection of blur streaks inside a track gate. **A MARKER condition** |
| `red_tip_caps.py` | ADR-0046 (rev. 3) | the default `redness` detector: difference-of-Gaussians blobs of `min(R-G, R-B+12)` at half resolution, each grown into its region (level raised until it closes), the cap point at the centre of the region's largest inscribed circle (the ball, not the painted neck or a highlight), candidates on one red structure merged (`SAME_CAP`), and `CapVerifier`, a logistic cap score over region features (refit with `analyze_red_tips.py fit-verifier`) |
| `red_tip_evidence.py` | ADR-0046 (rev. 3) | two tips for the `redness` detector: Hungarian association, evidence = running average of the verifier quality, slots by evidence (static objects lose rank, a moving tip displaces a never-moved one, challenges, takeover of coasting slots, identity memory for a returning tip), LOW_EVIDENCE / AMBIGUOUS / CLIPPED / PREDICTED never measured, slots re-resolved after an ambiguous merge |
| `red_tip_tracker.py` | ADR-0046 | two tips for the `colour` detector: joint (Hungarian) association with bounded prediction used for gating only, two-frame birth, coasting, LEFT/RIGHT slots, adoption after a lost streak, ambiguity flags and identity resets, slot release by red objects that never move, eviction of idle low-score clutter at the track limit, no binding among more red candidates than slots until one moves; `SlotState` / `TrackerFrame` shared with `red_tip_evidence.py` |
| `red_tip_estimator.py` | ADR-0046 | `MARKER` `StickObservation` + `EndpointEvidence` per hand from one pass per frame through the configured detector and tracker; a prediction never carries coordinates; per-frame diagnostics and session stats |
| `red_tip_synthetic.py` | ADR-0046 | SYNTHETIC glossy red-tip renderer (blur, reflections, occluders, distractors; `draw_stick`: wooden shaft and mottled paint run; `REAL_CAP`: the owner photo's cap size) for tests and offline self-checks |

`tip_confidence ≤ handedness_score` for every method (ambiguous identity ⇒ DEGRADED downstream). Evidence: `docs/reports/phase-03-tip-benchmark.md`. Tests: `tests/stick/` (`TEST-STICK-1/2`, `TEST-CONFORM-1`). Scripts: `scripts/benchmark_tip_methods.py`, `tools/annotate_tip.py`.
