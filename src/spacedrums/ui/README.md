# spacedrums.ui

**Status:** `guide.py` IMPLEMENTED (Phase 02, prototype quality; tests in `tests/ui/`). Zone display (Phase 04) and the debug overlay/dashboard (Phase 15) are PLANNED.

`draw_guide(frame, roi, band=(y0, y1), instruction, status_lines)` draws the fixed ROI box, the "hands here" band (ROI-normalized y, y down), the instruction "Stand so both hands and sticks stay inside the box" and a capture-stats line in which drops/duplicates/stalls are always visible. `scripts/show_guide.py` runs it live and saves a screenshot.
