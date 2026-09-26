# spacedrums.ui

**Phase 14:** `wizard_views.py` IMPLEMENTED: `draw_wizard(frame, roi, WizardView)` draws the Calibration
Wizard screens (stand-here box and band, zones with the cued/selected zone highlighted, reach envelope,
step header, progress bar, key hints) from plain data built by `spacedrums.app.calibrate`; `ui` never
imports `calib` (independent L7 siblings). Tests: `tests/ui/test_ui_wizard_views.py`.

**Status:** `guide.py` IMPLEMENTED (Phase 02, prototype quality; tests in `tests/ui/`); `overlay.py` minimal debug overlay IMPLEMENTED (Phase 03, Task 03.15: landmarks, grip + prior, search region, candidates, axis, tip coloured by method with the MARKER fallback/benchmark tag, filtered tip + velocity, per-hand status; exercised by `scripts/benchmark_tip_methods.py`). Zone display (Phase 04) and the full dashboard (Phase 15) are PLANNED.

`draw_guide(frame, roi, band=(y0, y1), instruction, status_lines)` draws the fixed ROI box, the "hands here" band (ROI-normalized y, y down), the instruction "Stand so both hands and sticks stay inside the box" and a capture-stats line in which drops/duplicates/stalls are always visible. `scripts/show_guide.py` runs it live and saves a screenshot.
