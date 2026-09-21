"""Post-session verification and the unusable-recording policy (Phase 06, Tasks 06.7 and 06.8).

``verify_session`` reads a recorded session directory (Phase 05 record-mode layout + the Phase 06
``metadata.json``) and produces one document (``verify.json``, ``schemas/session-verification.schema.json``):

* **checks** — file completeness, schema validity of the metadata, every stream header and every
  record, config-hash consistency (snapshot = metadata = every header), frame ordering / continuity
  (strictly increasing ``frame_id`` and ``t_capture``, ``t_capture <= t_frame_available``, no
  duplicate timestamps, every image file present, no orphan images), camera identity and ROI
  constancy, measured FPS vs the profile (tolerance tunable), drop / stall counts, per-record frame
  references, id references (commit -> candidate, audio event -> commit, timing STRIKE -> commit),
  zone ids vs the configured layout, the no-commit-while-not-VALID safety invariant, segment-marker
  integrity, per-segment tracking validity per relevant hand, hand-order flips (a heuristic proxy for
  swaps / crossings), the audio sync residual (pad condition), consent completeness;
* **quality** — the session quality report: frame counts, duration, delivered FPS, drops, stalls,
  duplicates, tracking coverage per hand and status, both-hands-VALID fraction, stick-tip presence,
  event counts per source / arm / zone, invalid records, metadata completeness, bytes on disk;
* **segments** — the same statistics per take plus the policy verdict per segment;
* **verdict** — ``ACCEPT | REVIEW | QUARANTINE`` with reasons, from the rule set of Task 06.8
  (segment-level exclusion: validity ratio below ``q_seg`` for the relevant hand(s), FPS deviation
  beyond tolerance, sync failure, operator-noted protocol violation; session-level: more than
  ``q_sess`` of the core segments excluded, consent incomplete, metadata unrecoverable), and the
  ``ExclusionRecord``s the policy produced (``schemas/exclusion-record.schema.json``).

Every threshold is a *candidate* (``VerifyThresholds``; the pilot distribution sets them, Task 06.10)
and is written into the document with its hash, so a verdict is reproducible. The document always
carries the session's classification label (SYNTHETIC / DEV CAPTURE / PILOT / PARTICIPANT); a
SYNTHETIC or DEV CAPTURE verdict is machinery evidence and never participant evidence. Nothing here
invents a measurement: a quantity that cannot be computed from the files is reported as ``null`` with
a reason.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from spacedrums import timing
from spacedrums.capture.stats import interval_stats
from spacedrums.config import config_hash as compute_config_hash
from spacedrums.contracts import (
    AudioEvent,
    CommittedStrike,
    FrameSample,
    HandObservation,
    StickObservation,
    StrikeCandidate,
    TimingRecord,
    TrackState,
    TrajectoryPrediction,
)
from spacedrums.contracts import schema as contract_schema
from spacedrums.data.audio_capture import onsets_on_t_mono, read_wav, sync_check
from spacedrums.data.metadata import (
    METADATA_FILENAME,
    ConsentStatus,
    SessionKind,
    SessionMetadata,
    classification_label,
    validate_metadata,
)
from spacedrums.data.protocol import CORE_TYPES, check_segment_markers
from spacedrums.data.recorder import segment_frame_ranges
from spacedrums.timing.logger import read_record_stream

VERIFICATION_SCHEMA_VERSION = "1.0"
EXCLUSION_SCHEMA_VERSION = "1.0"
VERIFY_FILENAME = "verify.json"
GENERATOR = {"tool": "spacedrums.data.validation", "version": "0.6.0"}

RECORD_STREAMS: dict[str, tuple[type, str]] = {
    "HandObservation": (HandObservation, "hand-observation"),
    "StickObservation": (StickObservation, "stick-observation"),
    "TrackState": (TrackState, "track-state"),
    "TrajectoryPrediction": (TrajectoryPrediction, "trajectory-prediction"),
    "StrikeCandidate": (StrikeCandidate, "strike-candidate"),
    "CommittedStrike": (CommittedStrike, "committed-strike"),
    "AudioEvent": (AudioEvent, "audio-event"),
}
REQUIRED_FILES = ("frames.jsonl", "timing.jsonl", "config.snapshot.yaml", METADATA_FILENAME)
HANDS = ("LEFT", "RIGHT")

# Checks whose FAIL quarantines the session (the rest degrade the verdict to REVIEW).
HARD_CHECKS = frozenset(
    {
        "V-FILES",
        "V-META-SCHEMA",
        "V-CONFIG-HASH",
        "V-HEADERS",
        "V-FRAMES-SCHEMA",
        "V-FRAME-ORDER",
        "V-FRAME-FILES",
        "V-RECORDS-SCHEMA",
        "V-CONSENT",
        "V-SESSION-POLICY",
    }
)


@dataclass(frozen=True)
class VerifyThresholds:
    """Candidate thresholds of the unusable-recording policy (Task 06.8). Set from the pilot
    distribution, then frozen; until then every value is a candidate and is recorded per verdict."""

    q_seg: float = 0.6  # candidate: min tracking validity ratio (VALID frames / frames) per relevant hand
    q_sess: float = 0.5  # candidate: fraction of core segments excluded that excludes the session
    fps_tolerance: float = 0.15  # candidate: relative deviation of delivered FPS from the profile value
    segment_fps_tolerance: float = 0.25  # candidate: per-segment tolerance (short blocks are noisier)
    drop_factor: float = 1.5  # Phase 02 gap definition (interval > drop_factor x nominal)
    stall_factor: float = 2.0  # Phase 02 stall definition
    max_drop_fraction: float = 0.05  # candidate: dropped / delivered per session before REVIEW
    max_stalls: int = 0  # candidate: stalls per session before REVIEW
    min_segment_frames: int = 5  # candidate: fewer frames -> segment excluded (NO_FRAMES / too short)
    sync_window_s: float = 0.5  # matching window operator marker <-> onset
    sync_residual_max_s: float = 0.05  # candidate: max |residual - mean| before sync failure
    sync_min_matched: int = 2  # candidate: start + end marker at least
    schema_sample: int | None = None  # None = validate every record against its JSON Schema

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def hash(self) -> str:
        return (
            "sha256:"
            + hashlib.sha256(
                json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )

    @classmethod
    def from_file(cls, path: str | Path) -> VerifyThresholds:
        d = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"unknown threshold keys: {sorted(unknown)}")
        return cls(**d)


@dataclass
class Check:
    id: str
    status: str  # PASS | FAIL | WARN | SKIP
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "status": self.status, "detail": self.detail}


class _Report:
    def __init__(self) -> None:
        self.checks: list[Check] = []

    def add(self, cid: str, status: str, detail: str) -> None:
        self.checks.append(Check(cid, status, detail))

    def ok(self, cid: str, detail: str = "") -> None:
        self.add(cid, "PASS", detail)

    def fail(self, cid: str, detail: str) -> None:
        self.add(cid, "FAIL", detail)

    def warn(self, cid: str, detail: str) -> None:
        self.add(cid, "WARN", detail)

    def skip(self, cid: str, detail: str) -> None:
        self.add(cid, "SKIP", detail)


# ----------------------------------------------------------------------------- helpers


def _fraction(num: int, den: int) -> float | None:
    return (num / den) if den else None


def _safe_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as e:
        return None, f"{path.name}: {e}"


def _validate_records(
    name: str, records: Sequence[dict[str, Any]], cls: type, stem: str, sample: int | None
) -> list[str]:
    """Dataclass round-trip for every record (invariants) + JSON Schema for every (or a sample)."""
    problems: list[str] = []
    for i, r in enumerate(records):
        try:
            cls.from_dict(r)
        except (ValueError, KeyError, TypeError) as e:
            problems.append(f"{name}[{i}]: {e}")
            if len(problems) >= 20:
                break
    step = 1 if sample is None or sample <= 0 else max(1, len(records) // sample)
    for i in range(0, len(records), step):
        errs = contract_schema.errors(stem, records[i])
        if errs:
            problems.append(f"{name}[{i}] schema: {errs[0]}")
            if len(problems) >= 20:
                break
    return problems


def _by_hand_zone(commits: Sequence[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in commits:
        key = f"{c['arm']}:{c['hand_id']}:{c['zone_id']}"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def hand_order_flips(hands: Sequence[dict[str, Any]]) -> tuple[int, int]:
    """(flips, both_present_frames): frames where the left/right wrist x-order changed relative to the
    previous frame with both hands present. A heuristic proxy for identity swaps and hand crossings —
    reported, never interpreted as a swap count."""
    per_frame: dict[int, dict[str, float]] = {}
    for h in hands:
        if h.get("present") and h.get("landmarks"):
            per_frame.setdefault(int(h["frame_id"]), {})[h["hand_id"]] = float(h["landmarks"][0][0])
    prev: int | None = None
    flips = 0
    both = 0
    for fid in sorted(per_frame):
        d = per_frame[fid]
        if "LEFT" not in d or "RIGHT" not in d:
            continue
        both += 1
        sign = 1 if d["LEFT"] > d["RIGHT"] else -1
        if prev is not None and sign != prev:
            flips += 1
        prev = sign
    return flips, both


def commits_during_non_valid(commits: Sequence[dict[str, Any]], tracks: Sequence[dict[str, Any]]) -> int:
    status = {(t["frame_id"], t["hand_id"]): t["status"] for t in tracks}
    return sum(1 for c in commits if status.get((c["frame_id"], c["hand_id"])) != "VALID")


def _dir_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0


# ----------------------------------------------------------------------------- main entry


def verify_session(
    session_dir: str | Path,
    *,
    thresholds: VerifyThresholds | None = None,
    write: bool = True,
    git_sha: str | None = None,
) -> dict[str, Any]:
    """Verify one session directory; returns (and by default writes) the ``verify.json`` document."""
    d = Path(session_dir)
    th = thresholds or VerifyThresholds()
    rep = _Report()
    reasons: list[str]
    quality: dict[str, Any] = {}
    segments_out: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []

    # ---- files ---------------------------------------------------------------------------
    missing = [f for f in REQUIRED_FILES if not (d / f).exists()]
    if not (d / "frames").is_dir():
        missing.append("frames/")
    for name in RECORD_STREAMS:
        if not (d / "records" / f"{name}.jsonl").exists():
            missing.append(f"records/{name}.jsonl")
    if missing:
        rep.fail("V-FILES", "missing: " + ", ".join(missing))
    else:
        rep.ok("V-FILES", "all required files present")

    # ---- metadata ------------------------------------------------------------------------
    meta_dict, err = (
        _safe_json(d / METADATA_FILENAME) if (d / METADATA_FILENAME).exists() else (None, "absent")
    )
    if meta_dict is None:
        rep.fail("V-META-SCHEMA", f"metadata unrecoverable: {err}")
        kind = SessionKind.DEV_CAPTURE
        session_id = d.name
        meta: SessionMetadata | None = None
    else:
        errs = validate_metadata(meta_dict)
        if errs:
            rep.fail("V-META-SCHEMA", "; ".join(errs[:5]))
        else:
            rep.ok("V-META-SCHEMA", "metadata.json valid (schema + invariants)")
        try:
            kind = SessionKind(meta_dict.get("session_kind", "DEV_CAPTURE"))
        except ValueError:
            kind = SessionKind.DEV_CAPTURE
        session_id = str(meta_dict.get("session_id", d.name))
        meta = SessionMetadata(meta_dict)

    # ---- config snapshot / hash ----------------------------------------------------------
    cfg: dict[str, Any] | None = None
    snapshot_hash: str | None = None
    if (d / "config.snapshot.yaml").exists():
        try:
            cfg = yaml.safe_load((d / "config.snapshot.yaml").read_text(encoding="utf-8"))
            snapshot_hash = compute_config_hash(cfg)
        except (OSError, ValueError, yaml.YAMLError) as e:
            rep.fail("V-CONFIG-HASH", f"config.snapshot.yaml unreadable: {e}")
    headers: dict[str, dict[str, Any]] = {}
    records: dict[str, list[dict[str, Any]]] = {}
    for name in list(RECORD_STREAMS) + ["TimingRecord"]:
        path = d / ("timing.jsonl" if name == "TimingRecord" else f"records/{name}.jsonl")
        if not path.exists():
            records[name] = []
            continue
        try:
            headers[name], records[name] = read_record_stream(path)
        except (OSError, ValueError) as e:
            rep.fail("V-HEADERS", f"{path.name}: {e}")
            records[name] = []
    if snapshot_hash is not None and meta_dict is not None:
        mismatches = []
        if meta_dict.get("config_hash") != snapshot_hash:
            mismatches.append(f"metadata {meta_dict.get('config_hash')} != snapshot {snapshot_hash}")
        for name, h in headers.items():
            if h.get("config_hash") != snapshot_hash:
                mismatches.append(f"{name} header {h.get('config_hash')}")
        if mismatches:
            rep.fail("V-CONFIG-HASH", "; ".join(mismatches[:4]))
        else:
            rep.ok("V-CONFIG-HASH", f"snapshot, metadata and {len(headers)} headers agree: {snapshot_hash}")
    elif not any(c.id == "V-CONFIG-HASH" for c in rep.checks):
        rep.fail("V-CONFIG-HASH", "cannot compare (snapshot or metadata missing)")

    # ---- headers -------------------------------------------------------------------------
    hdr_problems: list[str] = []
    for name, h in headers.items():
        errs = contract_schema.errors("record-stream-header", h)
        if errs:
            hdr_problems.append(f"{name}: {errs[0]}")
        if h.get("record_type") != name:
            hdr_problems.append(f"{name}: header record_type {h.get('record_type')}")
        if meta_dict is not None:
            if h.get("session_id") != meta_dict.get("session_id"):
                hdr_problems.append(f"{name}: session_id {h.get('session_id')} != metadata")
            if h.get("git_sha") != meta_dict.get("git_sha"):
                hdr_problems.append(f"{name}: git_sha differs from metadata")
            if h.get("clock_id") != meta_dict.get("clock_id"):
                hdr_problems.append(f"{name}: clock_id differs from metadata")
    if not any(c.id == "V-HEADERS" for c in rep.checks):
        if hdr_problems:
            rep.fail("V-HEADERS", "; ".join(hdr_problems[:5]))
        else:
            rep.ok("V-HEADERS", f"{len(headers)} stream headers valid and consistent")

    # ---- frames --------------------------------------------------------------------------
    frames: list[dict[str, Any]] = []
    frame_problems: list[str] = []
    if (d / "frames.jsonl").exists():
        for i, line in enumerate((d / "frames.jsonl").read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                FrameSample.from_dict(rec)
                frames.append(rec)
            except (ValueError, KeyError, TypeError) as e:
                frame_problems.append(f"line {i}: {e}")
                if len(frame_problems) >= 10:
                    break
        step = 1 if th.schema_sample is None else max(1, len(frames) // max(1, th.schema_sample))
        for i in range(0, len(frames), step):
            errs = contract_schema.errors("frame-sample", frames[i])
            if errs:
                frame_problems.append(f"frame {i} schema: {errs[0]}")
                break
    if frame_problems:
        rep.fail("V-FRAMES-SCHEMA", "; ".join(frame_problems[:5]))
    elif frames:
        rep.ok("V-FRAMES-SCHEMA", f"{len(frames)} FrameSample records valid")
    else:
        rep.fail("V-FRAMES-SCHEMA", "no frames")

    order_problems: list[str] = []
    dup_t = 0
    gaps_in_ids = 0
    for a, b in zip(frames, frames[1:], strict=False):
        if b["frame_id"] <= a["frame_id"]:
            order_problems.append(f"frame_id {b['frame_id']} after {a['frame_id']}")
        elif b["frame_id"] != a["frame_id"] + 1:
            gaps_in_ids += 1
        if b["t_capture"] <= a["t_capture"]:
            if b["t_capture"] == a["t_capture"]:
                dup_t += 1
            order_problems.append(f"t_capture not increasing at frame {b['frame_id']}")
        if b["t_frame_available"] < b["t_capture"]:
            order_problems.append(f"t_frame_available < t_capture at frame {b['frame_id']}")
        if len(order_problems) >= 10:
            break
    if order_problems:
        rep.fail("V-FRAME-ORDER", "; ".join(order_problems[:5]))
    elif frames:
        rep.ok(
            "V-FRAME-ORDER",
            f"frame_id and t_capture strictly increasing; {gaps_in_ids} frame_id gaps "
            "(capture assigns consecutive ids; a gap means a frame was lost after capture)",
        )
    if gaps_in_ids:
        rep.warn("V-FRAME-CONTINUITY", f"{gaps_in_ids} gaps in frame_id numbering")
    else:
        rep.ok("V-FRAME-CONTINUITY", "frame ids consecutive")

    missing_images = 0
    for f in frames:
        ref = f.get("image_ref", {})
        if ref.get("kind") == "FILE" and not (d / ref["path"]).exists():
            missing_images += 1
    n_pngs = len(list((d / "frames").glob("*.png"))) if (d / "frames").is_dir() else 0
    orphans = n_pngs - (len(frames) - missing_images)
    if missing_images or orphans:
        rep.fail(
            "V-FRAME-FILES",
            f"{missing_images} referenced images missing; {orphans} image files not referenced",
        )
    else:
        rep.ok("V-FRAME-FILES", f"{n_pngs} image files, all referenced exactly once")

    # camera identity / ROI
    cams = {f["camera_profile_id"] for f in frames}
    rois = {tuple(f["roi_px"]) for f in frames}
    cam_problems = []
    if len(cams) > 1:
        cam_problems.append(f"multiple camera_profile_id values {sorted(cams)}")
    if len(rois) > 1:
        cam_problems.append(f"ROI changed during the session ({len(rois)} values)")
    if meta_dict is not None and frames:
        if meta_dict.get("camera_profile_id") not in cams:
            cam_problems.append(
                f"metadata camera_profile_id {meta_dict.get('camera_profile_id')} "
                f"not in frames {sorted(cams)}"
            )
        if tuple(meta_dict.get("roi_px", ())) not in rois:
            cam_problems.append("metadata roi_px differs from the frames")
    if cam_problems:
        rep.fail("V-CAMERA", "; ".join(cam_problems))
    elif frames:
        rep.ok("V-CAMERA", f"camera_profile_id {next(iter(cams))}, ROI constant {list(next(iter(rois)))}")

    # ---- FPS / drops / stalls ------------------------------------------------------------
    nominal_fps: float | None = None
    nominal_src = "none"
    if cfg and "camera_profile" in cfg:
        cp = cfg["camera_profile"]
        nfm = cp.get("native_fps_measured")
        if isinstance(nfm, dict) and nfm.get("value_fps"):
            nominal_fps, nominal_src = float(nfm["value_fps"]), f"MEASURED native FPS ({nfm.get('run_id')})"
        elif cp.get("requested_fps"):
            nominal_fps, nominal_src = (
                float(cp["requested_fps"]),
                "REQUESTED mode (no measured native FPS in the profile)",
            )
    t_caps = [float(f["t_capture"]) for f in frames]
    delivered = len(frames)
    dropped = sum(int(f["dropped_since_last"]) for f in frames)
    fps_measured: float | None = None
    stalls = gaps = 0
    duration = (t_caps[-1] - t_caps[0]) if len(t_caps) > 1 else 0.0
    if len(t_caps) > 1 and not order_problems:
        st = interval_stats(
            t_caps,
            (1.0 / nominal_fps) if nominal_fps else None,
            drop_factor=th.drop_factor,
            stall_factor=th.stall_factor,
        )
        fps_measured, stalls, gaps = st.fps, st.n_stalls, st.n_gaps
        quality["intervals"] = {
            "p50_s": st.p50_s,
            "p99_s": st.p99_s,
            "max_s": st.max_s,
            "n_gaps": st.n_gaps,
            "n_stalls": st.n_stalls,
            "nominal_s": st.nominal_s,
        }
    if fps_measured is None:
        rep.skip("V-FPS", "fewer than two frames or broken ordering")
    elif nominal_fps is None:
        rep.warn("V-FPS", f"delivered {fps_measured:.2f} FPS; no profile value to compare with")
    else:
        dev = abs(fps_measured - nominal_fps) / nominal_fps
        msg = (
            f"delivered {fps_measured:.2f} FPS vs {nominal_fps:.2f} ({nominal_src}); "
            f"deviation {dev:.1%} (tol {th.fps_tolerance:.0%})"
        )
        if dev > th.fps_tolerance:
            rep.warn("V-FPS", msg)
        else:
            rep.ok("V-FPS", msg)
    drop_frac = _fraction(dropped, delivered + dropped)
    if delivered and drop_frac is not None and drop_frac > th.max_drop_fraction:
        rep.warn(
            "V-DROPS",
            f"{dropped} dropped of {delivered + dropped} ({drop_frac:.1%} > {th.max_drop_fraction:.0%})",
        )
    else:
        rep.ok("V-DROPS", f"{dropped} dropped frames ({0 if drop_frac is None else round(drop_frac, 4)})")
    if stalls > th.max_stalls:
        rep.warn("V-STALLS", f"{stalls} stalls (> {th.stall_factor} x nominal interval)")
    else:
        rep.ok("V-STALLS", f"{stalls} stalls, {gaps} gaps")

    # ---- records -------------------------------------------------------------------------
    rec_problems: list[str] = []
    for name, (cls, stem) in RECORD_STREAMS.items():
        rec_problems += _validate_records(name, records.get(name, []), cls, stem, th.schema_sample)
    rec_problems += _validate_records(
        "TimingRecord", records.get("TimingRecord", []), TimingRecord, "timing-record", th.schema_sample
    )
    if rec_problems:
        rep.fail("V-RECORDS-SCHEMA", "; ".join(rec_problems[:5]))
    else:
        n_rec = sum(len(v) for v in records.values())
        rep.ok(
            "V-RECORDS-SCHEMA",
            f"{n_rec} records valid (dataclass invariants + JSON Schema"
            + (
                ""
                if th.schema_sample is None
                else f", schema sampled every ~{len(frames) // max(1, th.schema_sample)}"
            )
            + ")",
        )

    frame_t = {int(f["frame_id"]): float(f["t_capture"]) for f in frames}
    ref_problems: list[str] = []
    for name in list(RECORD_STREAMS) + ["TimingRecord"]:
        if name == "AudioEvent":
            continue
        for r in records.get(name, []):
            fid = int(r["frame_id"])
            if fid not in frame_t:
                ref_problems.append(f"{name}: frame_id {fid} not in frames.jsonl")
            elif abs(float(r["t_capture"]) - frame_t[fid]) > 1e-9:
                ref_problems.append(f"{name}: t_capture of frame {fid} differs from frames.jsonl")
            if len(ref_problems) >= 10:
                break
    if ref_problems:
        rep.fail("V-RECORD-FRAMES", "; ".join(ref_problems[:5]))
    else:
        rep.ok("V-RECORD-FRAMES", "every record references an existing frame with the same t_capture")

    cand_ids = {c["candidate_id"] for c in records.get("StrikeCandidate", [])}
    strike_ids = {s["strike_id"] for s in records.get("CommittedStrike", [])}
    id_problems = [
        f"CommittedStrike {s['strike_id']} -> unknown candidate {s['candidate_id']}"
        for s in records.get("CommittedStrike", [])
        if s["candidate_id"] not in cand_ids
    ]
    id_problems += [
        f"AudioEvent -> unknown strike {e['strike_id']}"
        for e in records.get("AudioEvent", [])
        if e["strike_id"] not in strike_ids
    ]
    id_problems += [
        f"TimingRecord STRIKE -> unknown strike {t['strike_id']}"
        for t in records.get("TimingRecord", [])
        if t.get("kind") == "STRIKE" and t.get("strike_id") not in strike_ids
    ]
    if id_problems:
        rep.fail("V-REFS", "; ".join(id_problems[:5]))
    else:
        rep.ok(
            "V-REFS",
            f"{len(strike_ids)} commits, {len(cand_ids)} candidates, "
            f"{len(records.get('AudioEvent', []))} audio events cross-referenced",
        )

    # track state: exactly one per (frame, hand)
    seen: dict[tuple[int, str], int] = {}
    for t in records.get("TrackState", []):
        k = (int(t["frame_id"]), t["hand_id"])
        seen[k] = seen.get(k, 0) + 1
    dup_tracks = sum(1 for v in seen.values() if v > 1)
    missing_tracks = sum(1 for fid in frame_t for h in HANDS if (fid, h) not in seen)
    if dup_tracks or missing_tracks:
        rep.warn(
            "V-TRACK", f"{dup_tracks} duplicated and {missing_tracks} missing TrackState (frame, hand) pairs"
        )
    else:
        rep.ok("V-TRACK", "one TrackState per frame and hand")

    zone_ids = {z["zone_id"] for z in (cfg or {}).get("zones", [])}
    bad_zones = sorted(
        {
            r["zone_id"]
            for name in ("StrikeCandidate", "CommittedStrike")
            for r in records.get(name, [])
            if r["zone_id"] not in zone_ids
        }
    )
    if bad_zones and zone_ids:
        rep.fail("V-ZONES", f"zone ids not in the configured layout: {bad_zones}")
    elif zone_ids:
        rep.ok("V-ZONES", f"all event zone ids in the layout {sorted(zone_ids)}")
    else:
        rep.skip("V-ZONES", "no zones in the config snapshot")

    nv = commits_during_non_valid(records.get("CommittedStrike", []), records.get("TrackState", []))
    if nv:
        rep.fail(
            "V-SAFETY",
            f"{nv} commits on frames whose hand was not VALID "
            "(README section 8 violation; derived records regenerable)",
        )
    else:
        rep.ok("V-SAFETY", "0 commits on non-VALID frames")

    # ---- quality report ------------------------------------------------------------------
    tracks = records.get("TrackState", [])
    status_counts: dict[str, dict[str, int]] = {h: {} for h in HANDS}
    for t in tracks:
        sc = status_counts.setdefault(t["hand_id"], {})
        sc[t["status"]] = sc.get(t["status"], 0) + 1
    valid_per_frame: dict[int, set[str]] = {}
    for t in tracks:
        if t["status"] == "VALID":
            valid_per_frame.setdefault(int(t["frame_id"]), set()).add(t["hand_id"])
    both_valid = sum(1 for v in valid_per_frame.values() if len(v) == 2)
    hands_obs = records.get("HandObservation", [])
    sticks = records.get("StickObservation", [])
    flips, both_present = hand_order_flips(hands_obs)
    commits = records.get("CommittedStrike", [])
    cands = records.get("StrikeCandidate", [])
    meta_missing = []
    if meta_dict is not None:
        pm = meta_dict.get("participant_meta", {})
        meta_missing = [
            f"participant_meta.{k}"
            for k, v in pm.items()
            if v == "NOT_COLLECTED" and pm.get("source") != "NOT_APPLICABLE"
        ]
        for k in ("measured_fps", "capture_stats"):
            if meta_dict.get(k) is None:
                meta_missing.append(k)
        if meta_dict.get("lighting", {}).get("mean_luminance_auto") is None:
            meta_missing.append("lighting.mean_luminance_auto")
    frames_bytes = _dir_bytes(d / "frames")
    quality.update(
        {
            "label": classification_label(kind),
            "frames": delivered,
            "duration_s": duration,
            "fps_delivered": fps_measured,
            "fps_nominal": nominal_fps,
            "fps_nominal_source": nominal_src,
            "dropped": dropped,
            "drop_fraction": drop_frac,
            "stalls": stalls,
            "gaps": gaps,
            "duplicate_timestamps": dup_t,
            "frame_id_gaps": gaps_in_ids,
            "missing_images": missing_images,
            "orphan_images": max(0, orphans),
            "tracking": {
                h: {
                    "counts": status_counts.get(h, {}),
                    "valid_fraction": _fraction(status_counts.get(h, {}).get("VALID", 0), delivered),
                }
                for h in HANDS
            },
            "both_hands_valid_fraction": _fraction(both_valid, delivered),
            "hand_present_fraction": {
                h: _fraction(sum(1 for o in hands_obs if o["hand_id"] == h and o["present"]), delivered)
                for h in HANDS
            },
            "stick_tip_present_fraction": {
                h: _fraction(sum(1 for o in sticks if o["hand_id"] == h and o["present"]), delivered)
                for h in HANDS
            },
            "hand_order_flips": {
                "flips": flips,
                "both_present_frames": both_present,
                "note": "heuristic proxy for swaps/crossings",
            },
            "events": {
                "candidates_by_source": {
                    src: sum(1 for c in cands if c["source"] == src) for src in ("REACTIVE", "RULE", "MODEL")
                },
                "commits_by_arm": {
                    arm: sum(1 for c in commits if c["arm"] == arm)
                    for arm in sorted({c["arm"] for c in commits})
                },
                "commits_shadow": sum(1 for c in commits if c["shadow"]),
                "commits_sounding": sum(1 for c in commits if not c["shadow"]),
                "commits_by_arm_hand_zone": _by_hand_zone(commits),
                "audio_events": len(records.get("AudioEvent", [])),
                "predictions": len(records.get("TrajectoryPrediction", [])),
                "commits_during_non_valid": nv,
                "note": "integrity / coverage statistics only; never accuracy "
                "(phase document: no strike counts as accuracy)",
            },
            "invalid_records": len(rec_problems) + len(frame_problems),
            "metadata_incomplete_fields": meta_missing,
            "storage": {
                "frames_bytes": frames_bytes,
                "bytes_per_frame": (frames_bytes / delivered) if delivered else None,
                "session_bytes": _dir_bytes(d),
            },
        }
    )

    # ---- segments ------------------------------------------------------------------------
    seg_markers = meta_dict.get("segments", []) if meta_dict else []
    mp = check_segment_markers([s for s in seg_markers if s.get("t_end") is not None])
    if frames and seg_markers:
        t0, t1 = t_caps[0], t_caps[-1]
        for s in seg_markers:
            if s.get("t_end") is not None and (s["t_start"] > t1 or s["t_end"] < t0):
                mp.append(f"{s['segment_id']}: outside the recorded frame range")
    if mp:
        rep.fail("V-SEGMENTS", "; ".join(mp[:5]))
    elif seg_markers:
        rep.ok(
            "V-SEGMENTS",
            f"{len(seg_markers)} segment markers monotone, non-overlapping, inside the recording",
        )
    else:
        rep.warn("V-SEGMENTS", "no segment markers (session not recorded with the guided protocol)")
    ranges = segment_frame_ranges(seg_markers, t_caps)
    frame_ids_sorted = [int(f["frame_id"]) for f in frames]
    track_by = {(int(t["frame_id"]), t["hand_id"]): t["status"] for t in tracks}
    n_core = n_core_excluded = 0
    for s in seg_markers:
        key = (s["segment_id"], int(s.get("take", 1)))
        stype = s.get("type")
        core = stype in {str(t) for t in CORE_TYPES}
        entry: dict[str, Any] = {
            "segment_id": s["segment_id"],
            "take": key[1],
            "type": stype,
            "status": s.get("status"),
            "relevant_hands": list(s.get("hands", HANDS)),
            "n_frames": 0,
            "duration_s": None,
            "fps_est": None,
            "dropped": 0,
            "tracking_validity": {h: None for h in HANDS},
            "commits": {},
            "verdict": "SKIPPED",
            "reasons": [],
        }
        seg_reasons: list[str] = []
        if s.get("status") in ("SKIPPED", "ABORTED") or key not in ranges:
            entry["reasons"] = [f"status {s.get('status')}"]
            segments_out.append(entry)
            continue
        lo, hi = ranges[key]
        fids = frame_ids_sorted[lo:hi]
        n = len(fids)
        entry["n_frames"] = n
        if n:
            seg_t = t_caps[lo:hi]
            dur = seg_t[-1] - seg_t[0]
            entry["duration_s"] = dur
            entry["fps_est"] = (n - 1) / dur if n > 1 and dur > 0 else None
            entry["dropped"] = sum(int(frames[i]["dropped_since_last"]) for i in range(lo, hi))
            for h in HANDS:
                entry["tracking_validity"][h] = (
                    sum(1 for fid in fids if track_by.get((fid, h)) == "VALID") / n
                )
            fid_set = set(fids)
            seg_commits = [c for c in commits if int(c["frame_id"]) in fid_set]
            entry["commits"] = {
                arm: sum(1 for c in seg_commits if c["arm"] == arm)
                for arm in sorted({c["arm"] for c in seg_commits})
            }
        if n < th.min_segment_frames:
            seg_reasons.append(f"only {n} frames (< {th.min_segment_frames})")
        for h in entry["relevant_hands"]:
            v = entry["tracking_validity"].get(h)
            if v is None or v < th.q_seg:
                seg_reasons.append(
                    f"tracking validity {h} {'n/a' if v is None else round(v, 3)} < q_seg {th.q_seg}"
                )
        if entry["fps_est"] is not None and nominal_fps:
            dev = abs(entry["fps_est"] - nominal_fps) / nominal_fps
            if dev > th.segment_fps_tolerance:
                seg_reasons.append(f"fps_est {entry['fps_est']:.2f} deviates {dev:.0%} from nominal")
        if s.get("notes") and "VIOLATION" in str(s.get("notes")).upper():
            seg_reasons.append("operator-noted protocol violation")
        if s.get("status") == "RETAKEN":
            seg_reasons.append("superseded by a later take (kept, flagged)")
        entry["reasons"] = seg_reasons
        entry["verdict"] = "EXCLUDE" if seg_reasons else "ACCEPT"
        if core and s.get("status") == "RECORDED":
            n_core += 1
            if seg_reasons:
                n_core_excluded += 1
        if seg_reasons:
            exclusions.append(
                exclusion_record(
                    session_id=session_id,
                    participant_id=str(meta_dict.get("participant_id", "DEV")) if meta_dict else "DEV",
                    level="SEGMENT",
                    segment_id=s["segment_id"],
                    take=key[1],
                    reason_codes=_reason_codes(seg_reasons),
                    reason_text="; ".join(seg_reasons),
                    thresholds_hash=th.hash,
                )
            )
        segments_out.append(entry)
    core_excl_frac = _fraction(n_core_excluded, n_core)
    if seg_markers:
        msg = f"{n_core_excluded}/{n_core} core takes excluded by the segment rules" + (
            f" ({core_excl_frac:.0%})" if core_excl_frac is not None else ""
        )
        if n_core_excluded:
            rep.warn("V-SEG-TRACKING", msg)
        else:
            rep.ok("V-SEG-TRACKING", msg)
    else:
        rep.skip("V-SEG-TRACKING", "no segments")
    rep.ok(
        "V-HANDSWAP",
        f"{flips} hand-order flips over {both_present} both-hands frames (heuristic proxy for swaps / "
        "crossings; reported for Phase 07 QC, crossings are cued by the OCCLUSION segment)",
    )

    # ---- audio sync (pad condition) ------------------------------------------------------
    sync: dict[str, Any] | None = None
    pad = meta_dict.get("pad_mic") if meta_dict else None
    if pad and pad.get("present"):
        track = pad.get("audio_track")
        wav = d / track["path"] if track else None
        if track is None or wav is None or not wav.exists():
            rep.fail("V-AUDIO", "pad condition declared but no audio track file")
        elif track.get("t_mono_first_sample") is None:
            rep.fail("V-AUDIO", "audio track has no t_mono mapping")
        else:
            x, sr = read_wav(wav)
            onsets = onsets_on_t_mono(x, sr, float(track["t_mono_first_sample"]))
            res = sync_check(
                [m["t_mono"] for m in pad.get("sync_markers", [])], onsets, window_s=th.sync_window_s
            )
            sync = res.to_dict()
            spread = (
                max(abs(r - res.residual_mean_s) for r in res.residuals_s)
                if res.residuals_s and res.residual_mean_s is not None
                else None
            )
            sync["residual_spread_max_s"] = spread
            sync["label"] = "audio/video alignment check; MEASURED only on a real session (pilot PENDING)"
            if res.n_matched < th.sync_min_matched:
                rep.fail("V-AUDIO", f"only {res.n_matched} of {res.n_markers} sync markers matched an onset")
            elif spread is not None and spread > th.sync_residual_max_s:
                rep.warn("V-AUDIO", f"sync residual spread {spread:.4f} s > {th.sync_residual_max_s} s")
            else:
                rep.ok("V-AUDIO", f"{res.n_matched}/{res.n_markers} markers matched; spread {spread}")
    else:
        rep.skip("V-AUDIO", "no pad+mic condition in this session")

    # ---- consent / classification ------------------------------------------------------
    if meta_dict is not None:
        cs = meta_dict.get("consent_status")
        if kind in (SessionKind.PARTICIPANT, SessionKind.PILOT):
            if cs == str(ConsentStatus.SIGNED) and meta_dict.get("consent_record_id"):
                rep.ok("V-CONSENT", f"consent SIGNED ({meta_dict['consent_record_id']})")
            else:
                rep.fail(
                    "V-CONSENT",
                    f"consent {cs} / record {meta_dict.get('consent_record_id')}: "
                    f"incomplete for a {kind} session",
                )
        else:
            rep.skip("V-CONSENT", f"{kind}: consent not applicable (never participant data)")
        if (d / "checklist.json").exists():
            rep.ok("V-CHECKLIST", "operator checklist file present")
        elif kind in (SessionKind.PARTICIPANT, SessionKind.PILOT):
            rep.warn("V-CHECKLIST", "no checklist.json (operator checklist not filed for this session)")
        else:
            rep.skip("V-CHECKLIST", f"{kind}: checklist not applicable")
    if meta_dict is not None and meta_dict.get("quality_flags"):
        rep.warn("V-FLAGS", "operator quality flags: " + ", ".join(meta_dict["quality_flags"]))

    # ---- session policy ------------------------------------------------------------------
    if core_excl_frac is not None and core_excl_frac > th.q_sess:
        rep.fail("V-SESSION-POLICY", f"{core_excl_frac:.0%} of core segments excluded > q_sess {th.q_sess}")
    elif n_core:
        rep.ok("V-SESSION-POLICY", f"{core_excl_frac:.0%} of core segments excluded (<= q_sess {th.q_sess})")
    else:
        rep.skip("V-SESSION-POLICY", "no recorded core segments to apply the session rule to")

    # ---- verdict -------------------------------------------------------------------------
    hard_fail = [c for c in rep.checks if c.status == "FAIL" and c.id in HARD_CHECKS]
    other_fail = [c for c in rep.checks if c.status == "FAIL" and c.id not in HARD_CHECKS]
    warns = [c for c in rep.checks if c.status == "WARN"]
    if hard_fail:
        verdict = "QUARANTINE"
        reasons = [f"{c.id}: {c.detail}" for c in hard_fail + other_fail + warns]
    elif other_fail or warns:
        verdict = "REVIEW"
        reasons = [f"{c.id}: {c.detail}" for c in other_fail + warns]
    else:
        verdict = "ACCEPT"
        reasons = []
    if verdict == "QUARANTINE":
        exclusions.append(
            exclusion_record(
                session_id=session_id,
                participant_id=str(meta_dict.get("participant_id", "DEV")) if meta_dict else "DEV",
                level="SESSION",
                segment_id=None,
                take=None,
                reason_codes=_reason_codes([c.detail for c in hard_fail]) or ["SESSION_RULE"],
                reason_text="; ".join(f"{c.id}: {c.detail}" for c in hard_fail),
                thresholds_hash=th.hash,
            )
        )
    doc: dict[str, Any] = {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "session_id": session_id,
        "session_kind": str(kind),
        "label": classification_label(kind),
        "verdict": verdict,
        "reasons": list(dict.fromkeys(reasons)),
        "thresholds": th.to_dict(),
        "thresholds_hash": th.hash,
        "thresholds_label": "candidate values (pilot distribution sets them, Task 06.10)",
        "checks": [c.to_dict() for c in rep.checks],
        "quality": quality,
        "segments": segments_out,
        "sync": sync,
        "exclusions": exclusions,
        "generated_at": timing.wall_clock_iso(),
        "generator": {**GENERATOR, "git_sha": git_sha or "0" * 40},
    }
    if write:
        (d / VERIFY_FILENAME).write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        if (
            meta is not None
            and verdict != "QUARANTINE"
            and fps_measured is not None
            and not any(c.id == "V-META-SCHEMA" and c.status == "FAIL" for c in rep.checks)
        ):
            meta.data["measured_fps"] = {
                "value_fps": fps_measured,
                "method": "(n-1)/(t_last-t_first) over delivered unique frames (Phase 02 method)",
                "source": f"verify_session {doc['generated_at']}",
            }
            if not meta.errors():
                meta.write(d)
    return doc


REASON_CODES = (
    ("tracking validity", "LOW_TRACKING_VALIDITY"),
    ("fps", "FPS_DEVIATION"),
    ("sync", "SYNC_FAILURE"),
    ("violation", "PROTOCOL_VIOLATION"),
    ("frames", "TOO_FEW_FRAMES"),
    ("superseded", "RETAKEN"),
    ("consent", "CONSENT_INCOMPLETE"),
    ("core segments", "SESSION_RULE"),
    ("metadata", "METADATA_UNRECOVERABLE"),
    ("missing", "FILES_MISSING"),
    ("schema", "SCHEMA_INVALID"),
    ("config", "CONFIG_HASH_MISMATCH"),
    ("frame_id", "FRAME_ORDER"),
    ("t_capture", "FRAME_ORDER"),
)


def _reason_codes(reasons: Sequence[str]) -> list[str]:
    out: list[str] = []
    for r in reasons:
        low = r.lower()
        for needle, code in REASON_CODES:
            if needle in low and code not in out:
                out.append(code)
                break
    return out or ["OTHER"]


def exclusion_record(
    *,
    session_id: str,
    participant_id: str,
    level: str,
    segment_id: str | None,
    take: int | None,
    reason_codes: Sequence[str],
    reason_text: str,
    thresholds_hash: str,
    decided_by: str = "RULE",
    status: str = "QUARANTINED",
    decided_at: str | None = None,
) -> dict[str, Any]:
    """An ``ExclusionRecord`` (Task 06.8): quarantined, never deleted; listed with its reason."""
    suffix = f"-{segment_id}-t{take}" if level == "SEGMENT" else "-session"
    return {
        "schema_version": EXCLUSION_SCHEMA_VERSION,
        "exclusion_id": f"excl-{session_id}{suffix}",
        "session_id": session_id,
        "participant_id": participant_id,
        "level": level,
        "segment_id": segment_id,
        "take": take,
        "reason_codes": list(reason_codes),
        "reason_text": reason_text,
        "decided_by": decided_by,
        "rule_id": "unusable-recording-policy-v0.1",
        "thresholds_hash": thresholds_hash,
        "decided_at": decided_at or timing.wall_clock_iso(),
        "status": status,
    }


def validate_verification(doc: dict[str, Any]) -> list[str]:
    errs = contract_schema.errors("session-verification", doc)
    for e in doc.get("exclusions", []):
        errs += [
            f"exclusions/{e.get('exclusion_id')}: {m}" for m in contract_schema.errors("exclusion-record", e)
        ]
    return errs


def write_exclusions(path: str | Path, records: Sequence[dict[str, Any]]) -> Path:
    """Append ``ExclusionRecord``s to a JSONL log (never rewrites earlier lines)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        for r in records:
            errs = contract_schema.errors("exclusion-record", r)
            if errs:
                raise ValueError(f"invalid exclusion record: {errs[0]}")
            fh.write(json.dumps(r, allow_nan=False) + "\n")
    return p


