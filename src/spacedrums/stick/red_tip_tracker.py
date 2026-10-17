"""Two stick tips from red blobs: stable identities, bounded prediction, never a predicted hit.

Internal tracks (``max_tracks``) follow every plausible red blob, so a red object in the room keeps its
own blob instead of capturing a stick's identity. Two *slots* (LEFT, RIGHT) are bound to confirmed
tracks; only slots reach the decision pipeline.

* **Association**: one joint Hungarian assignment (``scipy.optimize.linear_sum_assignment``) of all tracks
  to the frame's strong blobs, cost ``(d / r)^2`` inside each track's gate ``r = min(gate_max_px,
  gate_px + gate_speed_gain * |v| * tau_p + gate_growth_px_s * (tau - 0.05 s)+)`` around the prediction
  ``p + v * tau_p`` with ``tau_p = min(tau, max_predict_s)``. The prediction exists for gating only.
* **Recovery and blur**: a bound track left without a match may take a strong blob nobody claimed
  within twice its gate (capped at ``gate_max_px``), else the saturated core of a blurred region in its
  gate (``RedDetection.cores``: strong evidence that may continue a track but never starts one), else
  re-segments its gate window with the weak floors (motion-blur streaks). At most ``max_weak_frames``
  consecutive weak frames count as measured.
* **Birth**: an unclaimed strong blob starts a tentative track, confirmed after ``birth_frames``
  consecutive observations; a tentative track dies on its first miss. No birth within ``gate_px`` of an
  observed bound tip (a split fragment of that tip). Births are the only place a delay is added. When all
  ``max_tracks`` are in use, a new blob that scores higher (``RedBlob.score``: size x paint share) replaces
  the lowest-scoring *unbound* track that is tentative or has never moved, so red clutter in the room cannot
  keep the real tips from being born (live session 2026-10-16 134746: 7450 refused births).
* **Coasting**: a missed confirmed track keeps its identity for ``max_coast_s``, then it is deleted. A
  coasting slot is PREDICTED and carries no coordinates downstream.
* **Slots**: a free slot binds the best observed, confirmed, unbound track (moving before static, then
  score). While more unbound tracks (confirmed, coasting or tentative) than free slots exist (red clutter),
  only a *moving* candidate may bind: a stick held still and a red object look alike, so the tracker waits
  for motion instead of guessing. When both slots bind together the larger camera x becomes LEFT: the
  camera image is not mirrored, so the player's left hand is on the image's right (measured in 91.6 % of
  two-hand frames of a fingertip session). With hand assist and two detected hands the nearer grips
  decide. A bound track that has never moved ``move_px`` from where it appeared, for ``static_window_s``,
  yields its slot to a moving unbound track: a red object that grabbed a slot loses it as soon as a real
  stick moves, while a stick that has been played keeps its slot when held still.
* **Ambiguity**: when the two bound tracks could exchange their blobs within ``ambiguity_margin``
  (touching or crossing tips), or one merged blob sits on both predictions, both slots are AMBIGUOUS
  (not measured). When the episode ends both slots request an identity reset, so the pipeline restarts
  their stroke state instead of bridging a possible swap. Every (re)binding requests a reset too.

Causal: :meth:`RedTipTracker.step` sees only the current detections and the tracker's own past.
Coordinates are ROI pixels; times are ``t_capture`` seconds.
"""

from __future__ import annotations

import math
from collections import Counter, deque
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from spacedrums.contracts import HandId
from spacedrums.stick.red_tip import RedBlob, RedTipSettings

SLOTS = (HandId.LEFT, HandId.RIGHT)
MEASURED_STATES = ("OBSERVED", "WEAK", "DARK")
ACTIVITY_WINDOW_S = 1.0  # "moving" looks this far back
GATE_GROWTH_AFTER_S = 0.05  # gate growth starts once more than ~1.5 frame periods passed unobserved
RECOVERY_GATE_FACTOR = 2.0
MISS_COST = 1.0 + 1e-6  # a match anywhere inside the gate beats a miss
BIG = 1e9


@dataclass(frozen=True)
class Grip:
    """Hand-assist evidence for one detected hand (ROI pixels)."""

    point: tuple[float, float]
    reach: float
    score: float


