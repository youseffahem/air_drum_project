"""Shared, colour-blind-friendly visual theme for the Phase 15 developer UI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    background: tuple[int, int, int] = (24, 24, 28)
    panel: tuple[int, int, int] = (38, 38, 44)
    text: tuple[int, int, int] = (238, 238, 242)
    muted: tuple[int, int, int] = (155, 155, 165)
    left: tuple[int, int, int] = (0, 190, 255)
    right: tuple[int, int, int] = (255, 145, 35)
    arm_a: tuple[int, int, int] = (245, 200, 70)
    arm_b: tuple[int, int, int] = (80, 210, 250)
    arm_c: tuple[int, int, int] = (215, 110, 255)
    ok: tuple[int, int, int] = (70, 220, 100)
    warning: tuple[int, int, int] = (0, 205, 255)
    error: tuple[int, int, int] = (70, 70, 245)
    ground_truth: tuple[int, int, int] = (255, 255, 255)


DEFAULT_THEME = Theme()


def arm_color(arm: str | None, theme: Theme = DEFAULT_THEME) -> tuple[int, int, int]:
    value = str(arm or "")
    if value == "A":
        return theme.arm_a
    if value == "B":
        return theme.arm_b
    return theme.arm_c


__all__ = ["DEFAULT_THEME", "Theme", "arm_color"]
