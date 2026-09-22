"""Offline replay of the identical causal core and an allowlisted track loader."""

from pathlib import Path

from spacedrums.contracts import TrackState
from spacedrums.contracts import schema as contracts
from spacedrums.features.core import FeatureCore
from spacedrums.timing.logger import read_record_stream


def load_causal_tracks(path, *, session_id=None):
    path = Path(path)
    allowed = {"tracks_causal.jsonl", "TrackState.jsonl"}
    if path.name not in allowed or path.resolve().name not in allowed:
        raise ValueError("only an explicitly named causal TrackState stream is allowed")
    header, rows = read_record_stream(path)
    contracts.validate("record-stream-header", header)
    if header["record_type"] != "TrackState" or header["record_schema_version"] != "1.0":
        raise ValueError("expected causal TrackState stream")
    if session_id is not None and header["session_id"] != session_id:
        raise ValueError("track session mismatch")
    tracks, previous = [], {}
    for row in rows:
        contracts.validate("track-state", row)
        track = TrackState.from_dict(row)
        old = previous.get(track.hand_id)
        if old and (track.frame_id <= old.frame_id or track.t_capture <= old.t_capture):
            raise ValueError("non-monotone causal track")
        previous[track.hand_id] = track
        tracks.append(track)
    return tracks


def build_features(tracks, schema, *, hands=None, sticks=None, frames=None):
    core = FeatureCore(schema)
    hands, sticks, frames = hands or {}, sticks or {}, frames or {}
    return [
        core.update(
            t,
            hand=hands.get((t.frame_id, str(t.hand_id))),
            stick=sticks.get((t.frame_id, str(t.hand_id))),
            frame=frames.get(t.frame_id),
        )
        for t in tracks
    ]
