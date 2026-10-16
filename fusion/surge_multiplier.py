"""
Forecast fusion — deterministic, zero LLM calls.
Fuses ARIMA baseline with social signal surge. Capped and confidence-floored.
"""
from dataclasses import dataclass

MAX_SURGE_MULTIPLIER = 4.0
MIN_CONFIDENCE_THRESHOLD = 0.55
CORROBORATION_WEIGHT = 0.3
HORIZON_DECAY_PER_DAY = 0.05


@dataclass
class SocialSignal:
    sku: str
    momentum: str  # "high" | "medium" | "low" | "none"
    confidence: float  # 0.0–1.0
    corroborating_sources: int  # number of independent posts
    signal_age_hours: float


@dataclass
class FusionResult:
    sku: str
    baseline_units: int
    fused_units: int
    surge_multiplier: float
    confidence: float
    horizon_days: int
    capped: bool
    detail: str


def fuse(baseline_units: int, signal: SocialSignal, horizon_days: int = 7) -> FusionResult:
    """
    Fuse ARIMA baseline with social signal. Deterministic — no model calls.
    Returns a capped, confidence-floored forecast.
    """
    if signal.confidence < MIN_CONFIDENCE_THRESHOLD or signal.momentum == "none":
        return FusionResult(
            sku=signal.sku,
            baseline_units=baseline_units,
            fused_units=baseline_units,
            surge_multiplier=1.0,
            confidence=signal.confidence,
            horizon_days=horizon_days,
            capped=False,
            detail="Signal confidence below threshold or no momentum — baseline used",
        )

    momentum_base = {"high": 3.0, "medium": 1.8, "low": 1.3}.get(signal.momentum, 1.0)

    corroboration_boost = min(signal.corroborating_sources * CORROBORATION_WEIGHT, 1.0)

    age_hours = signal.signal_age_hours
    age_decay = max(0.0, 1.0 - (age_hours / 24) * HORIZON_DECAY_PER_DAY)

    raw_multiplier = momentum_base * (1 + corroboration_boost) * age_decay * signal.confidence

    capped = raw_multiplier > MAX_SURGE_MULTIPLIER
    final_multiplier = min(raw_multiplier, MAX_SURGE_MULTIPLIER)

    fused_units = round(baseline_units * final_multiplier)

    return FusionResult(
        sku=signal.sku,
        baseline_units=baseline_units,
        fused_units=fused_units,
        surge_multiplier=final_multiplier,
        confidence=signal.confidence,
        horizon_days=horizon_days,
        capped=capped,
        detail=(
            f"momentum={signal.momentum} base={momentum_base:.2f} "
            f"corroboration={corroboration_boost:.2f} decay={age_decay:.2f} "
            f"raw={raw_multiplier:.2f} {'CAPPED at 4×' if capped else ''}"
        ),
    )
