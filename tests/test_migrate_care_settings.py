"""Unit tests for the care-setting migration's remap logic."""

from __future__ import annotations

from nhs_policy_navigator.pipeline.migrate_care_settings import remap


def test_remap_collapses_old_settings_into_buckets() -> None:
    assert remap(["Acute"]) == ["Secondary care"]
    assert remap(["Ambulance"]) == ["Secondary care"]
    assert remap(["Mental Health and Learning Disability"]) == ["Secondary care"]
    assert remap(["Primary Care"]) == ["Primary care"]
    assert remap(["Primary Care - Wider Primary Care"]) == ["Wider Primary care"]


def test_remap_dedupes_after_mapping() -> None:
    assert remap(["Acute", "Ambulance", "Community"]) == ["Secondary care"]


def test_remap_drops_unknown_values() -> None:
    assert remap(["Wizardry"]) == []


def test_remap_is_idempotent_for_new_values() -> None:
    assert remap(["Secondary care", "Primary care"]) == ["Secondary care", "Primary care"]


def test_remap_preserves_order() -> None:
    assert remap(["Primary Care", "Acute"]) == ["Primary care", "Secondary care"]
