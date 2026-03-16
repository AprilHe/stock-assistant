"""
app/services/candidate_merge_service.py

Layer 3 of the v2 pipeline: Signal Normalization and Candidate Merge.

Responsibilities:
- Group StrategySignals by ticker.
- Compute a confidence-weighted aggregate score and confidence.
- Detect directional conflicts.
- Assign an agreement_level label.
- Rank candidates by aggregate_score.

Design decisions (v1):
- Base weight = 1.0 for all strategies (equal-weight).
- Effective weight = base_weight × confidence, so a low-confidence signal
  contributes less to the aggregate without being fully excluded.
- Directional conflict penalty: if any signal direction differs from the
  majority, aggregate_score is reduced by CONFLICT_PENALTY per conflicting
  signal, and the conflict is written to AggregatedCandidate.conflicts.
  In v1 all evaluators only emit "long", so conflicts are rare; the
  mechanism is ready for when short signals are added.
- agreement_level rules:
    "high"     — 3+ strategies firing, score std < 0.12
    "medium"   — 2+ strategies firing, score std < 0.18
    "low"      — 1 strategy firing, or high score dispersion
    "conflict" — directional conflict detected

Replace CONFLICT_PENALTY and agreement thresholds when Phase 4 calibration
data is available.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone as dt_tz
from pathlib import Path

from domain.schemas.signals import (
    AggregatedCandidate,
    CandidateSignalView,
    StrategySignal,
)

logger = logging.getLogger(__name__)

_CALIBRATION_DIR = Path(__file__).parent.parent.parent / "data" / "calibration"

# Tune these constants when calibration data arrives (Phase 4).
CONFLICT_PENALTY: float = 0.05   # score reduction per conflicting signal
_HIGH_AGREEMENT_MIN_SIGNALS: int = 3
_HIGH_AGREEMENT_STD_THRESHOLD: float = 0.12
_MEDIUM_AGREEMENT_MIN_SIGNALS: int = 2
_MEDIUM_AGREEMENT_STD_THRESHOLD: float = 0.18


def _load_strategy_weights(path: Path | None = None) -> dict[str, float]:
    """Load per-strategy base weights from data/calibration/strategy_weights.json.

    Falls back to equal weights (1.0) if the file is missing or malformed.
    Provides the hook for Phase 4 backtest-derived calibration without requiring
    source code changes.
    """
    weights_path = path or (_CALIBRATION_DIR / "strategy_weights.json")
    if not weights_path.exists():
        return {}
    try:
        data = json.loads(weights_path.read_text(encoding="utf-8"))
        return {k: float(v) for k, v in data.items() if not k.startswith("_") and isinstance(v, (int, float))}
    except Exception as exc:
        logger.warning("Failed to load strategy weights from %s: %s; using equal weights.", weights_path, exc)
        return {}


# Load once at module import; reload is not needed during normal operation.
_STRATEGY_WEIGHTS: dict[str, float] = _load_strategy_weights()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _std(values: list[float]) -> float:
    """Population std dev.  Returns 0.0 for single-element lists."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / n)


def _majority_direction(signals: list[StrategySignal]) -> str:
    counts: dict[str, int] = {}
    for s in signals:
        counts[s.direction] = counts.get(s.direction, 0) + 1
    return max(counts, key=lambda d: counts[d])


def _detect_conflicts(
    signals: list[StrategySignal],
    majority_direction: str,
) -> list[str]:
    """Return human-readable conflict notes for signals that disagree."""
    conflicts: list[str] = []
    for s in signals:
        if s.direction != majority_direction:
            conflicts.append(
                f"{s.strategy_id} signals {s.direction!r} "
                f"(majority is {majority_direction!r})"
            )
    return conflicts


def _agreement_label(
    n_signals: int,
    score_std: float,
    has_conflict: bool,
) -> str:
    if has_conflict:
        return "low"
    if n_signals >= _HIGH_AGREEMENT_MIN_SIGNALS and score_std < _HIGH_AGREEMENT_STD_THRESHOLD:
        return "high"
    if n_signals >= _MEDIUM_AGREEMENT_MIN_SIGNALS and score_std < _MEDIUM_AGREEMENT_STD_THRESHOLD:
        return "medium"
    return "low"


