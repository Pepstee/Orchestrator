"""The prime directive — every ACTIVE law names a machine-check, or the build fails."""
from __future__ import annotations

from charter.laws import LAWS, active_laws_missing_check


def test_every_active_law_has_a_check():
    missing = active_laws_missing_check()
    assert not missing, (
        "active laws without a check (prime-directive violation): "
        f"{[law.id for law in missing]}"
    )


def test_law_ids_are_unique():
    ids = [law.id for law in LAWS]
    assert len(ids) == len(set(ids)), "duplicate law ids"
