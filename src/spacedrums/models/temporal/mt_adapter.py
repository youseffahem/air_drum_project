"""Multi-task adapters: heads populate ``aux`` only; the trajectory is decoded as in Phase 10.

``MultiTaskAnticipator`` is the only live-eligible form and refuses a package without the
trajectory head. ``DirectHeadDiagnostic`` is the labelled no-trajectory diagnostic of Task 11.6
(ADR-0007 amendment): it is deliberately not an ``Anticipator``, needs ``diagnostic=True`` to be
built, and the replay accepts its DIRECT_HEAD candidates only in an explicitly flagged mode.
"""

import numpy as np

from spacedrums.contracts import (
    CandidateDerivation,
    CandidateSource,
    StrikeCandidate,
    TrajectoryAux,
)

from .adapter import TemporalAnticipator
from .config import MultiTaskConfig
from .decode import decode
from .heads import decode_heads


def require_live_eligible(manifest):
    config = MultiTaskConfig.from_dict(manifest["mt_config"])
    if not manifest.get("live_eligible") or not config.live_eligible:
        raise ValueError("no-trajectory (direct-head) model package refused: trajectory first, ADR-0007")
    return config


class _MultiTaskBase(TemporalAnticipator):
    def __init__(self, model, manifest, **kwargs):
        super().__init__(model, manifest, **kwargs)
        self.config = MultiTaskConfig.from_dict(manifest["mt_config"])
        self.scaling = manifest["target_scaling"]
        self.anticipator_id = "temporal-mt-" + manifest["family"] + "-v1"

    def head_aux(self, track, outputs):
        values = decode_heads(self.config, self.scaling, outputs, [track.tip_filtered])
        zone = "zone_logits" in values
        return TrajectoryAux(
            strike_prob_within_H=float(values["strike_prob"][0]) if "strike_prob" in values else None,
            tti=float(values["tti_s"][0]) if "tti_s" in values else None,
            zone_logits=tuple(values["zone_logits"][0]) if zone else None,
            zone_ids=self.config.zone_ids if zone else None,
            impact_pos=tuple(values["impact_pos"][0]) if "impact_pos" in values else None,
            intensity_proxy=float(values["intensity"][0]) if "intensity" in values else None,
        )


class MultiTaskAnticipator(_MultiTaskBase):
    """Anticipator for arm C-MT: a TrajectoryPrediction whose aux carries every trained head."""

    def __init__(self, model, manifest, **kwargs):
        require_live_eligible(manifest)
        super().__init__(model, manifest, **kwargs)

    def _decode(self, track, outputs):
        return decode(
            track,
            outputs[0][0].numpy(),
            dt_step=self.dt_step,
            anticipator_id=self.anticipator_id,
            model_hash=self.model_hash,
            aux=self.head_aux(track, outputs),
        )


class _HeadRunner(_MultiTaskBase):
    def _decode(self, track, outputs):
        return track, self.head_aux(track, outputs)


class DirectHeadDiagnostic:
    """No-trajectory diagnostic: p(strike) + TTI + zone heads -> DIRECT_HEAD candidate.

    Mirrors the Phase 09 C-GBDT direct mode: one candidate per eligible frame, gated by the same
    Phase 05 policy (probability and tau_commit). Results must be labelled
    'direct / no-trajectory (diagnostic)'. Never wired into the application.
    """

    diagnostic_only = True
    source = CandidateSource.MODEL

    def __init__(self, model, manifest, *, diagnostic=False):
        if diagnostic is not True:
            raise ValueError("the direct-head diagnostic must be requested explicitly (diagnostic=True)")
        self.runner = _HeadRunner(model, manifest)
        if not {"strike", "tti", "zone"} <= set(self.runner.config.heads):
            raise ValueError("direct-head diagnostic needs strike, TTI and zone heads")
        self.anticipator_id = "temporal-mt-" + manifest["family"] + "-direct-diagnostic-v1"

    def reset(self, reason=None):
        self.runner.reset(reason)

    def __call__(self, track, history, window):
        out = self.runner(track, history, window)
        if out is None:
            return None
        track, aux = out
        tti = max(0.0, float(aux.tti))
        return StrikeCandidate(
            candidate_id=f"mt-direct-{track.hand_id}-{track.frame_id}",
            frame_id=track.frame_id,
            t_capture=track.t_capture,
            hand_id=track.hand_id,
            zone_id=aux.zone_ids[int(np.argmax(aux.zone_logits))],
            source=CandidateSource.MODEL,
            derivation=CandidateDerivation.DIRECT_HEAD,
            anticipator_id=self.anticipator_id,
            t_impact_pred=track.t_capture + tti,
            t_impact_est=None,
            tti=tti,
            impact_position=aux.impact_pos or track.tip_filtered,
            crossing_velocity=track.tip_velocity or (0.0, 0.0),
            strike_probability=aux.strike_prob_within_H,
            intensity_proxy=0.0 if aux.intensity_proxy is None else aux.intensity_proxy,
            t_candidate=track.t_capture,
        )
