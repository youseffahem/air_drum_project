"""Phase 07, Task 07.6 — acoustic onset ground truth on the pad + microphone subset.

    python scripts/acoustic_onset.py --session data/raw/<p>/<s> --labels data/labels/<s>
    python scripts/acoustic_onset.py --all --out docs/reports/phase-07-acoustic-validation.md
    python scripts/acoustic_onset.py --selftest      # SYNTHETIC click track with a known offset

Detects onsets in the session's microphone track, maps them onto ``t_mono``, pairs each onset with
the POSITIVE label of the pad zone in the same PAD segment, and reports the distribution of
``t_impact_phys - t_impact_est``.

**What the residual means.** It is a measured offset between two differently defined instants — the
geometric crossing of the virtual impact surface by the estimated stick tip, and the acoustic onset
of the sound the pad made. It is never a claim that the two are the same instant, and it is never
applied silently to labels. Every residual is reported together with the microphone-path latency
bound and the clap-sync residual, and a residual smaller than those bounds means nothing.

**Status.** No pad and no microphone are inventoried and no session with a person exists (Phase 06
conditions C-06-3 / C-06-4). On real sessions the script therefore prints the explicit PENDING
outcome with its reason; ``--selftest`` exercises the whole path on a SYNTHETIC click track whose
offset is injected and therefore known — a machinery check, not a measurement.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _p07 import LABELS_ROOT, find_label_dirs, find_sessions, use_utf8_stdout  # noqa: E402

from spacedrums.data.labels.acoustic import (  # noqa: E402
    DEFAULT_MIC_LATENCY_BOUND_S,
    DEFAULT_PAIR_WINDOW_S,
    pair_onsets,
    pair_session,
)
from spacedrums.data.labels.generate import read_labels  # noqa: E402
from spacedrums.data.labels.schema import LABELS_FILENAME  # noqa: E402
from spacedrums.data.metadata import SessionMetadata  # noqa: E402


def selftest(injected_offset_s: float = 0.006) -> int:
    """Pair a SYNTHETIC click track against SYNTHETIC labels with a known injected offset."""
    from spacedrums.data.audio_capture import detect_onsets

    rate = 48_000
    t0 = 100.0
    impacts = [100.50, 101.20, 101.95, 102.60]
    n = int(3.5 * rate)
    x = np.zeros(n, dtype=np.float32)
    rng = np.random.default_rng(7)
    x += rng.normal(0.0, 1e-4, n).astype(np.float32)
    for t in impacts:
        k = int(round((t - t0 + injected_offset_s) * rate))
        env = np.exp(-np.arange(400) / 60.0).astype(np.float32)
        x[k : k + 400] += env * np.sin(np.arange(400) * 0.4).astype(np.float32)
    onsets = [t0 + t for t in detect_onsets(x, rate, min_gap_s=0.2)]
    print(f"[selftest] SYNTHETIC click track: {len(onsets)} onsets detected for "
          f"{len(impacts)} injected clicks (offset {injected_offset_s * 1000:.1f} ms)")
    residuals = [o - i for o, i in zip(sorted(onsets), impacts, strict=False)]
    if residuals:
        print(f"[selftest] recovered offsets (s): "
              f"{[round(r, 5) for r in residuals]}")
    ok = len(onsets) == len(impacts) and all(
        abs(r - injected_offset_s) < 0.01 for r in residuals
    )
    print("[selftest] the recovered offset is the offset that was INJECTED: this validates the "
          "detector and the pairing path, and is not a measurement of any physical latency.")
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def _report_line(session_id: str, result) -> str:
    s = result.stats()
    if not result.available:
        return f"| `{session_id}` | — | — | — | — | **PENDING** — {result.reason} |"
    return (
        f"| `{session_id}` | {result.n_pad_positives} | {result.n_paired} | "
        f"{s['bias_s']:.5f} | {s['iqr_s']:.5f} | mic bound "
        f"{result.mic_latency_bound_s} s, sync {result.sync_residual_rms_s} s |"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", default=None)
    ap.add_argument("--labels", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--labels-root", default=str(LABELS_ROOT))
    ap.add_argument("--window-s", type=float, default=DEFAULT_PAIR_WINDOW_S)
    ap.add_argument("--mic-latency-bound-s", type=float, default=DEFAULT_MIC_LATENCY_BOUND_S)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    use_utf8_stdout()

    if args.selftest:
        return selftest()

    pairs: list[tuple[Path, Path]] = []
    if args.all:
        label_dirs = {d.name: d for d in find_label_dirs(Path(args.labels_root))}
        pairs = [(sd, label_dirs[sd.name]) for sd in find_sessions() if sd.name in label_dirs]
    elif args.session and args.labels:
        pairs = [(Path(args.session), Path(args.labels))]
    else:
        ap.error("give --session and --labels, or --all, or --selftest")

    if not pairs:
        print("[acoustic] no labelled session found — acoustic validation is PENDING "
              "(no pad + microphone recording exists; Phase 06 C-06-3)")
        return 0

    lines = ["| Session | Pad positives | Paired | Bias (s) | IQR (s) | Bounds / reason |",
             "|---|---:|---:|---:|---:|---|"]
    for session_dir, label_dir in pairs:
        meta = SessionMetadata.read(session_dir)
        labels = read_labels(label_dir / LABELS_FILENAME)
        result = pair_session(session_dir, labels, window_s=args.window_s,
                              mic_latency_bound_s=args.mic_latency_bound_s)
        print(f"[{meta.session_id}] available={result.available} "
              f"pad_positives={result.n_pad_positives} paired={result.n_paired} "
              f"{'' if result.available else '(' + str(result.reason) + ')'}")
        lines.append(_report_line(meta.session_id, result))
    text = "\n".join(lines)
    print("\n" + text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")
        print(f"[acoustic] wrote {args.out}")
    return 0


__all__ = ["main", "pair_onsets", "selftest"]

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
