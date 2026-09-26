# Debug overlay and dashboard

Phase 15 adds three views over the same immutable runtime records. None of them is a
strike source and none may change a decision.

## Live/replay application

```powershell
python -m spacedrums.app.main --source replay `
  --session-dir data/dev-sessions/dev-p05-swing-L2-exp-5 `
  --overlay-mode full --dashboard --no-audio
```

`--overlay-mode off|experiment|full` selects a preset. `experiment` is the low-overhead
mode: tracking safety badges, filtered tip, crossing/zone, TTI, decision/commit marker,
active arm/fallback, and capture/audio/UI-drop status. `full` additionally shows landmarks,
search region, stick axis/raw tip and method, velocity, all trajectories, intensity and
probability. Every item is also a field of `OverlayConfig` for protocol-specific toggles.

`--dashboard` starts an independent consumer thread. Publishing uses a bounded queue and
`put_nowait`; a slow dashboard increments `UI drops` and discards UI records. It never waits
in the capture/decision loop, and UI drops are kept distinct from camera drops.

The per-strike panel deliberately distinguishes:

- live anticipatory rows: **predicted lead (predicted impact - commit)**;
- replay rows with ground truth: **L_pred (estimated impact - commit)**;
- software output estimates: carry `_est`; they are not physical/acoustic measurements.

## Replay viewer and ground truth

```powershell
python -m spacedrums.ui.replay_viewer data/raw/SYNTHETIC/synthetic-p07-labels `
  --labels data/labels/synthetic-p07-labels/labels.jsonl
```

Use `a`/`d` or arrow keys to step, the trackbar to scrub, space to play/pause, and `q`
to exit. All streams are joined by `frame_id`, never by JSONL line position. Event labels
are one-to-one matched by the Phase 09 matcher and displayed as `MATCHED` or `UNMATCHED`;
unmatched commits are marked separately. The viewer accepts any session with the project
record layout (`frames.jsonl`, record streams, and `config.snapshot.yaml`), including
`ds-v1.0` sessions when available.

To export an annotated clip instead of opening a window:

```powershell
python -m spacedrums.ui.replay_viewer <session> --labels <labels.jsonl> `
  --export-clip out/session.mp4 --mode full
```

## Thesis-ready exports

`spacedrums.ui.export.export_session()` writes:

- annotated PNG frames;
- rolling tip-y/vertical-velocity/TTI and processing-time plots as PNG and SVG;
- a selected-frame predicted-versus-observed trajectory plot as PNG and SVG;
- a lead-time histogram;
- a per-strike timing CSV with explicit `lead_kind`;
- false-positive CSV grouped by the enclosing segment type where labels provide intervals;
- a session-summary JSON.

Names use `<session>__<arm>__<model>__<artifact>` with unsafe filename characters replaced.

## Reproduce the overhead evidence

```powershell
python scripts/measure_phase15.py data/dev-sessions/dev-p05-swing-L2-exp-5 `
  --output experiments/phase-15/20260926-phase15-overhead/final `
  --frames 171 --repeats 5
```

This is development replay wall time, not physical/acoustic latency. The experiment-mode
target is incremental p95 at most 5 ms versus overlay-off: 15% of a 30 fps frame period,
rounded. Re-measure after material renderer, driver, resolution, or hardware changes.

## Known limits

- OpenCV windows require a desktop session; exports and tests are headless-safe.
- The current recorded streams do not persist commit rejection traces. Live views receive
  those read-only traces from `FrameResult`; replay displays recorded candidates/commits.
- Browser DOM/plot rendering was not implemented. Only its local JSON socket transport was
  prototyped for the framework comparison.
- Existing example labels are synthetic/developer evidence and remain pending human review;
  no participant or `ds-v1.0` evidence is claimed.
- Replayed record stamps mix recorded and current processing clocks. Replay plots therefore
  show the inference-stage duration (same-clock stamps), not a fabricated total processing time.
