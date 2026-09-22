"""Offline target-only transforms. No target is passed to the feature core."""

import numpy as np


def trajectory_target(tracks, anchor, k, segment_keys):
    absolute = np.zeros((k, 2))
    displacement = np.zeros((k, 2))
    mask = np.zeros(k, dtype=bool)
    offsets = np.zeros(k)
    base = tracks[anchor]
    continuous = base.tip_filtered is not None
    for j in range(k):
        at = anchor + j + 1
        if at >= len(tracks):
            break
        t = tracks[at]
        offsets[j] = t.t_capture - base.t_capture
        continuous = continuous and t.reset_reason is None and t.tip_filtered is not None
        if continuous and segment_keys[at] == segment_keys[anchor] and segment_keys[at] is not None:
            absolute[j] = t.tip_filtered
            displacement[j] = np.asarray(t.tip_filtered) - base.tip_filtered
            mask[j] = True
    return displacement, absolute, mask, offsets


def auxiliary_target(labels, *, t, hand_id, session_id, segment_id, segment_take, end, h, h_max):
    # Never treat an unobserved or ambiguous horizon as a confident negative.
    selected = [
        r
        for r in labels
        if r["hand_id"] == hand_id
        and r["session_id"] == session_id
        and r["segment_id"] == segment_id
        and r["segment_take"] == segment_take
        and r.get("qc_status") != "REJECTED"
    ]
    ambiguous = False
    for r in selected:
        if r["label_class"] not in ("AMBIGUOUS", "EXCLUDED") and not r.get("excluded", False):
            continue
        lo = r.get("t_start") if r.get("t_start") is not None else r.get("t_event")
        hi = r.get("t_end") if r.get("t_end") is not None else r.get("t_event")
        if lo is not None and hi >= t and lo <= t + h_max:
            ambiguous = True
    positives = sorted(
        (
            r
            for r in selected
            if r["label_class"] == "POSITIVE"
            and not r.get("excluded", False)
            and r.get("t_impact_est") is not None
            and t < r["t_impact_est"] <= min(t + h_max, end)
        ),
        key=lambda r: r["t_impact_est"],
    )
    nxt = positives[0] if positives else None
    dt = nxt["t_impact_est"] - t if nxt else None
    within = bool(dt is not None and dt <= h)
    strike_mask = not ambiguous and (within or t + h <= end)
    tti_mask = nxt is not None and not ambiguous
    return {
        "strike_within_H": int(within) if strike_mask else 0,
        "strike_mask": strike_mask,
        "tti": dt if tti_mask else 0.0,
        "tti_mask": tti_mask,
        "zone_id": nxt["zone_id"] if tti_mask else None,
        "impact_pos": nxt["impact_position"] if tti_mask else [0.0, 0.0],
        "intensity": nxt["intensity_proxy_gt"] if tti_mask else 0.0,
        "impact_mask": tti_mask,
        "ambiguous": ambiguous,
    }
