"""Phase 11 invariant: no CommittedStrike without a geometry-derived candidate (ADR-0007).

The no-trajectory diagnostic runs only in an explicitly flagged harness mode that the live
application refuses. Heads may gate or relabel a geometry candidate; they never create one.
"""

import re
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from mt_helpers import controlled, manifest, mt_config, track

from spacedrums.commit import CommitSettings
from spacedrums.config import load_config
from spacedrums.contracts import Anticipator, CandidateDerivation, StrikeCandidate
from spacedrums.contracts.schema import validate
from spacedrums.eval.replay import replay
from spacedrums.features.batch import build_features
from spacedrums.features.schema import FeatureSchema
from spacedrums.geometry import ZoneRegistry
from spacedrums.models.temporal.config import TASKS
from spacedrums.models.temporal.consistency import AuxGate, AuxHeadSettings
from spacedrums.models.temporal.mt_adapter import DirectHeadDiagnostic, MultiTaskAnticipator

ROOT = Path(__file__).resolve().parents[2]
CFG = load_config(ROOT / "configs/prototype.candidate.yaml")
REGISTRY = ZoneRegistry.from_config(CFG["zones"])
SCHEMA = FeatureSchema(CFG["zones"])


def run(tracks, model, *, gate="default", diagnostic=False, heads=TASKS, p_commit=0.5):
    if gate == "default":
        gate = AuxGate(AuxHeadSettings(), heads)
    return replay(
        tracks,
        arm="MODEL:C-MT",
        registry=REGISTRY,
        commit_settings=replace(CommitSettings.from_config(CFG), p_commit=p_commit, n_confirm_frames=0),
        v_min=0.15,
        session_id="synthetic-mt-invariant",
        model=model,
        feature_schema=SCHEMA,
        feature_window_n=2,
        feature_records=build_features(tracks, SCHEMA),
        candidate_gate=gate,
        diagnostic_direct=diagnostic,
    )


@pytest.mark.parametrize("family", ["gru", "tcn"])
@pytest.mark.parametrize("crossing", [False, True])
def test_heads_cannot_create_strikes_and_every_commit_is_geometry(family, crossing):
    config = mt_config(family)
    # Heads shout "strike on the snare in 30 ms" at every frame, whatever the trajectory does.
    adapter = MultiTaskAnticipator(controlled(config, crossing=crossing), manifest(config))
    assert isinstance(adapter, Anticipator)
    tracks = [track(i, 0.505 + i * 0.02) for i in range(8)]
    result = run(tracks, adapter)
    assert bool(result.candidates) == crossing and bool(result.committed) == crossing
    ids = {c.candidate_id for c in result.candidates}
    for c in result.candidates:
        validate("strike-candidate", c.to_dict())
        assert c.derivation is CandidateDerivation.GEOMETRY and c.strike_probability is None
        assert re.fullmatch(r"synthetic-mt-invariant-LEFT-c\d{6}", c.candidate_id)  # geometry engine ids
    for s in result.committed:
        validate("committed-strike", s.to_dict())
        assert s.derivation is CandidateDerivation.GEOMETRY and s.arm == "C-MT" and s.candidate_id in ids
    for p in result.predictions:
        validate("trajectory-prediction", p.to_dict())
        assert (
            p.aux.strike_prob_within_H > 0.99 and p.aux.zone_ids[int(np.argmax(p.aux.zone_logits))] == "snare"
        )
        assert (p.aux.consistency_flags is not None) == any(
            c.frame_id == p.frame_id for c in result.candidates
        )
    if crossing:  # future frames cannot change earlier commits
        changed = tracks[:4] + [track(i, 0.4) for i in range(4, 8)]
        future = run(changed, MultiTaskAnticipator(controlled(config), manifest(config)))
        early = [s.to_dict() for s in result.committed if s.frame_id < 4]
        assert early == [s.to_dict() for s in future.committed if s.frame_id < 4]


def test_probability_gate_can_only_remove_geometry_candidates():
    config = mt_config("gru")
    tracks = [track(i, 0.505 + i * 0.02) for i in range(8)]
    quiet = MultiTaskAnticipator(controlled(config, p_logit=-10.0), manifest(config))
    gated = run(tracks, quiet, gate=AuxGate(AuxHeadSettings(use_p_aux=True, p_aux=0.5), TASKS))
    open_ = run(tracks, MultiTaskAnticipator(controlled(config, p_logit=-10.0), manifest(config)))
    assert open_.committed and not gated.committed and not gated.candidates


def test_c_mt_replay_requires_gate_and_refuses_unflagged_direct_candidates():
    config = mt_config("gru")
    tracks = [track(i, 0.505 + i * 0.02) for i in range(4)]
    with pytest.raises(ValueError, match="aux-head gate"):
        run(tracks, MultiTaskAnticipator(controlled(config), manifest(config)), gate=None)
    direct = DirectHeadDiagnostic(controlled(config), manifest(config), diagnostic=True)
    with pytest.raises(ValueError, match="trajectory through geometry"):
        run(tracks, direct)
    with pytest.raises(ValueError, match="direct-head diagnostic"):
        run(tracks, direct, diagnostic=True)  # the diagnostic never runs with a geometry gate
    geometry_candidate = StrikeCandidate(
        "x", 1, 10.02, "LEFT", "snare", "MODEL", "GEOMETRY", "fake", 10.05, None, 0.03, (0.4, 0.58),
        (0.0, 1.0), 1.0, 1.0, 10.02,
    )  # fmt: skip
    with pytest.raises(ValueError, match="DIRECT_HEAD"):
        run(tracks, lambda *_: geometry_candidate, gate=None, diagnostic=True)
    with pytest.raises(ValueError, match="C-MT harness mode"):
        replay(
            tracks,
            arm="MODEL:C-GRU",
            registry=REGISTRY,
            commit_settings=CommitSettings.from_config(CFG),
            v_min=0.15,
            session_id="x",
            model=direct,
            diagnostic_direct=True,
        )


def test_flagged_diagnostic_mode_is_labelled_and_never_an_anticipator():
    config = mt_config("gru", TASKS[1:])  # no trajectory head
    with pytest.raises(ValueError, match="refused"):
        MultiTaskAnticipator(controlled(config), manifest(config))
    with pytest.raises(ValueError, match="explicitly"):
        DirectHeadDiagnostic(controlled(config), manifest(config))
    direct = DirectHeadDiagnostic(controlled(config, tti_scaled=0.1), manifest(config), diagnostic=True)
    assert not isinstance(direct, Anticipator) and direct.diagnostic_only
    result = run([track(i, 0.30) for i in range(8)], direct, gate=None, diagnostic=True, heads=TASKS[1:])
    assert result.diagnostic and result.committed  # far from any zone: heads alone commit (diagnostic!)
    assert all(s.derivation is CandidateDerivation.DIRECT_HEAD for s in result.committed)
    for s in result.committed:
        validate("committed-strike", s.to_dict())


def test_live_application_refuses_c_mt_and_never_references_the_diagnostic():
    from spacedrums.app import DecisionPipeline

    with pytest.raises(ValueError, match="got C-MT"):
        DecisionPipeline(
            CFG.data,
            registry=REGISTRY,
            session_id="x",
            active_arm="C-MT",
            hardware_id="HW-01",
            config_hash=CFG.config_hash,
            audio=None,
            gain_fn=lambda z, p: 0.5,
        )
    for path in (ROOT / "src/spacedrums/app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "DirectHeadDiagnostic" not in text and "diagnostic_direct" not in text, path
