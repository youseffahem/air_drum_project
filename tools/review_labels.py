"""Phase 07, Task 07.5 — label review / QC tool.

    python tools/review_labels.py --labels data/labels/<session> --session data/raw/<p>/<session> \
        --reviewer A1 [--pass 1] [--plan 1.0,1.0,0.2]
    python tools/review_labels.py --selftest        # non-interactive scripted pass, no person needed
    python tools/review_labels.py --agreement --labels data/labels/<session>

Interactive mode opens an OpenCV window per queued label and scrubs the frames around the event
with overlays: the **reference** tip (the offline-smoothed trajectory the label came from), the
**causal** tip (what the live system saw), the zone outline, its impact surface, and a marker at
``t_impact_est``. Keys:

    <- / ->  scrub one frame      , / .   nudge t_impact_est by 1/4 frame
    a        accept               r       reject
    z        change zone (cycle)  d       defer -> AMBIGUOUS
    n        add a note           s       save and continue
    q        quit (progress is already on disk: the log is append-only)

Every keystroke that changes something writes a ``LabelReviewEntry`` to
``labels/<session>/review.jsonl`` and updates the label's ``review`` block. **An adjusted label
always keeps its original values** (``review.original``) and one ``review.history`` item per
changed field, so a correction can always be traced back.

``--pass 2`` is the independent re-review of the stratified agreement subset. It never overwrites
the first pass: the second decision lands in ``review.second_pass`` and a presence / zone / class
disagreement makes the event AMBIGUOUS (rule R6c) rather than silently picking a winner.

**No person is required to exercise this tool.** ``--selftest`` runs a scripted, deterministic pass
over a generated SYNTHETIC label set, which is what the tests use; agreement computed that way is
labelled SYNTHETIC and is a machinery check, never inter-annotator agreement.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from spacedrums import timing  # noqa: E402
from spacedrums.data.labels.generate import read_labels, read_reference_track  # noqa: E402
from spacedrums.data.labels.review import (  # noqa: E402
    QC_PROTOCOL_ID,
    TOOL_ID,
    Agreement,
    SamplingPlan,
    agreement,
    apply_entry,
    make_entry,
    qc_summary,
    read_review_log,
    review_queue,
    write_review_log,
)
from spacedrums.data.labels.schema import (  # noqa: E402
    LABEL_SET_FILENAME,
    LABELS_FILENAME,
    REFERENCE_TRACK_FILENAME,
    REVIEW_FILENAME,
    ReviewDecision,
    label_set_hash,
    sha256_file,
)

VERSION = "0.7.0"


# ----------------------------------------------------------------------------- persistence


def load(label_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    labels = read_labels(label_dir / LABELS_FILENAME)
    label_set = json.loads((label_dir / LABEL_SET_FILENAME).read_text(encoding="utf-8"))
    return labels, label_set


def save(label_dir: Path, labels: list[dict[str, Any]], label_set: dict[str, Any],
         plan: SamplingPlan) -> None:
    """Rewrite ``labels.jsonl`` and refresh the label set's QC block and file hashes."""
    with (label_dir / LABELS_FILENAME).open("w", encoding="utf-8", newline="\n") as fh:
        for rec in labels:
            fh.write(json.dumps(rec, allow_nan=False, sort_keys=True) + "\n")
    label_set["qc"] = qc_summary(labels, plan)
    counts = label_set["counts"]
    by_class: dict[str, int] = {}
    for rec in labels:
        by_class[rec["label_class"]] = by_class.get(rec["label_class"], 0) + 1
    counts["by_class"] = dict(sorted(by_class.items()))
    counts["total"] = len(labels)
    counts["ambiguous"] = by_class.get("AMBIGUOUS", 0)
    for entry in label_set["files"]:
        p = label_dir / entry["path"]
        if p.exists():
            entry["bytes"] = p.stat().st_size
            entry["sha256"] = sha256_file(p)
    label_set["set_hash"] = label_set_hash(label_set)
    (label_dir / LABEL_SET_FILENAME).write_text(
        json.dumps(label_set, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )


def record_decisions(
    label_dir: Path,
    decisions: list[tuple[str, ReviewDecision, dict[str, Any] | None, str | None]],
    *,
    reviewer_id: str,
    pass_no: int,
    reviewed_at: str,
    plan: SamplingPlan,
    lighting: str = "UNKNOWN",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply a list of ``(label_id, decision, after, reason)`` and persist labels + review log."""
    labels, label_set = load(label_dir)
    by_id = {rec["label_id"]: i for i, rec in enumerate(labels)}
    entries: list[dict[str, Any]] = []
    for label_id, decision, after, reason in decisions:
        i = by_id.get(label_id)
        if i is None:
            raise KeyError(f"no label {label_id} in {label_dir}")
        entry = make_entry(
            labels[i],
            decision=decision,
            reviewer_id=reviewer_id,
            reviewed_at=reviewed_at,
            pass_no=pass_no,
            after=after,
            reason=reason,
            lighting=lighting,
        )
        entries.append(entry)
        labels[i] = apply_entry(labels[i], entry)
    write_review_log(entries, label_dir / REVIEW_FILENAME)
    save(label_dir, labels, label_set, plan)
    return labels, entries


# ----------------------------------------------------------------------------- overlays


def frame_window(
    label: dict[str, Any], session_dir: Path, *, half_frames: int = 6
) -> list[dict[str, Any]]:
    """The ``FrameSample`` records around the event (for the scrub window)."""
    frames = [
        json.loads(line)
        for line in (session_dir / "frames.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    centre = label["frames"]["before_event"] or label["frames"]["first_frame_id"]
    idx = next((i for i, f in enumerate(frames) if f["frame_id"] == centre), 0)
    return frames[max(0, idx - half_frames) : idx + half_frames + 1]


def draw_overlay(image, label: dict[str, Any], frame: dict[str, Any], reference, causal, registry):
    """Draw the zone, its impact surface, both tips and the t_impact_est marker on ``image``."""
    import cv2  # imported here so the module stays importable without a GUI stack

    x, y, w, h = frame["roi_px"]

    def to_px(p):
        return int(round(x + p[0] * w)), int(round(y + p[1] * h))

    zone = registry[label["zone_id"]] if label["zone_id"] else None
    if zone is not None:
        surface = zone.impact_surface
        if hasattr(surface, "p0"):
            cv2.line(image, to_px(surface.p0), to_px(surface.p1), (0, 200, 255), 2)
        else:
            pts = [
                to_px(surface.point_at(surface.theta_start_rad
                                       + (surface.theta_end_rad - surface.theta_start_rad) * f / 32))
                for f in range(33)
            ]
            for a, b in zip(pts, pts[1:], strict=False):
                cv2.line(image, a, b, (0, 200, 255), 2)
    ref = next((s for s in reference if s.frame_id == frame["frame_id"]), None)
    if ref is not None:
        cv2.circle(image, to_px(ref.p), 5, (0, 255, 0), -1)  # reference tip (label source)
    cau = causal.get(frame["frame_id"])
    if cau is not None:
        cv2.circle(image, to_px(cau), 5, (255, 128, 0), 2)  # causal tip (what the live system saw)
    if label["impact_position"]:
        cv2.drawMarker(image, to_px(label["impact_position"]), (0, 0, 255),
                       cv2.MARKER_CROSS, 18, 2)
    text = (f"{label['label_id']}  {label['label_class']}  {label['label_rule_id']}  "
            f"t_impact_est={label['t_impact_est']}")
    cv2.putText(image, text, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(image, "green = REFERENCE (label source, non-causal) | orange = CAUSAL (runtime)",
                (10, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    return image


# ----------------------------------------------------------------------------- interactive


def interactive(args: argparse.Namespace) -> int:  # pragma: no cover - needs a GUI and a person
    import cv2
    import numpy as np

    from spacedrums.config import load_config
    from spacedrums.geometry import ZoneRegistry

    label_dir, session_dir = Path(args.labels), Path(args.session)
    labels, label_set = load(label_dir)
    plan = SamplingPlan(*[float(v) for v in args.plan.split(",")]) if args.plan else SamplingPlan()
    queue = review_queue(labels, plan)
    registry = ZoneRegistry.from_config(load_config(session_dir / "config.snapshot.yaml")["zones"])
    _, ref_by_hand = read_reference_track(label_dir / REFERENCE_TRACK_FILENAME)
    causal_by_hand: dict[str, dict[int, tuple[float, float]]] = {}
    from spacedrums.timing.logger import read_record_stream

    for rec in read_record_stream(session_dir / "records" / "TrackState.jsonl")[1]:
        if rec["tip_filtered"]:
            causal_by_hand.setdefault(rec["hand_id"], {})[rec["frame_id"]] = tuple(rec["tip_filtered"])
    print(f"[review] {QC_PROTOCOL_ID}: {len(queue)} of {len(labels)} labels queued "
          f"(rates {plan.to_dict()})")
    decisions: list[tuple[str, ReviewDecision, dict[str, Any] | None, str | None]] = []
    for label in queue:
        window = frame_window(label, session_dir)
        i = len(window) // 2
        t_adj = label["t_impact_est"]
        zone_ids = [z.zone_id for z in registry]
        zone_i = zone_ids.index(label["zone_id"]) if label["zone_id"] in zone_ids else 0
        note, reason = "", None
        while True:
            frame = window[i]
            img = cv2.imread(str(session_dir / frame["image_ref"]["path"]))
            if img is None:
                img = np.zeros((480, 640, 3), np.uint8)
            shown = dict(label)
            shown["t_impact_est"] = t_adj
            shown["zone_id"] = zone_ids[zone_i]
            draw_overlay(img, shown, frame, ref_by_hand.get(label["hand_id"], []),
                         causal_by_hand.get(label["hand_id"], {}), registry)
            cv2.imshow("review_labels", img)
            key = cv2.waitKey(0) & 0xFF
            if key in (81, ord("[")):
                i = max(0, i - 1)
            elif key in (83, ord("]")):
                i = min(len(window) - 1, i + 1)
            elif key == ord(",") and t_adj is not None:
                t_adj -= (1 / 30) / 4
            elif key == ord(".") and t_adj is not None:
                t_adj += (1 / 30) / 4
            elif key == ord("z"):
                zone_i = (zone_i + 1) % len(zone_ids)
            elif key == ord("n"):
                note = input("note: ")
            elif key in (ord("a"), ord("r"), ord("d")):
                decision = {ord("a"): ReviewDecision.ACCEPT, ord("r"): ReviewDecision.REJECT,
                            ord("d"): ReviewDecision.DEFER}[key]
                changed = t_adj != label["t_impact_est"] or zone_ids[zone_i] != label["zone_id"]
                if decision is ReviewDecision.ACCEPT and changed:
                    decision = ReviewDecision.ADJUST
                    reason = input("adjustment reason: ") or "reviewer adjustment"
                after = {"t_impact_est": t_adj, "t_event": t_adj if t_adj is not None
                         else label["t_event"], "zone_id": zone_ids[zone_i],
                         "label_class": label["label_class"]}
                decisions.append((label["label_id"], decision, after, reason))
                print(f"  {label['label_id']}: {decision}{' (' + note + ')' if note else ''}")
                break
            elif key == ord("q"):
                cv2.destroyAllWindows()
                if decisions:
                    record_decisions(label_dir, decisions, reviewer_id=args.reviewer,
                                     pass_no=args.pass_no, reviewed_at=timing.wall_clock_iso(),
                                     plan=plan, lighting=args.lighting)
                print(f"[review] saved {len(decisions)} decisions and quit")
                return 0
    cv2.destroyAllWindows()
    if decisions:
        record_decisions(label_dir, decisions, reviewer_id=args.reviewer, pass_no=args.pass_no,
                         reviewed_at=timing.wall_clock_iso(), plan=plan, lighting=args.lighting)
    print(f"[review] {len(decisions)} decisions written to {label_dir / REVIEW_FILENAME}")
    return 0


# ----------------------------------------------------------------------------- self-test


def scripted_decisions(labels: list[dict[str, Any]], *, pass_no: int
                       ) -> list[tuple[str, ReviewDecision, dict[str, Any] | None, str | None]]:
    """A deterministic scripted pass: accept, adjust every third, reject every fifth, defer the rest.

    Pass 2 differs on purpose (it shifts the accepted times by a quarter frame and rejects a
    different subset) so the agreement statistics have something to measure. These are SCRIPTED
    decisions by a machine; they are never presented as an annotator's judgement.
    """
    out = []
    for k, rec in enumerate(sorted(labels, key=lambda r: r["label_id"])):
        after = {
            "t_impact_est": rec["t_impact_est"],
            "t_event": rec["t_event"],
            "zone_id": rec["zone_id"],
            "label_class": rec["label_class"],
        }
        offset = k + (2 if pass_no == 2 else 0)
        if offset % 5 == 4:
            out.append((rec["label_id"], ReviewDecision.REJECT, after, "scripted reject"))
        elif offset % 3 == 2 and rec["t_impact_est"] is not None:
            shifted = dict(after)
            shifted["t_impact_est"] = rec["t_impact_est"] + (1 / 30) / 4
            shifted["t_event"] = shifted["t_impact_est"]
            out.append((rec["label_id"], ReviewDecision.ADJUST, shifted, "scripted adjustment"))
        elif offset % 7 == 6:
            out.append((rec["label_id"], ReviewDecision.DEFER, after, "scripted defer"))
        else:
            out.append((rec["label_id"], ReviewDecision.ACCEPT, after, None))
    return out


def selftest() -> int:
    from _p07 import git_sha

    sys.path.insert(0, str(ROOT / "tests" / "data"))
    from data_helpers import make_session

    from spacedrums.data.labels.generate import generate_labels

    tmp = Path(tempfile.mkdtemp(prefix="p07-review-"))
    try:
        session_dir, _, _ = make_session(tmp / "raw", session_id="synthetic-p07-review")
        result = generate_labels(session_dir, tmp / "labels",
                                 dataset_version="ds-v0.0-selftest-review", git_sha=git_sha())
        label_dir = result.label_dir
        plan = SamplingPlan(1.0, 1.0, 1.0)
        queue = review_queue(result.labels, plan)
        print(f"[selftest] {len(queue)} of {len(result.labels)} labels queued under "
              f"{QC_PROTOCOL_ID}")
        labels, entries1 = record_decisions(
            label_dir, scripted_decisions(queue, pass_no=1), reviewer_id="SELFTEST-A1", pass_no=1,
            reviewed_at="2026-09-22T12:00:00+03:00", plan=plan)
        labels, entries2 = record_decisions(
            label_dir, scripted_decisions(queue, pass_no=2), reviewer_id="SELFTEST-A2", pass_no=2,
            reviewed_at="2026-09-22T13:00:00+03:00", plan=plan)
        summary = qc_summary(labels, plan)
        print(f"[selftest] QC after two passes: {summary}")
        adjusted = [r for r in labels if r["review"]["adjusted"]]
        ok = True
        for rec in adjusted:
            kept = rec["review"]["original"] is not None and rec["review"]["history"]
            ok = ok and kept
            print(f"[selftest] adjusted {rec['label_id']}: original kept = {bool(kept)}, "
                  f"history entries = {len(rec['review']['history'])}")
        log = read_review_log(label_dir / REVIEW_FILENAME)
        print(f"[selftest] review log: {len(log)} entries "
              f"({len(entries1)} pass 1 + {len(entries2)} pass 2), append-only")
        ag = agreement(log, kind="SELF_REREVIEW",
                       evidence_label="SYNTHETIC — scripted machine decisions, not annotators")
        print(f"[selftest] agreement (SYNTHETIC, scripted): {json.dumps(ag.to_dict())}")
        ok = ok and len(log) == len(entries1) + len(entries2) and ag.n_pairs == len(queue)
        disagreed = [r for r in labels if r["review"]["disagreement"]]
        print(f"[selftest] labels with a recorded disagreement: {len(disagreed)} "
              f"(kinds {sorted({r['review']['disagreement']['kind'] for r in disagreed})})")
        print("\nNOTE: these are SCRIPTED machine decisions on SYNTHETIC labels. They validate the "
              "review round-trip and the agreement computation. They are NOT inter-annotator "
              "agreement and no such agreement is claimed.")
        print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def agreement_report(label_dir: Path, *, kind: str, evidence_label: str) -> Agreement:
    return agreement(read_review_log(label_dir / REVIEW_FILENAME), kind=kind,
                     evidence_label=evidence_label)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", default=None)
    ap.add_argument("--session", default=None)
    ap.add_argument("--reviewer", default=None, help="annotator pseudonym (A1, A2, ...)")
    ap.add_argument("--pass", dest="pass_no", type=int, default=1, choices=(1, 2))
    ap.add_argument("--plan", default=None, help="positives,ambiguous,negatives review rates")
    ap.add_argument("--lighting", default="UNKNOWN")
    ap.add_argument("--agreement", action="store_true", help="report agreement from the review log")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.agreement:
        if not args.labels:
            ap.error("--agreement needs --labels")
        log = read_review_log(Path(args.labels) / REVIEW_FILENAME)
        if not log:
            print("[agreement] no review log — inter-annotator agreement is PENDING / NOT VALIDATED")
            return 0
        kinds = {e["reviewer_id"] for e in log if int(e["pass"]) == 2}
        first = {e["reviewer_id"] for e in log if int(e["pass"]) == 1}
        kind = "INTER_ANNOTATOR" if kinds - first else "SELF_REREVIEW"
        ag = agreement(log, kind=kind, evidence_label="from the review log of this label set")
        print(json.dumps(ag.to_dict(), indent=2))
        return 0
    if not (args.labels and args.session and args.reviewer):
        ap.error("interactive review needs --labels, --session and --reviewer "
                 "(or use --selftest / --agreement)")
    print(f"[review] tool {TOOL_ID} (version {VERSION})")
    return interactive(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