@dataclass
class TipTrack:
    track_id: int
    pos: np.ndarray
    t_obs: float
    born_t: float
    area: float
    quality: float = 0.0  # RedBlob.score of the latest observation (ranking only)
    vel: np.ndarray = field(default_factory=lambda: np.zeros(2))
    n_obs: int = 1
    hits: int = 1  # consecutive observations
    misses: int = 0
    weak_run: int = 0
    confirmed: bool = False
    ever_moved: bool = False  # left its birth position by move_px at least once
    clipped: bool = False  # the latest blob touched the ROI border (never measured; never takes a free slot)
    need: int = 0  # consecutive observations confirming this track (0 = settings.birth_frames)
    history: deque = field(default_factory=deque)
    origin: np.ndarray | None = None  # birth position

    def __post_init__(self) -> None:
        if self.origin is None:
            self.origin = np.array(self.pos, float)

    def predict(self, t: float, s: RedTipSettings) -> tuple[np.ndarray, float]:
        tau = max(0.0, t - self.t_obs)
        tau_p = min(tau, s.max_predict_s)
        speed = math.hypot(float(self.vel[0]), float(self.vel[1]))
        growth = s.gate_growth_px_s * max(0.0, tau - GATE_GROWTH_AFTER_S)
        r = s.gate_px + s.gate_speed_gain * speed * tau_p + growth
        return self.pos + self.vel * tau_p, min(s.gate_max_px, r)

    def observe(self, blob: RedBlob, t: float, s: RedTipSettings) -> None:
        c = np.asarray(blob.center, float)
        tau = t - self.t_obs
        if tau > 0:
            v = (c - self.pos) / tau
            self.vel = v if self.n_obs == 1 else s.velocity_alpha * v + (1 - s.velocity_alpha) * self.vel
        self.pos, self.t_obs, self.area, self.quality = c, t, blob.area, blob.score
        self.n_obs += 1
        self.hits += 1
        self.misses = 0
        self.weak_run = self.weak_run + 1 if blob.weak else 0
        self.clipped = blob.clipped
        self.ever_moved = self.ever_moved or math.dist(c, self.origin) >= s.move_px
        self.history.append((t, float(c[0]), float(c[1])))
        while self.history and t - self.history[0][0] > ACTIVITY_WINDOW_S + 0.5:
            self.history.popleft()

    def score(self, s: RedTipSettings) -> float:
        return self.quality

    def moving(self, t: float, s: RedTipSettings) -> bool:
        return any(t - tt <= ACTIVITY_WINDOW_S and math.dist((x, y), self.pos) >= s.move_px
                   for tt, x, y in self.history)

    def idle(self, t: float, s: RedTipSettings) -> bool:
        """Never left its birth position in ``static_window_s``: a red object, not a played stick."""
        return not self.ever_moved and t - self.born_t >= s.static_window_s


@dataclass(frozen=True)
class SlotState:
    """What one hand's slot reports this frame (ROI pixels)."""

    hand_id: HandId
    # OBSERVED | WEAK | DARK | AMBIGUOUS | CLIPPED | WEAK_LIMIT | LOW_EVIDENCE | PREDICTED | NO_TRACK
    state: str
    track_id: int | None
    tip: tuple[float, float] | None  # observed centre; None unless a blob was seen this frame
    predicted: tuple[float, float] | None  # coasting prediction (diagnostics only, never measured)
    confidence: float  # evidence class for measured states, else 0
    misses: int
    area: float | None = None
    axis: tuple[float, float] | None = None

    @property
    def measured(self) -> bool:
        return self.state in MEASURED_STATES


@dataclass(frozen=True)
class TrackerFrame:
    t: float
    slots: dict[HandId, SlotState]
    resets: frozenset[HandId]
    ambiguous: bool
    tracks: tuple[dict, ...]


def recovery_reach(track: TipTrack, gate: float, s: RedTipSettings) -> float:
    """How far a bound track may jump to an unclaimed strong blob. A fast stroke's streak can vanish for a
    frame or two and reappear far from a constant-velocity prediction, so the reach grows with misses."""
    if track.misses == 0:
        return min(s.gate_max_px, RECOVERY_GATE_FACTOR * gate)
    return min(2 * s.gate_max_px, s.gate_max_px * (1 + track.misses))


def _assign(cost: np.ndarray) -> dict[int, int]:
    n, m = cost.shape
    if n == 0 or m == 0:
        return {}
    aug = np.full((n, m + n), BIG)
    aug[:, :m] = np.where(np.isfinite(cost), cost, BIG)
    aug[np.arange(n), m + np.arange(n)] = MISS_COST
    rows, cols = linear_sum_assignment(aug)
    return {int(i): int(j) for i, j in zip(rows, cols, strict=True) if j < m and aug[i, j] < BIG}


