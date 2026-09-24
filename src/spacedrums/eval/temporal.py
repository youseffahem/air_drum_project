"""The Phase 10 MODEL-only wrapper; geometry owns every candidate."""

from dataclasses import replace


def temporal_candidate(candidate, registry):
    if candidate is None:
        return None
    normal = registry[candidate.zone_id].inward_normal
    inward_speed = sum(v * n for v, n in zip(candidate.crossing_velocity, normal, strict=True))
    return replace(candidate, intensity_proxy=max(0.0, inward_speed))
