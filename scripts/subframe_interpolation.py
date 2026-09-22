"""Phase 07, Task 07.4 — linear vs quadratic sub-frame crossing comparison (evidence for ADR-0020).

    python scripts/subframe_interpolation.py --synthetic [--out docs/reports/phase-07-interpolation.md]
    python scripts/subframe_interpolation.py --session data/raw/<p>/<s> --labels data/labels/<s>

Phase 04 timed a crossing by linear interpolation between the two bracketing frames and left the
choice Pending. This script measures both estimators against the best available reference and
applies the decision rule that was **declared before the run** (``interp.DECISION_RULE``):

    smaller IQR wins; within 10 % of each other, smaller |bias| wins; within 10 % on both, keep
    LINEAR (the Phase 04 estimator, fewer assumptions).

Reference, in order of preference:

1. ``t_impact_phys`` on the pad + microphone subset — PENDING, no such recording exists;
2. manual frame annotations near impacts — PENDING, person-dependent;
3. the **analytic** crossing time of a SYNTHETIC trajectory — available now.

Only (3) runs here, and its result is labelled SYNTHETIC. A synthetic comparison measures how the
two estimators behave on a known parabolic approach sampled at the frame rate; it is evidence about
the *estimators*, not about this project's real recordings, and the ADR says so.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _p07 import LABELS_ROOT, use_utf8_stdout  # noqa: E402

from spacedrums.app.synthetic import DT, Swing, build_sequence  # noqa: E402
from spacedrums.config import load_config  # noqa: E402
from spacedrums.contracts import HandId  # noqa: E402
from spacedrums.data.labels import interp  # noqa: E402
from spacedrums.data.labels.rules import signed_distance_to_surface  # noqa: E402
from spacedrums.data.labels.smooth import (  # noqa: E402
    Measurement,
    ReferenceSample,
    ReferenceSmoother,
)
from spacedrums.geometry import ZoneRegistry  # noqa: E402
from spacedrums.geometry.impact import crossing_time as linear_crossing_time  # noqa: E402
from spacedrums.geometry.impact import segment_surface  # noqa: E402

CONFIG = Path(__file__).resolve().parents[1] / "configs" / "prototype.candidate.yaml"


def synthetic_events(
    *,
    zone_id: str = "snare",
    n: int = 24,
    smoother_id: str | None = "rts-kalman-cv-v1",
    noise: float = 0.0,
) -> tuple[list[float], list[float], int]:
    """(linear errors, quadratic errors, n) against the analytic crossing of SYNTHETIC swings.

    The swings vary in downward duration and depth, so the approach acceleration and the phase of
    the crossing inside the frame interval both vary; a single swing would only measure one phase.

    ``smoother_id = None`` uses the sampled measurements directly. That **isolates the
    interpolation question**: with a smoother in the path the error is dominated by how the
    smoother treats the reversal at impact, which is Task 07.2's question, not Task 07.4's.
    """
    registry = ZoneRegistry.from_config(load_config(CONFIG)["zones"])
    zone = registry[zone_id]
    err_lin: list[float] = []
    err_quad: list[float] = []
    for k in range(n):
        t_down = 0.14 + 0.010 * (k % 6)
        depth = 0.03 + 0.004 * (k % 5)
        # Shift the stroke start by a fraction of a frame so the crossing lands at a different
        # phase inside the frame interval each time.
        t_start = 0.40 + DT * (k / n)
        sw = Swing(HandId.RIGHT, zone_id, t_start, t_down=t_down, depth=depth)
        seq = build_sequence(registry, [sw], duration_s=t_start + 2 * t_down + 0.4,
                             noise=noise, seed=100 + k)
        if not seq.truth:  # pragma: no cover - every swing above is a strike
            continue
        t_truth = seq.truth[0].t_cross  # build_sequence offsets the analytic crossing onto t_mono
        meas = [
            Measurement(frame_id=fs.frame_id, t=fs.t_capture,
                        p=obs[HandId.RIGHT][1].tip, confidence=obs[HandId.RIGHT][1].tip_confidence)
            for fs, obs in seq.frames
        ]
        samples = (
            list(ReferenceSmoother(smoother_id).smooth(meas).samples)
            if smoother_id
            else [
                ReferenceSample(m.frame_id, m.t, m.p, (0.0, 0.0), 1.0, False)
                for m in meas
                if m.present
            ]
        )
        if len(samples) < 4:
            continue
        distances = [signed_distance_to_surface(zone, s.p) for s in samples]
        bracket = None
        for i in range(len(samples) - 1):
            if zone.shape.contains(samples[i].p) or not zone.shape.contains(
                samples[i + 1].p, include_boundary=False
            ):
                continue
            if segment_surface(samples[i].p, samples[i + 1].p, zone.impact_surface) is not None:
                bracket = (i, i + 1)
                break
        if bracket is None:
            continue
        i, j = bracket
        cross = segment_surface(samples[i].p, samples[j].p, zone.impact_surface)
        t_lin = linear_crossing_time(samples[i].t, samples[j].t, cross.s)
        quad = interp.quadratic_crossing([s.t for s in samples], distances, bracket=bracket)
        if quad is None:
            continue
        err_lin.append(t_lin - t_truth)
        err_quad.append(quad.t_cross - t_truth)
    return err_lin, err_quad, len(err_lin)


def _ms(v: float | None) -> str:
    return "—" if v is None else f"{v * 1000:.3f} ms"


def render(cmp_result: interp.Comparison, *, title: str, extra: str = "") -> str:
    lines = [
        f"# {title}",
        "",
        f"**Reference:** {cmp_result.reference}",
        "",
        f"**Evidence class:** {cmp_result.evidence_label}",
        "",
        f"**Decision rule (declared before the run):** {interp.DECISION_RULE}",
        "",
        "| Estimator | n | bias (median) | IQR | max |error| |",
        "|---|---:|---:|---:|---:|",
        f"| LINEAR (Phase 04) | {cmp_result.n} | {_ms(cmp_result.bias_linear_s)} | "
        f"{_ms(cmp_result.iqr_linear_s)} | {_ms(cmp_result.max_abs_linear_s)} |",
        f"| QUADRATIC | {cmp_result.n} | {_ms(cmp_result.bias_quadratic_s)} | "
        f"{_ms(cmp_result.iqr_quadratic_s)} | {_ms(cmp_result.max_abs_quadratic_s)} |",
        "",
        f"**Decision: `{cmp_result.decision}`** — {cmp_result.decision_reason}",
        "",
    ]
    if extra:
        lines += [extra, ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--synthetic", action="store_true", default=True)
    ap.add_argument("--session", default=None)
    ap.add_argument("--labels", default=None)
    ap.add_argument("--labels-root", default=str(LABELS_ROOT))
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--noise", type=float, default=0.0)
    ap.add_argument("--smoother", default="rts-kalman-cv-v1")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    use_utf8_stdout()

    if args.session or args.labels:
        print("[interp] a comparison against a PHYSICAL reference needs the pad + microphone "
              "subset, which does not exist (Phase 06 C-06-3). Result: PENDING / NOT VALIDATED.")
        return 0

    label = (
        "SYNTHETIC — generated trajectories with an analytically known crossing; evidence about "
        "the estimators, not about real recordings"
    )
    raw_lin, raw_quad, raw_n = synthetic_events(n=args.n, smoother_id=None, noise=args.noise)
    raw = interp.compare(
        raw_lin,
        raw_quad,
        reference="analytic crossing of the SYNTHETIC swing — sampled measurements, no smoother",
        evidence_label=label,
    )
    sm_lin, sm_quad, sm_n = synthetic_events(n=args.n, smoother_id=args.smoother, noise=args.noise)
    smoothed = interp.compare(
        sm_lin,
        sm_quad,
        reference=f"analytic crossing of the SYNTHETIC swing — through `{args.smoother}`",
        evidence_label=label,
    )
    note = (
        "> **Not a real-world measurement.** The reference is the analytic crossing of a generated "
        "trajectory. The comparison against a physical reference (`t_impact_phys`, pad + "
        "microphone) and against manual frame annotations near impacts remains **PENDING / NOT "
        "VALIDATED**: no such recording exists.\n>\n"
        f"> Table 1 isolates the interpolation estimator ({raw_n} events, no smoother). Table 2 "
        f"shows the same strokes through the reference smoother `{args.smoother}` ({sm_n} events); "
        "there the error also carries how the smoother treats the reversal at impact, which is "
        "Task 07.2's question (`docs/reports/phase-07-reference-smoother.md`).\n>\n"
        f"> Measurement noise {args.noise}. The decision below is taken on **Table 1**, because "
        "that is the table that isolates the estimator under test."
    )
    text = "\n".join(
        [
            render(raw, title="Phase 07 — Sub-frame interpolation comparison (Table 1: estimator only)"),
            render(smoothed, title="Table 2 — the same strokes through the reference smoother",
                   extra=note),
        ]
    )
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")
        print(f"[interp] wrote {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
