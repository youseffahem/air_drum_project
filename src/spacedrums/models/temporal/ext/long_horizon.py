"""E1 longer horizons: K beyond the Phase 10 grid and a two-rate output grid.

Targets are read on the dense uniform grid up to the largest declared step with the unchanged
Phase 10 ``fixed_grid`` (contiguous observed spans only, no extrapolation); a two-rate grid is a
subset of those columns, so no new interpolation exists. The prediction is emitted with explicit
``t_offsets_s`` and geometry intersects the polyline as given (contracts.md section 3.6).
"""

import numpy as np


def grid_columns(config):
    """Column indices of the declared output steps in the dense 1..max_step target grid."""
    return [step - 1 for step in config.grid_steps]


def select_grid(sample, config):
    """Restrict a loaded sample's fixed-grid targets to the declared output steps (in place)."""
    t = sample["tensors"]
    if t["target"].shape[1] != config.max_step:
        raise ValueError("targets must be read on the dense grid up to the largest declared step")
    if not config.uniform:
        columns = grid_columns(config)
        t["target"], t["target_mask"] = t["target"][:, columns], t["target_mask"][:, columns]
    sample["grid_steps"] = list(config.grid_steps)
    sample["offsets_s"] = list(config.offsets_s)
    return sample


def error_by_offset(predicted, sample):
    """Mean displacement error per output time; the horizon-growth table of Task 12.3."""
    t = sample["tensors"]
    distance = np.linalg.norm(np.asarray(predicted) - t["target"].numpy(), axis=-1)
    mask = t["target_mask"].numpy()
    return [
        {
            "offset_s": offset,
            "n": int(mask[:, j].sum()),
            "error": float(distance[:, j][mask[:, j]].mean()) if mask[:, j].any() else None,
        }
        for j, offset in enumerate(sample["offsets_s"])
    ]
