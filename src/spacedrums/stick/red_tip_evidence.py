"""Two stick tips from verified redness candidates: evidence-based slots, never a predicted hit.

Used with ``stick_tip.detector: redness`` (stick/red_tip_caps.py). Every candidate carries a verifier
quality ``q`` in [0, 1] (``RedBlob.score``); a single frame's ``q`` flickers, so the tracker decides on
accumulated **evidence** instead (owner recordings 2026-10-17: hands and cloth reach a high ``q`` in some
frames, caps drop in others; docs/perf/red-tip-stick-mode.md section 11).

* **Tracks** follow every candidate that reached ``birth_quality`` (no birth within ``FRAGMENT_PX`` of a
  track seen this frame). Association is one joint Hungarian assignment of tracks to candidates, cost
  ``(d / r)^2 + QUALITY_COST x (1 - q)`` inside each track's gate (same gate as RedTipTracker:
  ``gate_px`` + speed x horizon + growth, capped at ``gate_max_px``); the prediction exists for gating only.
  A track is confirmed after ``birth_frames`` consecutive observations; a tentative track dies on its first
  miss, a confirmed one coasts ``max_coast_s``.
* **Evidence** ``ev`` is an EMA (``evidence_alpha``) of ``q``; a clipped observation counts 0, a miss
  multiplies it by ``MISS_DECAY``. **Rank** = ``ev`` x a stillness weight: a track that has not moved
  ``move_px`` for ``still_s`` loses weight linearly over ``still_decay_s`` down to ``still_floor``, so a
  static red object yields its slot to a played stick (binding order and challenges use the rank).
  Measurement uses the evidence alone: a stick held still is indistinguishable from a red object until it
  moves, and its first stroke must not wait for that (on the labelled recordings the stillness weight
  changed measured false points by at most 2).
* **Slots** (LEFT, RIGHT; larger camera x = LEFT, the image is not mirrored) bind observed, unclipped
  tracks with ``ev >= bind_evidence`` that are confirmed or, on their first frame, reach
  ``q >= instant_quality`` within ``identity_memory_s`` / ``identity_memory_px`` of where a slot last
  measured (a stick reacquired after a short loss; a first sighting always waits ``birth_frames``). Tracks
  that moved ``move_px`` within the last second come first, then the best rank. One new tip takes the slot
  that last measured near it, else its side of the image.
* **Slot changes**: a slot is released when its track is lost, clipped for ``clip_release_frames`` or below
  ``release_evidence``. A coasting slot **adopts** a tip reborn within ``gate_max_px x (1 + misses)``
  (at most twice ``gate_max_px``) of where it was lost, as RedTipTracker does: a fast stroke or a short
  dropout outruns the gate, and the stroke continues unless the other stick is unseen too (then it could
  be the other stick, and the stroke restarts). A slot coasting for ``takeover_s`` may otherwise be taken
  by any live track (fast reacquisition, with a reset). A bound track that has never moved since its birth
  yields at once to a moving unbound track of similar rank (within ``challenge_margin``): at start-up a
  static red object and two sticks held still look alike, and the first motion decides; the new pair is
  then ordered like a joint binding. An unbound track ranking ``challenge_margin`` above the weaker bound
  one for ``challenge_frames`` frames takes that slot. Every other (re)binding requests an identity reset.
* **Blur**: a bound track that missed its gate may take an unclaimed candidate within twice its gate
  (``RECOVERY_GATE_FACTOR``, capped at ``gate_max_px``): a stroke starting from rest outruns a gate sized for
  stillness. A streak scores low with the verifier (it learned still caps), so a bound, established tip
  measured OBSERVED within ``WEAK_AFTER_S``, whose candidate has ``q < measure_quality`` but moved at least
  ``WEAK_STEP_PX``, is measured as WEAK (``weak_confidence``) for at most ``max_weak_frames`` consecutive
  frames, its evidence held. WEAK only continues a measured cap; it never starts a measurement.
* **Output per slot**: OBSERVED (measured, ``observed_confidence``) only with ``ev >= measure_evidence``
  and this frame's ``q >= measure_quality``; WEAK as above; otherwise LOW_EVIDENCE (seen, not trusted: no
  stroke uses it);
  CLIPPED for a cut cap; PREDICTED (no coordinates) while coasting; NO_TRACK when unbound. AMBIGUOUS when the
  two bound tracks could exchange their candidates within ``ambiguity_margin``. When that episode ends the
  two tracks take the slots whose last measurements they are nearer to (tips that touched and parted return
  to their own sides, consistent with the larger-x = LEFT convention; motion predictions mean nothing
  through a merge) and both slots reset.

Causal: :meth:`RedTipEvidenceTracker.step` sees only the current candidates and its own past. Coordinates
are ROI pixels; times are ``t_capture`` seconds.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from spacedrums.contracts import HandId
from spacedrums.stick.red_tip import RedBlob, RedTipSettings
from spacedrums.stick.red_tip_tracker import SLOTS, SlotState, TrackerFrame, _assign

GATE_GROWTH_AFTER_S = 0.05
ACTIVITY_WINDOW_S = 1.0  # "moving" = moved move_px within this window
QUALITY_COST = 0.3  # association prefers the better candidate among equally near ones
MISS_DECAY = 0.85  # evidence factor per missed frame
FRAGMENT_PX = 12.0  # no birth this close to a track observed in the same frame
WEAK_STEP_PX = 8.0  # a low-quality candidate continues a bound tip as WEAK only while it moves this much ...
WEAK_AFTER_S = 0.2  # ... and only a tip measured OBSERVED this recently (WEAK never starts a measurement)
RECOVERY_GATE_FACTOR = 2.0  # a bound track that missed its gate may take an unclaimed candidate this much
# farther (still capped at gate_max_px): a stroke starting from rest outruns a gate sized for stillness
MAX_TRACKS = 16  # internal tracks (both sticks plus red distractors); births beyond it are skipped


@dataclass
class EvidenceTrack:
    track_id: int
    pos: np.ndarray
    t_obs: float
    born_t: float
    quality: float  # this frame's verifier quality (0 when clipped)
    evidence: float  # EMA of the quality
    clipped: bool
    area: float
    axis: tuple[float, float]
    vel: np.ndarray = field(default_factory=lambda: np.zeros(2))
    n_obs: int = 1
    hits: int = 1
    misses: int = 0
    confirmed: bool = False
    clip_run: int = 0
    better_run: int = 0
    weak: bool = False  # this frame continues a bound tip on a low-quality (blurred) candidate
    weak_run: int = 0
    observed_t: float | None = None  # last frame this track was measured OBSERVED in a slot
    anchor: np.ndarray | None = None  # where it last moved from ...
    moved_t: float = 0.0  # ... and when
    ever_moved: bool = False  # moved move_px at least once since birth
    weight: float = 1.0  # stillness weight in [still_floor, 1]

    def __post_init__(self) -> None:
        if self.anchor is None:
            self.anchor = np.array(self.pos, float)
            self.moved_t = self.t_obs
        self.clip_run = int(self.clipped)

    def predict(self, t: float, s: RedTipSettings) -> tuple[np.ndarray, float]:
        tau = max(0.0, t - self.t_obs)
        tau_p = min(tau, s.max_predict_s)
        speed = math.hypot(float(self.vel[0]), float(self.vel[1]))
        growth = s.gate_growth_px_s * max(0.0, tau - GATE_GROWTH_AFTER_S)
        r = s.gate_px + s.gate_speed_gain * speed * tau_p + growth
        return self.pos + self.vel * tau_p, min(s.gate_max_px, r)

    def observe(self, blob: RedBlob, t: float, s: RedTipSettings, *, bound: bool = False) -> None:
        c = np.asarray(blob.center, float)
        step = math.dist(c, self.pos)
        tau = t - self.t_obs
        if tau > 0:
            v = (c - self.pos) / tau
            self.vel = v if self.n_obs == 1 else s.velocity_alpha * v + (1 - s.velocity_alpha) * self.vel
        self.pos, self.t_obs, self.area, self.axis = c, t, blob.area, blob.axis
        self.n_obs += 1
        self.hits += 1
        self.misses = 0
        self.clipped = blob.clipped
        self.clip_run = self.clip_run + 1 if blob.clipped else 0
        if math.dist(c, self.anchor) >= s.move_px:
            self.anchor, self.moved_t, self.ever_moved = c.copy(), t, True
        still = t - self.moved_t
        fade = 1.0 - (still - s.still_s) / s.still_decay_s
        self.weight = 1.0 if still <= s.still_s else max(s.still_floor, fade)
        self.quality = 0.0 if blob.clipped else blob.score
        # Motion blur smears a cap into a streak the verifier scores low (it learned still caps): a bound,
        # established tip that keeps moving continues on it for at most max_weak_frames frames, its evidence
        # held, like the colour detector's weak re-detection.
        recent = self.observed_t is not None and t - self.observed_t <= WEAK_AFTER_S
        self.weak = (bound and recent and not blob.clipped and self.quality < s.measure_quality
                     and step >= WEAK_STEP_PX and self.evidence >= s.measure_evidence
                     and self.weak_run < s.max_weak_frames)
        self.weak_run = self.weak_run + 1 if self.weak else 0
        if not self.weak:
            self.evidence = s.evidence_alpha * self.quality + (1 - s.evidence_alpha) * self.evidence

    def moving(self, t: float) -> bool:
        return self.ever_moved and t - self.moved_t <= ACTIVITY_WINDOW_S

    @property
    def rank(self) -> float:
        """Evidence weighted by stillness: slot competition (binding order, challenges)."""
        return self.evidence * self.weight

    def miss(self) -> None:
        self.misses += 1
        self.hits = 0
        self.evidence *= MISS_DECAY


class RedTipEvidenceTracker:
    def __init__(self, settings: RedTipSettings | None = None) -> None:
        self.settings = settings or RedTipSettings()
        self.counters: Counter = Counter()
        self.reset()

    def reset(self) -> None:
        self.tracks: list[EvidenceTrack] = []
        self.slots: dict[HandId, int | None] = dict.fromkeys(SLOTS)
        self.last: dict[HandId, tuple[float, np.ndarray] | None] = dict.fromkeys(SLOTS)  # last measurement
        self.next_id = 1
        self.t_last: float | None = None
        self.ambiguous = False

    def step(self, t: float, blobs, *, roi_size: tuple[int, int], **_ignored) -> TrackerFrame:
        """One frame of verified candidates (``RedBlob.score`` = quality). Extra keyword arguments of
        :meth:`RedTipTracker.step` (``weak``, ``grips``, ``cores``) are accepted and ignored."""
        s = self.settings
        if self.t_last is not None and t <= self.t_last:
            raise ValueError("tracker frames must have strictly increasing timestamps")
        self.t_last = t
        blobs = list(blobs)
        tracks = self.tracks
        preds = [tr.predict(t, s) for tr in tracks]
        cost = np.full((len(tracks), len(blobs)), np.inf)
        for i, (p, r) in enumerate(preds):
            for j, b in enumerate(blobs):
                d = math.dist(b.center, p)
                if d <= r:
                    cost[i, j] = (d / r) ** 2 + QUALITY_COST * (1.0 - b.score)
        match = _assign(cost)
        bound = {tid for tid in self.slots.values() if tid is not None}
        lost = [i for i, tr in enumerate(tracks) if tr.track_id in bound and i not in match]
        free = [j for j in range(len(blobs)) if j not in match.values()]
        if lost and free:  # recovery: a bound tip whose stroke outran its gate (never beyond gate_max_px)
            reach = {i: min(s.gate_max_px, RECOVERY_GATE_FACTOR * preds[i][1]) for i in lost}
            extra = np.full((len(lost), len(free)), np.inf)
            for a, i in enumerate(lost):
                for b, j in enumerate(free):
                    d = math.dist(blobs[j].center, preds[i][0])
                    if d <= reach[i]:
                        extra[a, b] = (d / reach[i]) ** 2
            for a, b in _assign(extra).items():
                match[lost[a]] = free[b]
                self.counters["RECOVERED"] += 1
        seen = {tracks[i].track_id: j for i, j in match.items()}
        ambiguous = self._ambiguous(tracks, preds, blobs, seen)
        survivors = []
        for tr in tracks:
            if tr.track_id in seen:
                tr.observe(blobs[seen[tr.track_id]], t, s, bound=tr.track_id in bound)
                if not tr.confirmed and tr.hits >= s.birth_frames:
                    tr.confirmed = True
                    self.counters["CONFIRMED"] += 1
                survivors.append(tr)
                continue
            tr.miss()
            if tr.confirmed and t - tr.t_obs <= s.max_coast_s:
                survivors.append(tr)
            else:
                self.counters["LOST" if tr.confirmed else "TENTATIVE_DROPPED"] += 1
        self.tracks = survivors
        claimed = set(match.values())
        for j, b in enumerate(blobs):
            if j in claimed or b.score < s.birth_quality or b.clipped:
                continue
            if any(math.dist(b.center, tr.pos) < FRAGMENT_PX for tr in self.tracks if tr.t_obs == t):
                self.counters["FRAGMENT_SUPPRESSED"] += 1
                continue
            if len(self.tracks) >= MAX_TRACKS:
                self.counters["BIRTH_SKIPPED_FULL"] += 1
                continue
            self.tracks.append(EvidenceTrack(self.next_id, np.asarray(b.center, float), t, t, b.score,
                                             b.score, b.clipped, b.area, b.axis))
            self.next_id += 1
            self.counters["BIRTHS"] += 1
        resets = self._bind(t, roi_size)
        if self.ambiguous and not ambiguous:
            self._resolve_after_ambiguity(t)
            if s.reset_after_ambiguity:
                resets |= {h for h in SLOTS if self.slots[h] is not None}
                self.counters["AMBIGUITY_RESETS"] += 1
        if ambiguous:
            self.counters["AMBIGUOUS_FRAMES"] += 1
            if not self.ambiguous:
                self.counters["AMBIGUITY_EPISODES"] += 1
        self.ambiguous = ambiguous
        self.counters["IDENTITY_RESETS"] += len(resets)
        return TrackerFrame(t, self._states(t, ambiguous), frozenset(resets), ambiguous, self._summary(t))

    def _ambiguous(self, tracks, preds, blobs, seen) -> bool:
        """The two bound tracks could exchange this frame's candidates at little extra cost."""
        index = {tr.track_id: i for i, tr in enumerate(tracks)}
        pair = [self.slots[h] for h in SLOTS]
        if not all(tid is not None and tid in index and tid in seen for tid in pair):
            return False
        (ia, ib), (ja, jb) = (index[pair[0]], index[pair[1]]), (seen[pair[0]], seen[pair[1]])

        def c(i, j):
            p, r = preds[i]
            return (math.dist(blobs[j].center, p) / r) ** 2

        return c(ia, jb) + c(ib, ja) - (c(ia, ja) + c(ib, jb)) < self.settings.ambiguity_margin

    def _remembered(self, tr: EvidenceTrack, t: float) -> bool:
        """``tr`` is where a slot measured recently: a reacquired stick, not a first sighting."""
        s = self.settings
        return any(last is not None and t - last[0] <= s.identity_memory_s
                   and math.dist(tr.pos, last[1]) <= s.identity_memory_px for last in self.last.values())

    def _resolve_after_ambiguity(self, t: float) -> None:
        live = {tr.track_id: tr for tr in self.tracks}
        tracks = [live.get(self.slots[h]) if self.slots[h] is not None else None for h in SLOTS]
        if any(tr is None or tr.t_obs != t for tr in tracks) or any(self.last[h] is None for h in SLOTS):
            return
        (a, b), (la, lb) = tracks, (self.last[SLOTS[0]][1], self.last[SLOTS[1]][1])
        if math.dist(a.pos, lb) + math.dist(b.pos, la) < math.dist(a.pos, la) + math.dist(b.pos, lb):
            self.slots[SLOTS[0]], self.slots[SLOTS[1]] = b.track_id, a.track_id
            self.counters["REASSIGNED_AFTER_AMBIGUITY"] += 1

    def _bind(self, t: float, roi_size: tuple[int, int]) -> set[HandId]:
        s = self.settings
        live = {tr.track_id: tr for tr in self.tracks}
        resets: set[HandId] = set()
        for h in SLOTS:
            tid = self.slots[h]
            if tid is None:
                continue
            tr = live.get(tid)
            if tr is None:
                self.slots[h] = None
                self.counters["SLOT_LOST"] += 1
            elif tr.clip_run >= s.clip_release_frames:
                self.slots[h] = None
                self.counters["RELEASED_CLIPPED"] += 1
            elif tr.evidence < s.release_evidence:
                self.slots[h] = None
                self.counters["RELEASED_EVIDENCE"] += 1

        def bind(h, tr):
            self.slots[h] = tr.track_id
            resets.add(h)
            self.counters["BINDS"] += 1

        def pool():
            bound = {tid for tid in self.slots.values() if tid is not None}
            return sorted((tr for tr in self.tracks if tr.t_obs == t and tr.track_id not in bound
                           and not tr.clipped and tr.evidence >= s.bind_evidence
                           and (tr.confirmed
                                or (tr.quality >= s.instant_quality and self._remembered(tr, t)))),
                          key=lambda tr: (not tr.moving(t), -tr.rank, tr.track_id))

        for h in SLOTS:  # a track that never moved yields to a moving tip of similar rank
            tid = self.slots[h]
            if tid is None or live[tid].ever_moved:
                continue
            movers = [tr for tr in pool() if tr.confirmed and tr.moving(t)
                      and tr.rank >= live[tid].rank - s.challenge_margin]
            if movers:
                bind(h, movers[0])
                self.counters["STATIC_RELEASES"] += 1
                other = SLOTS[1] if h is SLOTS[0] else SLOTS[0]
                if self.slots[other] is not None:  # the pair is new: order it like a joint binding
                    a, b = live[self.slots[HandId.LEFT]], live[self.slots[HandId.RIGHT]]
                    if a.pos[0] < b.pos[0]:
                        self.slots[HandId.LEFT], self.slots[HandId.RIGHT] = b.track_id, a.track_id
                    resets |= {HandId.LEFT, HandId.RIGHT}
        for h in SLOTS:  # a coasting slot adopts a tip reborn near where it was lost (a short gap)
            tid = self.slots[h]
            if tid is None or live[tid].t_obs == t:
                continue
            old = live[tid]
            reach = min(2 * s.gate_max_px, s.gate_max_px * (1 + old.misses))
            near = [tr for tr in pool()
                    if tr.born_t > old.t_obs and math.dist(tr.pos, old.pos) <= reach]
            if not near:
                continue
            pick = min(near, key=lambda tr: math.dist(tr.pos, old.pos))
            if pick.n_obs == 1:  # carry the motion across the gap into the new track's gating
                pick.vel = (pick.pos - old.pos) / max(1e-3, t - old.t_obs)
            other = self.slots[SLOTS[1] if h is SLOTS[0] else SLOTS[0]]
            self.slots[h] = pick.track_id
            self.counters["BINDS"] += 1
            self.counters["ADOPTED"] += 1
            if other is None or live[other].t_obs != t:  # it could be the other stick: restart strokes
                resets.add(h)
            self.tracks.remove(old)
            live.pop(tid)
        pool = pool()
        coasting = [h for h in SLOTS
                    if self.slots[h] is not None and t - live[self.slots[h]].t_obs >= s.takeover_s]
        free = [h for h in SLOTS if self.slots[h] is None or (pool and h in coasting)]
        if len(free) == 2 and len(pool) >= 2:
            a, b = pool[0], pool[1]
            left, right = (a, b) if a.pos[0] >= b.pos[0] else (b, a)
            bind(HandId.LEFT, left)
            bind(HandId.RIGHT, right)
            self.counters["TAKEOVERS"] += sum(h in coasting for h in SLOTS)
        elif free and pool:
            tr = pool[0]
            h = free[0]
            if len(free) == 2:
                memory = [(math.dist(tr.pos, self.last[x][1]), x) for x in free
                          if self.last[x] is not None and t - self.last[x][0] <= s.identity_memory_s]
                if memory and min(memory)[0] <= s.identity_memory_px:
                    h = min(memory)[1]
                else:
                    h = HandId.LEFT if tr.pos[0] >= roi_size[0] / 2 else HandId.RIGHT
            self.counters["TAKEOVERS"] += h in coasting
            bind(h, tr)
        bound = {tid for tid in self.slots.values() if tid is not None}
        held = [h for h in SLOTS if self.slots[h] in live]
        for tr in self.tracks:  # a clearly better unbound track replaces the weaker bound one
            weakest = min(held, key=lambda h: live[self.slots[h]].rank) if len(held) == 2 else None
            if (tr.track_id in bound or not tr.confirmed or tr.t_obs != t or tr.clipped or weakest is None
                    or tr.rank <= live[self.slots[weakest]].rank + s.challenge_margin):
                tr.better_run = 0
                continue
            tr.better_run += 1
            if tr.better_run >= s.challenge_frames:
                tr.better_run = 0
                bind(weakest, tr)
                bound = {tid for tid in self.slots.values() if tid is not None}
                self.counters["CHALLENGED"] += 1
        return resets

    def _states(self, t: float, ambiguous: bool) -> dict[HandId, SlotState]:
        s = self.settings
        live = {tr.track_id: tr for tr in self.tracks}
        states = {}
        for h in SLOTS:
            tid = self.slots[h]
            tr = live.get(tid) if tid is not None else None
            if tr is None:
                states[h] = SlotState(h, "NO_TRACK", None, None, None, 0.0, 0)
                continue
            if tr.t_obs != t:
                p, _ = tr.predict(t, s)
                states[h] = SlotState(h, "PREDICTED", tid, None, (float(p[0]), float(p[1])), 0.0, tr.misses)
                continue
            tip = (float(tr.pos[0]), float(tr.pos[1]))
            confidence = 0.0
            if ambiguous:
                state = "AMBIGUOUS"
            elif tr.clipped:
                state = "CLIPPED"
            elif tr.weak:
                state, confidence = "WEAK", s.weak_confidence
                self.counters["WEAK_FRAMES"] += 1
            elif tr.evidence < s.measure_evidence or tr.quality < s.measure_quality:
                state = "LOW_EVIDENCE"
                self.counters["LOW_EVIDENCE_FRAMES"] += 1
            else:
                state, confidence = "OBSERVED", s.observed_confidence
                self.last[h] = (t, tr.pos.copy())
                tr.observed_t = t
            states[h] = SlotState(h, state, tid, tip, None, confidence, 0, tr.area, tr.axis)
        return states

    def _summary(self, t: float) -> tuple[dict, ...]:
        slot_of = {tid: str(h) for h, tid in self.slots.items() if tid is not None}
        return tuple({"id": tr.track_id, "slot": slot_of.get(tr.track_id), "confirmed": tr.confirmed,
                      "observed": tr.t_obs == t, "pos": (float(tr.pos[0]), float(tr.pos[1])),
                      "misses": tr.misses, "evidence": round(tr.evidence, 3), "rank": round(tr.rank, 3),
                      "quality": round(tr.quality, 3)} for tr in self.tracks)


__all__ = ["EvidenceTrack", "RedTipEvidenceTracker"]
