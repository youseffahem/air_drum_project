# Geometry

**Status:** IMPLEMENTED (Phase 04; empirical layout tuning remains pending).

Deterministic, causal trajectory-to-impact geometry in ROI-normalized, y-down coordinates.
`GeometryEngine.observe` consumes only the previous and current observed point. Predicted paths use
the same segment/surface intersection code and sparse predictions are never silently densified.
