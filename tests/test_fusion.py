"""Unit tests for fusion/surge_multiplier — cap, floor, decay."""
import sys
sys.path.insert(0, "/home/appadmin/groundswell")

from fusion.surge_multiplier import fuse, SocialSignal, MAX_SURGE_MULTIPLIER, MIN_CONFIDENCE_THRESHOLD


def _sig(momentum="high", confidence=0.81, sources=4, age_hours=6.0, sku="SHOE-PEG41-GRY"):
    return SocialSignal(sku=sku, momentum=momentum, confidence=confidence,
                        corroborating_sources=sources, signal_age_hours=age_hours)


def test_high_momentum_beats_arima():
    result = fuse(31, _sig())
    assert result.fused_units > result.baseline_units


def test_multiplier_capped_at_4x():
    result = fuse(100, _sig(momentum="high", confidence=0.99, sources=100, age_hours=0.1))
    assert result.surge_multiplier <= MAX_SURGE_MULTIPLIER
    assert result.capped is True


def test_low_confidence_uses_baseline():
    result = fuse(50, _sig(momentum="high", confidence=0.3))
    assert result.fused_units == result.baseline_units
    assert result.surge_multiplier == 1.0


def test_none_momentum_uses_baseline():
    result = fuse(50, _sig(momentum="none", confidence=0.9))
    assert result.fused_units == result.baseline_units


def test_spec_demo_scenario():
    # The spec claims: baseline 31, fused 142 on the PEG41 viral scenario
    result = fuse(31, _sig(momentum="high", confidence=0.81, sources=4, age_hours=6.0))
    assert result.fused_units > 31
    assert result.fused_units <= 31 * MAX_SURGE_MULTIPLIER


def test_old_signal_decays():
    fresh = fuse(100, _sig(age_hours=1.0))
    old = fuse(100, _sig(age_hours=200.0))
    assert fresh.surge_multiplier >= old.surge_multiplier


def test_medium_momentum_lower_than_high():
    high_result = fuse(100, _sig(momentum="high"))
    med_result = fuse(100, _sig(momentum="medium"))
    assert high_result.surge_multiplier >= med_result.surge_multiplier
