"""Post-geometry use of multi-task heads: agreement flags and optional gates (Task 11.5).

The gate receives a ``TrajectoryPrediction`` and the ``StrikeCandidate`` that geometry derived
from that same prediction. It may drop the candidate or swap its intensity proxy; it never
creates one (ADR-0007). Only contracts are imported: geometry's output is passed in by the
caller, so a model package still cannot see zones (import-linter ``no-peek``).
"""

import math
from collections import Counter
from dataclasses import dataclass, replace

import numpy as np

from spacedrums.contracts import CONSISTENCY_CHECKS, CandidateDerivation

INTENSITY_SOURCES = ("geometry", "head")
HEAD_FOR_CHECK = {"zone": "zone", "tti": "tti", "position": "position", "intensity": "intensity"}


@dataclass(frozen=True)
class AuxHeadSettings:
    """``commit.aux_heads`` (config 1.5). Every default is off; all values are candidates."""

    use_p_aux: bool = False
    p_aux: float = 0.5
    use_agreement: bool = False
    agreement_checks: tuple[str, ...] = ("zone", "tti", "position")
    tti_tolerance_s: float = 0.03
    position_tolerance: float = 0.05
    intensity_tolerance: float = 0.5
    intensity_source: str = "geometry"

    def __post_init__(self):
        object.__setattr__(self, "agreement_checks", tuple(self.agreement_checks))
        checks = self.agreement_checks
        if not checks or len(set(checks)) != len(checks) or any(c not in CONSISTENCY_CHECKS for c in checks):
            raise ValueError(f"agreement_checks must be a nonempty unique subset of {CONSISTENCY_CHECKS}")
        if not 0 <= self.p_aux <= 1 or self.intensity_source not in INTENSITY_SOURCES:
            raise ValueError("p_aux in [0,1] and a known intensity source required")
        tolerances = (self.tti_tolerance_s, self.position_tolerance, self.intensity_tolerance)
        if any(not math.isfinite(v) or v < 0 for v in tolerances):
            raise ValueError("tolerances must be finite and nonnegative")

    @classmethod
    def from_config(cls, cfg):
        block = cfg["commit"].get("aux_heads")
        return cls() if block is None else cls(**block)

    def to_dict(self):
        return {
            "use_p_aux": self.use_p_aux,
            "p_aux": self.p_aux,
            "use_agreement": self.use_agreement,
            "agreement_checks": list(self.agreement_checks),
            "tti_tolerance_s": self.tti_tolerance_s,
            "position_tolerance": self.position_tolerance,
            "intensity_tolerance": self.intensity_tolerance,
            "intensity_source": self.intensity_source,
        }

    def required_heads(self):
        heads = set()
        if self.use_p_aux:
            heads.add("strike")
        if self.use_agreement:
            heads.update(HEAD_FOR_CHECK[c] for c in self.agreement_checks)
        if self.intensity_source == "head":
            heads.add("intensity")
        return heads


def consistency_flags(aux, candidate, settings):
    """Per-check agreement of heads with the geometry candidate; None without a candidate/head.

    Geometry intensity is the candidate's proxy before any intensity-source swap, i.e. the
    inward crossing speed on the predicted trajectory (``eval.temporal``).
    """
    if candidate is None:
        return None
    flags = {
        "zone": None
        if aux.zone_logits is None
        else bool(aux.zone_ids[int(np.argmax(aux.zone_logits))] == candidate.zone_id),
        "tti": None
        if aux.tti is None or candidate.tti is None
        else bool(abs(aux.tti - candidate.tti) <= settings.tti_tolerance_s),
        "position": None
        if aux.impact_pos is None
        else bool(math.dist(aux.impact_pos, candidate.impact_position) <= settings.position_tolerance),
        "intensity": None
        if aux.intensity_proxy is None
        else bool(abs(aux.intensity_proxy - candidate.intensity_proxy) <= settings.intensity_tolerance),
    }
    return None if all(v is None for v in flags.values()) else flags


class AuxGate:
    """C-MT post-geometry step between geometry and the unchanged Phase 05 policy.

    The head probability never reaches ``commit.p_commit``: the candidate's
    ``strike_probability`` is cleared and ``p_aux`` is applied here only when enabled, so the
    defaults leave every geometry-derived candidate untouched apart from that field.
    """

    def __init__(self, settings, heads):
        missing = settings.required_heads() - set(heads)
        if missing:
            raise ValueError(f"aux-head settings need absent heads: {sorted(missing)}")
        self.settings = settings
        self.decisions = Counter()
        self.log = []

    def __call__(self, prediction, candidate):
        flags = consistency_flags(prediction.aux, candidate, self.settings)
        if flags is not None:
            prediction = replace(prediction, aux=replace(prediction.aux, consistency_flags=flags))
        if candidate is None:
            return prediction, None
        if candidate.derivation is not CandidateDerivation.GEOMETRY:
            raise ValueError("aux-head gates apply only to geometry-derived candidates")
        s, probability = self.settings, prediction.aux.strike_prob_within_H
        decision = "PASS"
        if s.use_p_aux and (probability is None or probability < s.p_aux):
            decision = "REJECT_P_AUX"
        elif s.use_agreement and (flags is None or any(flags[c] is not True for c in s.agreement_checks)):
            decision = "REJECT_AGREEMENT"
        self.decisions[decision] += 1
        self.log.append(
            {
                "frame_id": candidate.frame_id,
                "hand_id": str(candidate.hand_id),
                "candidate_id": candidate.candidate_id,
                "zone_id": candidate.zone_id,
                "strike_prob_within_H": probability,
                "consistency_flags": flags,
                "decision": decision,
            }
        )
        if decision != "PASS":
            return prediction, None
        out = replace(candidate, strike_probability=None)
        if s.intensity_source == "head":
            if prediction.aux.intensity_proxy is None:
                raise ValueError("head intensity source without an intensity output")
            out = replace(out, intensity_proxy=max(0.0, float(prediction.aux.intensity_proxy)))
        return prediction, out
