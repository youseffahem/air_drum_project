"""Convert GBDT outputs to direct or trajectory-derived model candidates."""

from __future__ import annotations

from spacedrums.contracts import (
    CandidateDerivation,
    CandidateSource,
    StrikeCandidate,
    TrackState,
    TrajectoryAux,
    TrajectoryPrediction,
)


class GBDTAdapter:
    def __init__(self, predictor, *, mode: str, dt_step: float = 1 / 30):
        if mode not in ("direct", "trajectory") or dt_step <= 0:
            raise ValueError("mode must be direct or trajectory, dt_step positive")
        self.predictor, self.mode, self.dt_step = predictor, mode, dt_step

    def __call__(self, track: TrackState, _history, window):
        if window is None or track.tip_filtered is None:
            return None
        x, mask = window
        out = self.predictor.predict(x, mask)
        probability = out["strike_probability"]
        if self.mode == "direct":
            zone = out["zone_id"]
            tti = out["tti"]
            if zone is None or tti is None:
                return None
            tti = max(0.0, float(tti))
            return StrikeCandidate(
                candidate_id=f"gbdt-{track.hand_id}-{track.frame_id}",
                frame_id=track.frame_id,
                t_capture=track.t_capture,
                hand_id=track.hand_id,
                zone_id=zone,
                source=CandidateSource.MODEL,
                derivation=CandidateDerivation.DIRECT_HEAD,
                anticipator_id="gbdt-direct-v1",
                t_impact_pred=track.t_capture + tti,
                t_impact_est=None,
                tti=tti,
                impact_position=track.tip_filtered,
                crossing_velocity=track.tip_velocity or (0.0, 0.0),
                strike_probability=probability,
                intensity_proxy=sum(v * v for v in (track.tip_velocity or (0.0, 0.0))) ** 0.5,
                t_candidate=track.t_capture,
            )
        points = out["displacements"]
        k = self.predictor.manifest["trajectory_steps"]
        if not points or max(points) != k - 1:
            return None
        anchors = [(0, (0.0, 0.0))] + sorted((step + 1, delta) for step, delta in points.items())
        positions = []
        for step in range(1, k + 1):
            right = next(i for i, (s, _) in enumerate(anchors) if s >= step)
            if anchors[right][0] == step:
                displacement = anchors[right][1]
            else:
                left_s, left = anchors[right - 1]
                right_s, end = anchors[right]
                alpha = (step - left_s) / (right_s - left_s)
                displacement = (left[0] + alpha * (end[0] - left[0]), left[1] + alpha * (end[1] - left[1]))
            positions.append(
                (track.tip_filtered[0] + displacement[0], track.tip_filtered[1] + displacement[1])
            )
        return TrajectoryPrediction(
            frame_id=track.frame_id,
            t_capture=track.t_capture,
            hand_id=track.hand_id,
            anticipator_id="gbdt-trajectory-v1",
            model_hash=self.predictor.model_hash,
            K=k,
            dt_step=self.dt_step,
            t_offsets_s=None,
            positions=tuple(positions),
            velocities=None,
            uncertainty=None,
            uncertainty_kind=None,
            aux=TrajectoryAux(strike_prob_within_H=probability, tti=out["tti"]),
            t_inference_done=track.t_capture,
        )
