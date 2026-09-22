"""Stable feature groups for Phase 19; no data-dependent selection."""

GROUPS = ("POS", "VEL", "ACC", "JERK", "AXIS", "HAND", "ZONE", "CONF", "TIME")
DEFAULT_GROUPS = tuple(g for g in GROUPS if g != "JERK")
ROBUST_GROUPS = frozenset(("VEL", "ACC", "JERK"))


def group_indices(schema, groups):
    groups = set(groups)
    if not groups <= set(GROUPS):
        raise ValueError("unknown feature group")
    return [i for i, f in enumerate(schema.fields) if f["group"] in groups]
