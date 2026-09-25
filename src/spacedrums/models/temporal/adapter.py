"""Per-hand Anticipator, shared weights, no direct-head strike path."""

import numpy as np
import torch

from spacedrums.contracts import CandidateSource

from .decode import decode
from .gru import BoundedGRUState


class TemporalAnticipator:
    source = CandidateSource.MODEL

    def __init__(self, model, manifest, *, stateful=False, feature_stream=None, stats=None):
        self.model = model.eval()
        self.manifest = manifest
        self.model_hash = manifest.get("export_hash", manifest["checkpoint_hash"])
        self.anticipator_id = "temporal-" + manifest["family"] + "-v1"
        self.n, self.k, self.dt_step = manifest["N"], manifest["K"], manifest["dt_step"]
        if stateful and manifest["family"] != "gru":
            raise ValueError("stateful cache is available only for GRU")
        if (feature_stream is None) != (stats is None):
            raise ValueError("streaming features require schema and fold stats together")
        if feature_stream is not None and (
            feature_stream.schema.fingerprint != manifest["feature_schema_hash"]
            or stats.data["fold"] != manifest["fold"]
        ):
            raise ValueError("streaming schema/fold mismatch")
        self.stateful, self.states = stateful, {}
        # Inject the upstream assembler; models must not import its geometry dependency.
        self.stats, self.stream = stats, feature_stream
        self.last = {}

    def declared_history(self):
        return {
            "N": self.n,
            "N_min": self.n,
            "state": "bounded cold-start lanes" if self.stateful else "windowed",
        }

    def reset(self, reason=None):
        del reason
        self.states.clear()
        self.last.clear()
        if self.stream:
            self.stream.reset()

    def _reset_hand(self, hand):
        self.states.pop(hand, None)
        self.last.pop(hand, None)
        if self.stream:
            self.stream.reset(hand)

    def __call__(self, track, history, window):
        if not history or history[-1] != track:
            raise ValueError("adapter track/history mismatch")
        return self.predict(history, window)

    @torch.inference_mode()
    def predict(self, track_history, features=None):
        prepared = self._prepare(track_history, features)
        if prepared is None:
            return None
        track, x, mask = prepared
        return self._decode(track, self._infer(track.hand_id, x, mask))

    def _prepare(self, track_history, features):
        """Per-hand causal guards; returns (track, x, mask) or None. Shared by every head layout."""
        if not track_history:
            return None
        track = track_history[-1]
        hand = track.hand_id
        if track.reset_reason is not None:
            self._reset_hand(hand)
        if track.status not in ("VALID", "DEGRADED") or track.tip_filtered is None:
            self.states.pop(hand, None)
            self.last.pop(hand, None)
            if features is None and self.stream:
                # Retain the masked observation/actual dt using the Phase 08 assembler.
                self.stream.update(track)
            return None
        previous = self.last.get(hand)
        if previous is not None and (track.t_capture <= previous[0] or track.frame_id <= previous[1]):
            self._reset_hand(hand)
            return None
        self.last[hand] = (track.t_capture, track.frame_id)
        if features is None and self.stream:
            self.stream.update(track)
            features = self.stream.window(hand, stats=self.stats)
        window = list(track_history[-self.n :])
        if len(window) != self.n or features is None:
            return None
        if any(t.hand_id != hand or t.status not in ("VALID", "DEGRADED") for t in window):
            self.states.pop(hand, None)
            return None
        if any(t.reset_reason is not None for t in window[1:]):
            return None
        if any(a.t_capture >= b.t_capture for a, b in zip(window, window[1:], strict=False)):
            self.states.pop(hand, None)
            return None
        x, mask = (torch.as_tensor(np.asarray(v).copy()) for v in features)
        x, mask = x.to(torch.float32), mask.to(torch.bool)
        if x.shape != (self.n, self.manifest["F"]) or mask.shape != x.shape:
            raise ValueError("model/feature shape mismatch")
        if not torch.isfinite(x[mask]).all():
            raise ValueError("nonfinite model inputs")
        return track, x, mask

    def _infer(self, hand, x, mask):
        if self.stateful:
            if hand not in self.states:
                self.states[hand] = BoundedGRUState(self.model)
            return self.states[hand](x, mask)
        return self.model(x[None], mask[None])

    def _decode(self, track, outputs):
        delta, logit = outputs
        probability = float(torch.sigmoid(logit[0])) if self.manifest["config"]["auxiliary"] else None
        # The prediction clock remains the trained fixed grid even if capture dt varies.
        # Geometry interpolates consecutive grid points; live input resampling is Phase 13.
        return decode(
            track,
            delta[0].numpy(),
            dt_step=self.dt_step,
            anticipator_id=self.anticipator_id,
            model_hash=self.model_hash,
            probability=probability,
        )
