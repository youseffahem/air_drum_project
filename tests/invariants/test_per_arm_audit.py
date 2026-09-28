"""SYNTHETIC/DEV negative controls for unequal per-arm refractory deadlines."""

from inv_helpers import strike

from spacedrums.commit import CommitAuditor, CommitSettings
from spacedrums.contracts import Arm


def test_audible_refractory_uses_previous_arm_deadline(registry):
    auditor = CommitAuditor(
        CommitSettings(),
        registry,
        settings_by_arm={
            Arm.A: CommitSettings(refractory_zone_s=0.3, refractory_hand_s=0.2),
            Arm.B: CommitSettings(refractory_zone_s=0.05, refractory_hand_s=0.01),
        },
    )
    first = strike(0, 1.0, arm=Arm.A)
    next_arm = strike(1, 1.1, arm=Arm.B, source="RULE")
    assert auditor._refractory("AUDIBLE", first, 0, 1.0) == []
    # B's shorter own timer must not erase the deadline inherited from A.
    assert len(auditor._refractory("AUDIBLE", next_arm, 1, 1.1)) == 2
    after = strike(2, 1.31, arm=Arm.B, source="RULE")
    assert auditor._refractory("AUDIBLE", after, 2, 1.31) == []


def test_longer_destination_timer_does_not_retroactively_extend_prior_arm(registry):
    auditor = CommitAuditor(
        CommitSettings(),
        registry,
        settings_by_arm={
            Arm.A: CommitSettings(refractory_zone_s=0.05, refractory_hand_s=0.01),
            Arm.B: CommitSettings(refractory_zone_s=0.3, refractory_hand_s=0.2),
        },
    )
    assert not auditor._refractory("AUDIBLE", strike(0, 1.0, arm=Arm.A), 0, 1.0)
    assert not auditor._refractory("AUDIBLE", strike(1, 1.1, arm=Arm.B, source="RULE"), 1, 1.1)
