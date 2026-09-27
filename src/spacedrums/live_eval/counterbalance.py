"""Arm-order counterbalancing for the live experiment (pre-registration §9).

The arm is a blocked within-participant factor. Order effects (practice, fatigue, carry-over from
hearing anticipatory sound) are balanced with a **Williams design**.

* For an even number of arms ``n``, one Williams square of ``n`` sequences balances both position
  and first-order carry-over.
* For odd ``n``, the square plus its row-reversed mirror is needed (``2n`` sequences).

For the three live arms (A, B, C) that gives six sequences: every permutation. Each arm then takes
each position twice, and each ordered pair of adjacent arms occurs twice.

Assignment is deterministic: ``sequence_index = (participant_index - 1) mod len(sequences)``. The
index is recorded in ``LiveSessionMetadata``, so the order is reproducible from the metadata alone.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

LIVE_ARMS = ("A", "B", "C")


def williams_sequences(n: int) -> list[tuple[int, ...]]:
    """Williams design over ``range(n)``: ``n`` sequences (``n`` even) or ``2n`` (``n`` odd)."""
    if n < 2:
        raise ValueError("counterbalancing needs at least two arms")
    first, lo, hi = [0], 1, n - 1
    take_low = True
    while len(first) < n:
        if take_low:
            first.append(lo)
            lo += 1
        else:
            first.append(hi)
            hi -= 1
        take_low = not take_low
    square = [tuple((x + r) % n for x in first) for r in range(n)]
    if n % 2 == 0:
        return square
    return square + [tuple(reversed(row)) for row in square]


def arm_sequences(arms: Sequence[str] = LIVE_ARMS) -> list[tuple[str, ...]]:
    if len(set(arms)) != len(arms):
        raise ValueError("arm labels must be distinct")
    return [tuple(arms[i] for i in row) for row in williams_sequences(len(arms))]


def arm_order(participant_index: int, arms: Sequence[str] = LIVE_ARMS) -> dict[str, Any]:
    """The arm order of the ``participant_index``-th live participant (1-based, as recorded)."""
    if participant_index < 1:
        raise ValueError("participant_index is 1-based")
    sequences = arm_sequences(arms)
    index = (participant_index - 1) % len(sequences)
    return {
        "participant_index": participant_index,
        "sequence_index": index,
        "order": list(sequences[index]),
        "design": f"Williams-{len(arms)}",
        "n_sequences": len(sequences),
    }


def balance_report(sequences: Sequence[Sequence[str]]) -> dict[str, Any]:
    """Position counts and ordered first-order carry-over counts of a set of sequences."""
    position = Counter((arm, pos) for seq in sequences for pos, arm in enumerate(seq))
    carry = Counter((a, b) for seq in sequences for a, b in zip(seq, seq[1:], strict=False))
    arms = sorted({a for seq in sequences for a in seq})
    return {
        "arms": arms,
        "position": {f"{a}@{p}": position[(a, p)] for a in arms for p in range(len(arms))},
        "carryover": {f"{a}->{b}": carry[(a, b)] for a in arms for b in arms if a != b},
        "position_balanced": len({position[(a, p)] for a in arms for p in range(len(arms))}) == 1,
        "carryover_balanced": len({carry[(a, b)] for a in arms for b in arms if a != b}) == 1,
    }


__all__ = ["LIVE_ARMS", "arm_order", "arm_sequences", "balance_report", "williams_sequences"]
