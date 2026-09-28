"""SYNTHETIC/DEV: frame dropping, original timestamps, label separation, prefix causality."""

from dataclasses import replace

import pytest

from spacedrums.ablation.retrack import retrack
from spacedrums.ablation.transforms import drop_frames
from spacedrums.app.synthetic import Swing, build_sequence
from spacedrums.config import load_config
from spacedrums.contracts import HandId
from spacedrums.data.feature_dataset import FeatureSession
from spacedrums.features.normalize import FeatureTable
from spacedrums.features.schema import FeatureSchema
from spacedrums.geometry import ZoneRegistry


@pytest.mark.parametrize("method", ["GEOM", "AXIS_REFINED", "MARKER"])
@pytest.mark.parametrize("factor", [1, 2])
def test_retracking_uses_retained_frames_and_preserves_labels(method, factor):
    cfg = load_config("configs/prototype.candidate.yaml").data
    seq = build_sequence(
        ZoneRegistry.from_config(cfg["zones"]), [Swing(HandId.LEFT, "snare", 0.2)], duration_s=1.5
    )
    frames = [frame for frame, _ in seq]
    observations = {
        f.frame_id: {h: (ho, replace(so, method_id=method)) for h, (ho, so) in obs.items()} for f, obs in seq
    }
    labels = [{"evidence": "SYNTHETIC/DEV", "unchanged_reference_time": 100.42}]
    reference = FeatureSession(
        FeatureTable("SYNTHETIC-ONLY", "synthetic-retrack", "SYNTHETIC", [], []),
        [],
        labels,
        [],
        FeatureSchema(cfg["zones"]),
        {},
        {},
    )
    seen = []

    def perceive(frame):
        seen.append(frame.frame_id)
        return observations[frame.frame_id]

    args = dict(method=method, factor=factor, marker_recorded=method == "MARKER")
    full = retrack(reference, frames, perceive, cfg, **args)
    assert seen == [f.frame_id for f in frames if f.frame_id % factor == 0]
    assert full.labels == labels and full.labels is not labels
    assert [t.t_capture for t in full.tracks[::2]] == [f.t_capture for f in frames[::factor]]
    prefix = retrack(reference, frames[:21], perceive, cfg, **args)
    assert prefix.tracks == [t for t in full.tracks if t.frame_id < 21]
    assert prefix.table.records == [r for r in full.table.records if r.frame_id < 21]
    if factor == 2:
        dt_index = full.schema.names.index("dt")
        assert any(
            r.mask[dt_index] and r.values[dt_index] == pytest.approx(2 / 30) for r in full.table.records
        )
    # Independent negative control: a changed delivered observation changes the suffix.
    for fid in list(observations):
        if fid >= 21:
            observations[fid] = {
                h: (ho, replace(so, tip=(0.9, 0.9)) if so.tip is not None else so)
                for h, (ho, so) in observations[fid].items()
            }
    changed = retrack(reference, frames, perceive, cfg, **args)
    assert changed.tracks[: len(prefix.tracks)] == prefix.tracks
    assert changed.tracks != full.tracks


def test_frame_drop_refuses_upsampling_bad_order_and_marker_without_recording():
    cfg = load_config("configs/prototype.candidate.yaml").data
    seq = build_sequence(ZoneRegistry.from_config(cfg["zones"]), [], duration_s=0.2)
    frames = [f for f, _ in seq]
    for factor in (1, 0, 1.5):
        with pytest.raises(ValueError):
            list(drop_frames(frames, factor=factor, origin_frame_id=0))
    with pytest.raises(ValueError):
        list(drop_frames(list(reversed(frames)), factor=2, origin_frame_id=0))
    with pytest.raises(ValueError, match="recorded marker"):
        retrack(None, [], None, cfg, method="MARKER")