class RedTipTracker:
    def __init__(self, settings: RedTipSettings | None = None) -> None:
        self.settings = settings or RedTipSettings()
        self.counters: Counter = Counter()
        self.reset()

    def reset(self) -> None:
        self.tracks: list[TipTrack] = []
        self.slots: dict[HandId, int | None] = dict.fromkeys(SLOTS)
        self.next_id = 1
        self.t_last: float | None = None
        self.ambiguous = False

    def step(self, t: float, blobs, *, roi_size: tuple[int, int], weak=None,
             grips: dict[HandId, Grip] | None = None, cores=()) -> TrackerFrame:
        """One frame. ``weak(center, radius)`` returns weak-floor blobs near a point (nearest first).
        ``cores``: saturated cores of blurred regions; bound tracks may recover on them, nothing is born."""
        s = self.settings
        if self.t_last is not None and t <= self.t_last:
            raise ValueError("tracker frames must have strictly increasing timestamps")
        self.t_last = t
        grips = grips or {}
        blobs = list(blobs)
        tracks = self.tracks
        index = {tr.track_id: i for i, tr in enumerate(tracks)}
        preds = [tr.predict(t, s) for tr in tracks]
        cost = np.full((len(tracks), len(blobs)), np.inf)
        for i, (p, r) in enumerate(preds):
            for j, b in enumerate(blobs):
                d = math.dist(b.center, p)
                if d <= r:
                    cost[i, j] = (d / r) ** 2
        match = _assign(cost)
        claimed = set(match.values())
        seen: dict[int, RedBlob] = {tracks[i].track_id: blobs[j] for i, j in match.items()}

        # Recovery (joint, wider gate, unclaimed blobs only), then weak re-detection, for bound tracks.
        pair = [self.slots[h] for h in SLOTS]
        lost = [index[tid] for tid in pair
                if tid is not None and tid in index and tid not in seen and tracks[index[tid]].confirmed]
        free = [j for j in range(len(blobs)) if j not in claimed]
        spare = [blobs[j] for j in free] + list(cores)  # cores only ever continue a bound track
        if lost and spare:
            wide = np.full((len(lost), len(spare)), np.inf)
            for a, i in enumerate(lost):
                p, r = preds[i]
                reach = recovery_reach(tracks[i], r, s)
                for c, b in enumerate(spare):
                    d = math.dist(b.center, p)
                    if d <= reach:
                        wide[a, c] = (d / reach) ** 2
            for a, c in _assign(wide).items():
                if c < len(free):
                    claimed.add(free[c])
                seen[tracks[lost[a]].track_id] = spare[c]
                self.counters["RECOVERED" if c < len(free) else "CORE_FRAMES"] += 1
        pending = [i for i in lost if tracks[i].track_id not in seen]
        if weak is not None and pending:
            # Blur streaks near each still-unmatched bound track, assigned jointly (no slot-order bias).
            separation = max(2.0 * s.merge_px, 0.5 * s.gate_px)
            taken = [b.center for b in seen.values()]
            options: list[RedBlob] = []
            for i in pending:
                p, r = preds[i]
                for b in weak(tuple(map(float, p)), r):
                    if all(math.dist(b.center, c) > separation for c in taken + [o.center for o in options]):
                        options.append(b)
            if options:
                streak = np.full((len(pending), len(options)), np.inf)
                for a, i in enumerate(pending):
                    p, r = preds[i]
                    for c, b in enumerate(options):
                        d = math.dist(b.center, p)
                        if d <= r:
                            streak[a, c] = (d / r) ** 2
                for a, c in _assign(streak).items():
                    seen[tracks[pending[a]].track_id] = options[c]
                    self.counters["WEAK_FRAMES"] += 1

        # Ambiguity between the two bound tracks: could they exchange what they were given?
        ambiguous = False
        if all(tid is not None and tid in index for tid in pair):
            ia, ib = index[pair[0]], index[pair[1]]
            ba, bb = seen.get(pair[0]), seen.get(pair[1])

            def c(i, blob):
                p, r = preds[i]
                return (math.dist(blob.center, p) / r) ** 2

            if ba is not None and bb is not None:
                ambiguous = c(ia, bb) + c(ib, ba) - (c(ia, ba) + c(ib, bb)) < s.ambiguity_margin
            elif (ba is None) != (bb is None):
                i_has, i_not, blob = (ia, ib, ba) if ba is not None else (ib, ia, bb)
                ambiguous = (math.dist(blob.center, preds[i_not][0]) <= s.gate_px
                             and c(i_not, blob) - c(i_has, blob) < s.ambiguity_margin)

        # Update observed tracks; age the others.
        survivors = []
        for tr in tracks:
            blob = seen.get(tr.track_id)
            if blob is not None:
                tr.observe(blob, t, s)
                if not tr.confirmed and tr.hits >= (tr.need or s.birth_frames):
                    tr.confirmed = True
                    self.counters["CONFIRMED"] += 1
                survivors.append(tr)
                continue
            tr.misses += 1
            tr.hits = 0
            if not tr.confirmed:
                self.counters["TENTATIVE_DROPPED"] += 1
            elif t - tr.t_obs > s.max_coast_s:
                self.counters["LOST"] += 1
            else:
                survivors.append(tr)
        self.tracks = tracks = survivors

        # Births from unclaimed strong blobs.
        bound_now = {tid for tid in self.slots.values() if tid is not None}
        anchors = [tr.pos for tr in tracks if tr.track_id in bound_now and tr.t_obs == t]
        for j, b in enumerate(blobs):
            if j in claimed:
                continue
            if any(math.dist(b.center, a) <= s.gate_px for a in anchors):
                self.counters["FRAGMENT_SUPPRESSED"] += 1
                continue
            if b.dark and (b.surround or 0.0) < s.dark_birth_surround:
                self.counters["DARK_NO_CONTEXT"] += 1  # dim-light blobs start a track only when held up
                continue
            if len(tracks) >= s.max_tracks:
                victim = self._evictable(b, bound_now)
                if victim is None:
                    self.counters["TRACK_LIMIT"] += 1
                    continue
                tracks.remove(victim)
                self.counters["TRACK_EVICTED"] += 1
            if len(grips) == 2 and all(math.dist(b.center, g.point) > g.reach for g in grips.values()):
                self.counters["FAR_FROM_HANDS"] += 1
                continue
            need = s.dark_birth_frames if b.dark else s.birth_frames  # dim-light blobs must persist longer
            tr = TipTrack(self.next_id, np.asarray(b.center, float), t, t, b.area, b.score,
                          confirmed=need <= 1, history=deque([(t, *map(float, b.center))]), clipped=b.clipped,
                          need=need)
            self.next_id += 1
            tracks.append(tr)
            seen[tr.track_id] = b
            self.counters["BIRTHS"] += 1

        resets = self._bind_slots(t, roi_size, grips)
        if self.ambiguous and not ambiguous and s.reset_after_ambiguity:
            resets |= {h for h in SLOTS if self.slots[h] is not None}
            self.counters["AMBIGUITY_RESETS"] += 1
        if ambiguous:
            self.counters["AMBIGUOUS_FRAMES"] += 1
            if not self.ambiguous:
                self.counters["AMBIGUITY_EPISODES"] += 1
        self.ambiguous = ambiguous
        self.counters["IDENTITY_RESETS"] += len(resets)

        live = {tr.track_id: tr for tr in tracks}
        pred_by_id = {tr.track_id: preds[i][0] for tr, i in ((tr, index.get(tr.track_id)) for tr in tracks)
                      if i is not None}
        states = {}
        for h in SLOTS:
            tid = self.slots[h]
            tr = live.get(tid) if tid is not None else None
            if tr is None:
                states[h] = SlotState(h, "NO_TRACK", None, None, None, 0.0, 0)
                continue
            blob = seen.get(tid) if tr.t_obs == t else None
            if blob is None:
                p = pred_by_id.get(tid, tr.pos)
                states[h] = SlotState(h, "PREDICTED", tid, None, (float(p[0]), float(p[1])), 0.0, tr.misses)
                continue
            confidence = 0.0
            if ambiguous and tid in pair:
                state = "AMBIGUOUS"
            elif blob.clipped:
                state = "CLIPPED"
            elif blob.weak and tr.weak_run > s.max_weak_frames:
                state = "WEAK_LIMIT"
            elif blob.weak:
                state, confidence = "WEAK", s.weak_confidence
            elif blob.dark:
                state, confidence = "DARK", s.dark_confidence
            else:
                state, confidence = "OBSERVED", s.observed_confidence
            states[h] = SlotState(h, state, tid, (float(blob.center[0]), float(blob.center[1])), None,
                                  confidence, 0, blob.area, blob.axis)
        slot_of = {tid: str(h) for h, tid in self.slots.items() if tid is not None}
        summary = tuple(
            {"id": tr.track_id, "slot": slot_of.get(tr.track_id), "confirmed": tr.confirmed,
             "observed": tr.t_obs == t, "pos": (float(tr.pos[0]), float(tr.pos[1])), "misses": tr.misses}
            for tr in tracks
        )
        return TrackerFrame(t, states, frozenset(resets), ambiguous, summary)

    def _evictable(self, blob: RedBlob, bound: set[int]) -> TipTrack | None:
        """The unbound track a better new blob may replace: tentative or never moved, lowest score first."""
        pool = [tr for tr in self.tracks if tr.track_id not in bound and tr.quality < blob.score
                and (not tr.confirmed or not tr.ever_moved)]
        return min(pool, key=lambda tr: (tr.quality, tr.t_obs, tr.track_id)) if pool else None

    def _bind_slots(self, t: float, roi_size: tuple[int, int], grips: dict[HandId, Grip]) -> set[HandId]:
        s = self.settings
        live = {tr.track_id: tr for tr in self.tracks}
        resets: set[HandId] = set()
        for h in SLOTS:
            if self.slots[h] is not None and self.slots[h] not in live:
                self.slots[h] = None
                self.counters["SLOT_LOST"] += 1

        def candidates():
            bound = {tid for tid in self.slots.values() if tid is not None}
            pool = [tr for tr in self.tracks if tr.confirmed and tr.t_obs == t and tr.track_id not in bound
                    and not tr.clipped]
            return sorted(pool, key=lambda tr: (not tr.moving(t, s), -tr.score(s), tr.track_id))

        def bind(h, tr, *, reset=True):
            self.slots[h] = tr.track_id
            if reset:
                resets.add(h)
            self.counters["BINDS"] += 1

        for h in SLOTS:  # a coasting slot adopts a tip that appeared near it while it was unseen
            tid = self.slots[h]
            if tid is None or live[tid].t_obs == t:
                continue
            old = live[tid]
            reach = min(2 * s.gate_max_px, s.gate_max_px * (1 + old.misses))
            bound = {x for x in self.slots.values() if x is not None}
            newer = [tr for tr in self.tracks if tr.track_id not in bound and tr.t_obs == t and not tr.clipped
                     and tr.born_t > old.t_obs and math.dist(tr.pos, old.pos) <= reach]
            if not newer:
                continue
            pick = min(newer, key=lambda tr: math.dist(tr.pos, old.pos))
            if pick.n_obs == 1:  # carry the motion across the gap into the new track's gating
                pick.vel = (pick.pos - old.pos) / max(1e-3, t - old.t_obs)
            pick.confirmed = True
            other = self.slots[SLOTS[1] if h is SLOTS[0] else SLOTS[0]]
            # Only when the other stick is unseen too could this be the other stick: then restart strokes.
            bind(h, pick, reset=other is None or live[other].t_obs != t)
            self.tracks.remove(old)
            live.pop(tid)
            self.counters["ADOPTED"] += 1

        for h in SLOTS:  # a red object that never moved yields its slot as soon as an unbound tip moves
            tid = self.slots[h]
            if tid is not None and live[tid].idle(t, s):
                movers = [tr for tr in candidates() if tr.moving(t, s)]
                if movers:
                    bind(h, movers[0])
                    self.counters["STATIC_RELEASES"] += 1
        free = [h for h in SLOTS if self.slots[h] is None]
        pool = candidates()
        bound = {tid for tid in self.slots.values() if tid is not None}
        rivals = [tr for tr in self.tracks if tr.track_id not in bound]  # seen, coasting or still tentative
        if free and len(rivals) > len(free) and len(grips) < 2:
            # More red candidates than free slots: a stick held still and a red object in the room look the
            # same, so only a moving candidate may take a slot (no guess by size or position).
            pool = [tr for tr in pool if tr.moving(t, s)]
            if not pool:
                self.counters["BIND_DEFERRED"] += 1
        if len(free) == 2 and len(pool) >= 2:
            a, b = pool[0], pool[1]
            if len(grips) == 2:
                gl, gr = grips[HandId.LEFT].point, grips[HandId.RIGHT].point
                straight = math.dist(a.pos, gl) + math.dist(b.pos, gr)
                crossed = math.dist(a.pos, gr) + math.dist(b.pos, gl)
                left, right = (a, b) if straight <= crossed else (b, a)
            else:
                left, right = (a, b) if a.pos[0] >= b.pos[0] else (b, a)
            bind(HandId.LEFT, left)
            bind(HandId.RIGHT, right)
        elif len(free) == 2 and pool:
            tr = pool[0]
            near = [(d, h) for h, g in grips.items() if (d := math.dist(tr.pos, g.point)) <= g.reach]
            h = min(near)[1] if near else (HandId.LEFT if tr.pos[0] >= roi_size[0] / 2 else HandId.RIGHT)
            bind(h, tr)
        elif free and pool:
            bind(free[0], pool[0])
        return resets


__all__ = ["MEASURED_STATES", "SLOTS", "Grip", "RedTipTracker", "SlotState", "TipTrack", "TrackerFrame"]
