"""Frame-drop/tip-method preparation seam. Labels are never passed to perception or tracking."""

from copy import deepcopy

from spacedrums.config import config_hash
from spacedrums.contracts import HandId
from spacedrums.data.feature_dataset import FeatureSession
from spacedrums.features.core import FeatureCore
from spacedrums.features.normalize import FeatureTable
from spacedrums.tracking import CausalTracker, TrackerSettings

from .transforms import drop_frames


def retrack(reference, frames, perceive, cfg, *, method, factor=1, origin_frame_id=0, marker_recorded=False):
    """Rebuild causal tracks/features from retained raw frames with an injected perception stack.

    ``perceive(frame)`` returns the existing per-hand HandObservation/StickObservation pair.
    The producer must be fresh for each call/session (including a fresh hand landmarker).
    Native-rate evidence is a separate prerequisite; this function makes no FPS claim.
    """
    if method not in ("GEOM", "AXIS_REFINED", "MARKER"):
        raise ValueError("unknown tip method")
    if method == "MARKER" and not marker_recorded:
        raise ValueError("MARKER requires a recorded marker block; benchmark condition only")
    if type(factor) is not int or factor < 1:
        raise ValueError("frame-drop factor must be an integer >= 1")
    source = frames if factor == 1 else drop_frames(frames, factor=factor, origin_frame_id=origin_frame_id)
    trackers = {h: CausalTracker(h, TrackerSettings.from_config(cfg)) for h in HandId}
    core, tracks, records, delivered = FeatureCore(reference.schema), [], [], []
    previous = None
    eligibility = {
        (r.frame_id, r.hand_id): ok
        for r, ok in zip(reference.table.records, reference.table.eligible, strict=True)
    }
    eligible = []
    for frame in source:
        if previous and (frame.frame_id <= previous.frame_id or frame.t_capture <= previous.t_capture):
            raise ValueError("nonmonotone raw recording")
        previous = frame
        observations = perceive(frame)
        delivered.append((frame.frame_id, frame.t_capture))
        for hand in HandId:
            hand_obs, stick = observations[hand]
            for obs in (hand_obs, stick):
                if (obs.frame_id, obs.t_capture, obs.hand_id) != (frame.frame_id, frame.t_capture, hand):
                    raise ValueError("perception must use only the current retained frame")
            if str(stick.method_id) != method:
                raise ValueError("tip producer differs from the declared ablation method")
            track = trackers[hand].update(hand_obs, stick, frame.t_capture)
            tracks.append(track)
            records.append(core.update(track, hand=hand_obs, stick=stick, frame=frame))
            eligible.append(eligibility.get((frame.frame_id, str(hand)), False))
    hashes = {
        **reference.input_hashes,
        "ablation_retrack": config_hash(
            {
                "method": method,
                "factor": factor,
                "origin": origin_frame_id,
                "delivered": delivered,
                "config": cfg,
                "labels_unchanged": config_hash(reference.labels),
            }
        ),
    }
    return FeatureSession(
        FeatureTable(
            reference.table.participant,
            reference.table.session_id,
            reference.table.source_kind,
            records,
            eligible,
        ),
        tracks,
        deepcopy(reference.labels),
        deepcopy(reference.segments),
        reference.schema,
        {
            "status": "REQUIRES paired raw replay verification",
            "method": method,
            "condition": "MARKER benchmark" if method == "MARKER" else method,
        },
        hashes,
    )
