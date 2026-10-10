"""Build or verify the acoustic Salamander Drumkit bank used by the full-kit demo.

Source: "The Salamander Drumkit" by Alexander Holm, genuine acoustic overhead-microphone recordings
(48 kHz / 24-bit stereo), licence CC BY-SA 3.0. The archive is fetched once into data/cache/ (git-ignored),
pinned by size and MD5/SHA-1/SHA-256, read with the stdlib tarfile module (never extracted wholesale), and
the selected takes are turned into assets/samples/acoustic/*.wav plus assets/samples/acoustic-manifest.json.
The WAVs are git-ignored like the TR-505 bank; the manifest and licence notes are tracked.

  python scripts/fetch_acoustic_samples.py            build (downloads the archive if it is not cached)
  python scripts/fetch_acoustic_samples.py --archive PATH   build from a local copy of the archive
  python scripts/fetch_acoustic_samples.py --verify   offline hash check of the built WAVs

Processing (deterministic, recipe id ``sal-v1``; every step is applied per take):
  1. mono = mean of the two channels (what SampleBank does anyway); no resampling (source is 48 kHz)
  2. tom2 only: the rack-tom takes are resampled down 6 semitones (99/70) - a DERIVED sample, flagged as such
  3. head: leading silence is trimmed to 2 ms before the first sample above -40 dBFS of the take's peak
  4. tail: samples below -84 dBFS after the last audible sample are dropped, then a 60 ms raised-cosine
     fade-out so no sample ends on a step; cymbals keep their natural ring
  5. ONE kit-wide gain puts the loudest hard take at TARGET_PEAK_DB; relative levels between instruments are
     kept (no per-sample peak normalisation)
  6. soft layers are trimmed so their median peak sits SOFT_BELOW_HARD_DB under the hard layer's, so the
     intensity-gain curve alone controls loudness and the layer swap only changes timbre
Tom 2 is DERIVED from the rack tom because the kit contains only two toms; see LICENSES.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
import urllib.request
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "assets/samples"
OUT_DIR = SAMPLES / "acoustic"
MANIFEST = SAMPLES / "acoustic-manifest.json"
CACHE = ROOT / "data/cache/salamander/salamanderDrumkit.tar.bz2"

ARCHIVE_URL = "https://archive.org/download/SalamanderDrumkit/salamanderDrumkit.tar.bz2"
ARCHIVE_PAGE = "https://archive.org/details/SalamanderDrumkit"
ARCHIVE_SIZE = 387_611_727
ARCHIVE_MD5 = "af8e2067668a7f438e7d981877fb771f"  # as listed by archive.org's metadata API
ARCHIVE_SHA1 = "b16146d901ba4e22f821396362371a745e2aa935"  # as listed by archive.org's metadata API
# computed on first download
ARCHIVE_SHA256 = "34e746ec1721bb530b1caf5b17443ae3cde45a2cce1a80e2637e4c11d6f1e3f5"
RECIPE = "sal-v1"
ACCESSED = "2026-10-10"

RATE = 48_000
TARGET_PEAK_DB = -8.0  # loudest hard take; leaves room for two simultaneous hits and ringing cymbals
SOFT_BELOW_HARD_DB = 2.0
MAX_TAKES = 3
HEAD_MS, ONSET_DB, TAIL_FLOOR_DB, FADE_MS = 2.0, -40.0, -84.0, 60.0
TOM2_RATIO = Fraction(99, 70)  # 12*log2(99/70) = 6.0005 semitones down

# group id -> (source instrument, hard dynamic, soft dynamic, what the source drum/cymbal is)
GROUPS = {
    "salamander-snare": ("snare", "FF", "MP", "14x5in birch-stave snare"),
    "salamander-tom1": ("hiTom", "FF", "F", "12x7in rack tom"),
    "salamander-tom2": ("hiTom", "FF", "F", "12x7in rack tom resampled down 6 semitones (DERIVED)"),
    "salamander-floor-tom": ("loTom", "FF", "MP", "14x14in floor tom"),
    "salamander-hihat": ("hihatClosed", "F", "P", "Stagg 14in SH hi-hat, closed"),
    "salamander-crash": ("crash1", "FF", "P", "Paiste 18in Innovations medium crash"),
    "salamander-ride": ("ride1", "FF", "MP", "20in medium ride (README: Paiste pst5)"),
}
DERIVED = {"salamander-tom2": {"from": "hiTom",
    "resample": f"{TOM2_RATIO.numerator}/{TOM2_RATIO.denominator}",
                               "semitones": round(-12 * float(np.log2(float(TOM2_RATIO))), 3)}}
MEMBER = re.compile(r"^OH/([A-Za-z0-9]+)_OH_([A-Za-z]+)_(\d+)\.wav$")


def db(x: float) -> float:
    return 20 * float(np.log10(max(x, 1e-12)))


def hashes(path: Path) -> dict[str, str]:
    md5, sha1, sha256 = hashlib.md5(), hashlib.sha1(), hashlib.sha256()  # noqa: S324 - archive.org lists md5/sha1
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            md5.update(chunk), sha1.update(chunk), sha256.update(chunk)
    return {"md5": md5.hexdigest(), "sha1": sha1.hexdigest(), "sha256": sha256.hexdigest(),
        "size": path.stat().st_size}


def check_archive(path: Path) -> None:
    got = hashes(path)
    want = {"md5": ARCHIVE_MD5, "sha1": ARCHIVE_SHA1, "sha256": ARCHIVE_SHA256, "size": ARCHIVE_SIZE}
    bad = [k for k in want if got[k] != want[k]]
    if bad:
        raise SystemExit(f"archive {path} does not match the pinned {', '.join(bad)}; refusing to use it")


def ensure_archive(path: Path | None) -> Path:
    path = path or CACHE
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {ARCHIVE_URL} ({ARCHIVE_SIZE / 1e6:.0f} MB) -> {path}")
        urllib.request.urlretrieve(ARCHIVE_URL, path)  # noqa: S310 - fixed https URL, hashes pinned above
    check_archive(path)
    return path


# -- processing ----------------------------------------------------------------------------------------


def to_mono(data: np.ndarray) -> np.ndarray:
    return np.mean(data, axis=1, dtype=np.float64) if data.ndim == 2 else data.astype(np.float64)


def trim_and_fade(x: np.ndarray, rate: int = RATE) -> np.ndarray:
    """Head to 2 ms before the onset, inaudible tail dropped, then a raised-cosine fade-out."""
    peak = float(np.abs(x).max())
    onset = int(np.argmax(np.abs(x) > peak * 10 ** (ONSET_DB / 20)))
    start = max(0, onset - round(HEAD_MS * 1e-3 * rate))
    audible = np.nonzero(np.abs(x) > 10 ** (TAIL_FLOOR_DB / 20))[0]
    end = int(audible[-1]) + 1 if len(audible) else len(x)
    y = x[start:end].copy()
    n = min(len(y), round(FADE_MS * 1e-3 * rate))
    y[-n:] *= 0.5 * (1 + np.cos(np.linspace(0, np.pi, n)))
    return y


def peak_db(x: np.ndarray) -> float:
    return db(float(np.abs(x).max()))


def pick_takes(candidates: dict[int, np.ndarray], n: int, avoid: set[int] = frozenset()) -> list[int]:
    """The ``n`` takes whose peak is closest to the layer median (consistent levels), in take order."""
    pool = {k: v for k, v in candidates.items() if k not in avoid} or candidates
    med = float(np.median([peak_db(v) for v in pool.values()]))
    ranked = sorted(pool, key=lambda k: (abs(peak_db(pool[k]) - med), k))
    return sorted(ranked[:n])


def read_members(archive: Path, wanted: set[tuple[str, str]]) -> dict[tuple[str, str], dict[int, tuple[str,
    bytes]]]:
    """(instrument, dynamic) -> take index -> (member name, bytes); only the wanted members are read."""
    found: dict[tuple[str, str], dict[int, tuple[str, bytes]]] = {}
    with tarfile.open(archive, "r:bz2") as tar:
        for member in tar:
            m = MEMBER.match(member.name) if member.isfile() else None
            if m and (m.group(1), m.group(2)) in wanted:
                found.setdefault((m.group(1), m.group(2)), {})[int(m.group(3))] = (
                    member.name, tar.extractfile(member).read())
    return found


def decode(blob: bytes) -> np.ndarray:
    import io

    data, rate = sf.read(io.BytesIO(blob), dtype="float64", always_2d=True)
    if rate != RATE:
        raise SystemExit(f"unexpected source rate {rate}")
    return to_mono(data)


def build(archive: Path | None) -> int:
    archive = ensure_archive(archive)
    wanted = {(inst, dyn) for inst, hard, soft, _ in GROUPS.values() for dyn in (hard, soft)}
    found = read_members(archive, wanted)
    missing = wanted - set(found)
    if missing:
        raise SystemExit(f"archive lacks {sorted(missing)}")
    processed: dict[tuple[str, str], dict] = {}
    used_for_tom1: dict[str, set[int]] = {}  # layer -> take indices Tom 1 uses (same dynamic only)
    for group, (inst, hard_dyn, soft_dyn, _desc) in GROUPS.items():
        for layer, dyn in (("hard", hard_dyn), ("soft", soft_dyn)):
            raw = {i: trim_and_fade(decode(blob)) for i, (_, blob) in found[(inst, dyn)].items()}
            avoid = used_for_tom1.get(layer, set()) if group == "salamander-tom2" else set()
            chosen = pick_takes(raw, MAX_TAKES, avoid)
            if group == "salamander-tom1":
                used_for_tom1[layer] = set(chosen)
            takes = []
            for rr, i in enumerate(chosen, start=1):
                x = raw[i]
                if group == "salamander-tom2":
                    x = trim_and_fade(resample_poly(x, TOM2_RATIO.numerator, TOM2_RATIO.denominator))
                takes.append({"round_robin": rr, "source_take": i, "member": found[(inst, dyn)][i][0],
                    "x": x})
            processed[(group, layer)] = {"takes": takes, "dyn": dyn}
    # one kit-wide gain from the loudest hard take, then per-group soft-layer matching
    kit_gain = 10 ** ((TARGET_PEAK_DB - max(peak_db(t["x"]) for (g, la), v in processed.items()
                                              if la == "hard" for t in v["takes"])) / 20)
    entries = []
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for group in GROUPS:
        hard_med = float(np.median([peak_db(t["x"] * kit_gain) for t in processed[(group, "hard")]["takes"]]))
        soft_med = float(np.median([peak_db(t["x"] * kit_gain) for t in processed[(group, "soft")]["takes"]]))
        soft_trim = (hard_med - SOFT_BELOW_HARD_DB) - soft_med
        for layer in ("hard", "soft"):
            trim = 0.0 if layer == "hard" else soft_trim
            for t in processed[(group, layer)]["takes"]:
                y = np.clip(t["x"] * kit_gain * 10 ** (trim / 20), -1.0, 1.0)
                sample_id = f"{group}-{layer}-{t['round_robin']}"
                path = OUT_DIR / f"{sample_id}.wav"
                sf.write(path, y, RATE, subtype="PCM_24")
                entries.append({
                    "sample_id": sample_id, "file": f"acoustic/{path.name}",
                    "sha256": "sha256:" + hashes(path)["sha256"],
                    "group": group, "layer": layer, "round_robin": t["round_robin"],
                    "source_member": t["member"], "source_dynamic": processed[(group, layer)]["dyn"],
                    "derived": group in DERIVED, "trim_db": round(trim, 2), "peak_dbfs": round(peak_db(y), 2),
                    "duration_s": round(len(y) / RATE, 3),
                })
    doc = {
        "schema_version": "1.1",
        "asset_kind": "acoustic-drum-samples",
        "recordings": "genuine acoustic overhead-microphone recordings "
                      "(48 kHz / 24-bit stereo, mixed to mono)",
        "source": {"name": "The Salamander Drumkit", "author": "Alexander Holm", "page": ARCHIVE_PAGE,
                   "archive_url": ARCHIVE_URL, "archive_size": ARCHIVE_SIZE, "archive_md5": ARCHIVE_MD5,
                   "archive_sha1": ARCHIVE_SHA1, "archive_sha256": ARCHIVE_SHA256, "accessed": ACCESSED},
        "license_id": "CC-BY-SA-3.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
        "attribution": "The Salamander Drumkit by Alexander Holm, CC BY-SA 3.0; processed by Space Drums "
                       f"(recipe {RECIPE}: mono mixdown, head/tail trim with fade, kit-wide gain, "
                       "soft-layer trim).",
        "recipe": {"id": RECIPE, "sample_rate_hz": RATE, "target_peak_dbfs": TARGET_PEAK_DB,
        "kit_gain_db": round(db(kit_gain), 3),
                   "soft_below_hard_db": SOFT_BELOW_HARD_DB, "head_ms": HEAD_MS,
                   "tail_floor_dbfs": TAIL_FLOOR_DB,
                   "fade_ms": FADE_MS, "max_takes": MAX_TAKES,
                   "libraries": {"numpy": np.__version__, "soundfile": sf.__version__}},
        "groups": {g: {"source": GROUPS[g][3], "derived": DERIVED.get(g)} for g in GROUPS},
        "samples": entries,
    }
    MANIFEST.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(entries)} samples and {MANIFEST.relative_to(ROOT)} (kit gain {db(kit_gain):+.2f} dB)")
    return 0


def verify() -> int:
    doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    failures = []
    for e in doc["samples"]:
        path = SAMPLES / e["file"]
        actual = hashes(path)["sha256"] if path.exists() else None
        ok = actual == e["sha256"].removeprefix("sha256:")
        print(f"{'OK' if ok else 'FAIL'} {e['sample_id']} {actual or 'missing'}")
        if not ok:
            failures.append(e["sample_id"])
    if failures:
        raise SystemExit(
            f"acoustic sample verification failed ({len(failures)}); "
            "run: python scripts/fetch_acoustic_samples.py"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verify", action="store_true",
        help="offline: re-hash the built WAVs, build nothing")
    parser.add_argument("--archive", type=Path,
        help="use this local copy of the archive (still hash-checked)")
    args = parser.parse_args()
    return verify() if args.verify else build(args.archive)


if __name__ == "__main__":
    sys.exit(main())