def read_exclusions(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def format_verdict(doc: dict[str, Any]) -> str:
    q = doc["quality"]
    lines = [
        f"== {doc['session_id']} [{doc['session_kind']}] :: {doc['label']}",
        f"verdict: {doc['verdict']}",
    ]
    lines += [f"  reason: {r}" for r in doc["reasons"]]
    lines.append(
        f"frames {q.get('frames')} | duration {q.get('duration_s', 0.0):.2f} s | delivered FPS "
        f"{'n/a' if q.get('fps_delivered') is None else round(q['fps_delivered'], 2)} "
        f"| dropped {q.get('dropped')} "
        f"| stalls {q.get('stalls')} | both-hands-VALID {q.get('both_hands_valid_fraction')}"
    )
    for c in doc["checks"]:
        lines.append(f"  {c['status']:<4} {c['id']:<20} {c['detail']}")
    for s in doc["segments"]:
        tv = s["tracking_validity"]
        lines.append(
            f"  seg {s['segment_id']} t{s['take']} {s['verdict']:<8} n={s['n_frames']} "
            f"L={tv.get('LEFT')} R={tv.get('RIGHT')} {'; '.join(s['reasons'])}"
        )
    return "\n".join(lines)


__all__ = [
    "EXCLUSION_SCHEMA_VERSION",
    "HARD_CHECKS",
    "RECORD_STREAMS",
    "REQUIRED_FILES",
    "VERIFICATION_SCHEMA_VERSION",
    "VERIFY_FILENAME",
    "Check",
    "VerifyThresholds",
    "commits_during_non_valid",
    "exclusion_record",
    "format_verdict",
    "hand_order_flips",
    "read_exclusions",
    "validate_verification",
    "verify_session",
    "write_exclusions",
]
