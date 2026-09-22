"""SYNTHETIC in-memory unit fixture for the complete fold exporter. No recording is made.

The four identities below are test grouping keys, never participant pseudonyms or campaign data.
Targets are scripted test values, not annotation or measured ground truth.
"""


from spacedrums.config import config_hash
from spacedrums.contracts import TrackState
from spacedrums.data.feature_dataset import FeatureSession
from spacedrums.data.splits import Roster, build_split
from spacedrums.features.batch import build_features
from spacedrums.features.normalize import FeatureTable
from spacedrums.features.schema import FeatureSchema
from spacedrums.features.streaming import StreamingFeatures


def synthetic_fixture(config):
    schema = FeatureSchema(config["zones"])
    sessions = []
    version = "ds-v0.0-selftest-features"
    for identity in range(4):
        participant, session_id = f"SYNTHETIC-U{identity}", f"synthetic-feature-unit-{identity}"
        tracks, labels = [], []
        t = 100.0
        for i in range(120):
            t += 0.025 + (i % 3) * 0.004
            for hand in ("LEFT", "RIGHT"):
                invalid = 35 <= i <= 37
                tracks.append(
                    TrackState(
                        i,
                        t,
                        hand,
                        "INVALID" if invalid else "VALID",
                        "synthetic-unit-fixture",
                        "GEOM",
                        None if invalid else (0.3 + identity * 0.04, 0.4 + (i % 20) * 0.009),
                        None if invalid else (0.01 * identity, 0.3 + 0.01 * (i % 7)),
                        None if invalid else (0.0, 0.02 * identity),
                        None,
                        None,
                        0.8,
                        1 if invalid else 0,
                        None if invalid else t,
                        None,
                        None,
                    )
                )
        for hand in ("LEFT", "RIGHT"):
            for j, impact in enumerate((100.8, 101.6, 102.4)):
                labels.append(
                    {
                        "session_id": session_id,
                        "participant_id": participant,
                        "source_kind": "SYNTHETIC",
                        "segment_id": "unit-segment",
                        "segment_take": 1,
                        "hand_id": hand,
                        "label_id": f"{session_id}-{hand}-{j}",
                        "label_class": "POSITIVE",
                        "t_impact_est": impact,
                        "t_event": impact,
                        "excluded": False,
                        "zone_id": "snare",
                        "impact_position": [0.4, 0.58],
                        "intensity_proxy_gt": 0.3,
                        "notes": "SCRIPTED SYNTHETIC UNIT TARGET; not human annotation",
                    }
                )
        records = build_features(tracks, schema)
        stream = StreamingFeatures(schema)
        assert records == [stream.update(track) for track in tracks]
        table = FeatureTable(participant, session_id, "SYNTHETIC", records, [True] * len(records))
        sessions.append(
            FeatureSession(
                table,
                tracks,
                labels,
                [
                    {
                        "segment_id": "unit-segment",
                        "take": 1,
                        "t_start": 100.0,
                        "t_end": t + 0.001,
                        "eligible": True,
                    }
                ],
                schema,
                {"bit_identical": True, "records_compared": len(records)},
                {"synthetic_fixture": config_hash([track.to_dict() for track in tracks])},
            )
        )
    roster = Roster(
        version, "labels-v1.0", "SYNTHETIC", {s.table.participant: [s.table.session_id] for s in sessions}
    )
    _, cv = build_split(roster)
    manifest = {
        "dataset_version": version,
        "manifest_hash": config_hash(
            {"fixture": "p08-unit-v1", "inputs": [s.input_hashes for s in sessions]}
        ),
        "kind": "SELFTEST",
    }
    return manifest, cv, sessions