def _merge_candidate_metadata(signals: list[StrategySignal]) -> dict[str, float | int | str | bool]:
    if not signals:
        return {}

    merged: dict[str, float | int | str | bool] = {}
    strongest = max(signals, key=lambda item: (item.score_normalized, item.confidence))
    for key, value in strongest.metadata.items():
        merged[key] = value

    merged["primary_strategy_id"] = strongest.strategy_id
    merged["primary_horizon"] = strongest.horizon
    if strongest.validity_template:
        merged["primary_validity_template"] = strongest.validity_template

    for key in ("asset_type", "sector", "industry"):
        if key in merged and merged[key]:
            continue
        for signal in signals:
            candidate_value = signal.metadata.get(key)
            if candidate_value not in (None, ""):
                merged[key] = candidate_value
                break

    return merged


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def merge_signals(signals: list[StrategySignal]) -> list[AggregatedCandidate]:
    """Merge a flat list of StrategySignals into per-ticker AggregatedCandidates.

    Steps per ticker:
    1. Compute effective_weight = 1.0 × confidence per signal.
    2. Confidence-weighted mean → aggregate_score and aggregate_confidence.
    3. Detect directional conflicts; apply CONFLICT_PENALTY per conflict.
    4. Compute score std and assign agreement_level.
    5. Sort final candidates by aggregate_score descending; assign rank.
    """
    if not signals:
        return []

    # Group by ticker
    by_ticker: dict[str, list[StrategySignal]] = {}
    for s in signals:
        by_ticker.setdefault(s.ticker, []).append(s)

    generated_at = datetime.now(dt_tz.utc).isoformat()
    candidates: list[AggregatedCandidate] = []

    for ticker, ticker_signals in by_ticker.items():
        majority_dir = _majority_direction(ticker_signals)
        conflicts = _detect_conflicts(ticker_signals, majority_dir)

        # Confidence-weighted aggregate
        total_weight = 0.0
        weighted_score_sum = 0.0
        weighted_conf_sum = 0.0

        for s in ticker_signals:
            base_weight = _STRATEGY_WEIGHTS.get(s.strategy_id, 1.0)
            effective_weight = base_weight * s.confidence
            total_weight += effective_weight
            weighted_score_sum += s.score_normalized * effective_weight
            weighted_conf_sum += s.confidence * effective_weight

        if total_weight <= 0:
            continue

        agg_score = weighted_score_sum / total_weight
        agg_conf = weighted_conf_sum / total_weight

        # Conflict penalty
        agg_score -= len(conflicts) * CONFLICT_PENALTY
        agg_score = max(0.0, min(1.0, agg_score))

        # Agreement level
        score_std = _std([s.score_normalized for s in ticker_signals])
        agreement = _agreement_label(len(ticker_signals), score_std, bool(conflicts))

        # Build compact signal views for the candidate
        signal_views = [
            CandidateSignalView(
                strategy_id=s.strategy_id,
                score_normalized=round(s.score_normalized, 4),
                confidence=round(s.confidence, 4),
                direction=s.direction,
                horizon=s.horizon,
                validity_template=s.validity_template,
                metadata=s.metadata,
            )
            for s in sorted(ticker_signals, key=lambda x: x.score_normalized, reverse=True)
        ]

        candidates.append(
            AggregatedCandidate(
                ticker=ticker,
                aggregate_direction=majority_dir,
                aggregate_score=round(agg_score, 4),
                aggregate_confidence=round(agg_conf, 4),
                strategy_signals=signal_views,
                agreement_level=agreement,
                conflicts=conflicts,
                generated_at=generated_at,
                metadata=_merge_candidate_metadata(ticker_signals),
            )
        )

    # Sort by aggregate_score descending and assign preliminary_rank
    candidates.sort(key=lambda c: c.aggregate_score, reverse=True)
    for rank, candidate in enumerate(candidates, start=1):
        candidate.preliminary_rank = rank

    return candidates
