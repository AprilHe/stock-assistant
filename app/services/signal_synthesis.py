"""Signal synthesis service for explaining merged candidate state."""

from __future__ import annotations

import json

from domain.schemas.signals import AggregatedCandidate, SignalSynthesis, StrategySignal


def _signals_by_ticker(signals: list[StrategySignal]) -> dict[str, list[StrategySignal]]:
    grouped: dict[str, list[StrategySignal]] = {}
    for signal in signals:
        grouped.setdefault(signal.ticker, []).append(signal)
    return grouped


def _conviction(candidate: AggregatedCandidate) -> str:
    if candidate.aggregate_score >= 0.70 and candidate.aggregate_confidence >= 0.65:
        return "high"
    if candidate.aggregate_score >= 0.58 and candidate.aggregate_confidence >= 0.52:
        return "medium"
    return "low"


def _signal_alignment(candidate: AggregatedCandidate) -> dict[str, float]:
    return {
        signal.strategy_id: signal.score_normalized
        for signal in candidate.strategy_signals
    }


def _key_supports(candidate: AggregatedCandidate, signals: list[StrategySignal]) -> list[str]:
    supports: list[str] = []
    if candidate.agreement_level == "high":
        supports.append("multiple strategies are strongly aligned on the same directional view")
    elif candidate.agreement_level == "medium":
        supports.append("more than one strategy supports the current directional bias")

    primary = max(signals, key=lambda item: (item.score_normalized, item.confidence), default=None)
    if primary is not None:
        supports.extend(primary.evidence[:2])

    sector = str(candidate.metadata.get("sector", "")).strip()
    if sector:
        supports.append(f"portfolio context can evaluate this setup within the {sector} bucket")

    deduped: list[str] = []
    for item in supports:
        if item and item not in deduped:
            deduped.append(item)
    return deduped[:4]


def _key_risks(candidate: AggregatedCandidate, signals: list[StrategySignal]) -> list[str]:
    risks: list[str] = []
    if candidate.conflicts:
        risks.extend(candidate.conflicts)

    risk_flags: list[str] = []
    for signal in signals:
        risk_flags.extend(signal.risk_flags)
    for risk in risk_flags:
        if risk not in risks:
            risks.append(risk)

    if candidate.agreement_level == "low":
        risks.append("signal agreement is limited, so conviction should stay measured")

    return risks[:4]


def _summary(candidate: AggregatedCandidate, supports: list[str], risks: list[str]) -> str:
    support_text = supports[0] if supports else "signal support is limited"
    risk_text = risks[0] if risks else "no major cross-strategy conflict is currently detected"
    return (
        f"{candidate.aggregate_direction.title()} bias with {candidate.agreement_level} agreement: "
        f"{support_text}; key risk is {risk_text}."
    )


def synthesize_candidate(
    candidate: AggregatedCandidate,
    signals: list[StrategySignal],
) -> SignalSynthesis:
    """Explain merged candidate state without changing deterministic decisions."""
    supports = _key_supports(candidate, signals)
    risks = _key_risks(candidate, signals)
    return SignalSynthesis(
        ticker=candidate.ticker,
        overall_direction=candidate.aggregate_direction,
        conviction=_conviction(candidate),
        signal_alignment=_signal_alignment(candidate),
        summary=_summary(candidate, supports, risks),
        key_supports=supports,
        key_risks=risks,
    )


def synthesize_candidates(
    candidates: list[AggregatedCandidate],
    signals: list[StrategySignal],
) -> list[SignalSynthesis]:
    """Generate synthesis objects for all merged candidates."""
    grouped_signals = _signals_by_ticker(signals)
    return [
        synthesize_candidate(candidate, grouped_signals.get(candidate.ticker, []))
        for candidate in candidates
    ]


def synthesize_candidate_with_ai(
    candidate: AggregatedCandidate,
    signals: list[StrategySignal],
) -> SignalSynthesis:
    """Optionally enhance deterministic synthesis with an LLM explanation.

    Falls back to the deterministic synthesis if the AI path is unavailable
    or returns invalid structured output.
    """
    deterministic = synthesize_candidate(candidate, signals)

    try:
        from core.ai_analysis import _call_llm_json_with_retries
    except Exception:
        return deterministic

    prompt = (
        "You are explaining a merged trading candidate. Return valid raw JSON only.\n\n"
        f"Candidate:\n{json.dumps(candidate.model_dump(), ensure_ascii=True)}\n\n"
        f"Underlying signals:\n{json.dumps([signal.model_dump() for signal in signals], ensure_ascii=True)}\n\n"
        "Return JSON with this exact structure:\n"
        "{\n"
        '  "summary": "<1 concise sentence>",\n'
        '  "key_supports": ["<support 1>", "<support 2>", "<support 3>"],\n'
        '  "key_risks": ["<risk 1>", "<risk 2>", "<risk 3>"]\n'
        "}\n"
        "Keep supports and risks short, factual, and grounded in the provided evidence."
    )
    parsed = _call_llm_json_with_retries(prompt, retries=1)
    if parsed is None:
        return deterministic

    summary = str(parsed.get("summary", "")).strip() or deterministic.summary
    key_supports = [str(item).strip() for item in parsed.get("key_supports", []) if str(item).strip()]
    key_risks = [str(item).strip() for item in parsed.get("key_risks", []) if str(item).strip()]

    return SignalSynthesis(
        ticker=deterministic.ticker,
        overall_direction=deterministic.overall_direction,
        conviction=deterministic.conviction,
        signal_alignment=deterministic.signal_alignment,
        summary=summary,
        key_supports=key_supports[:4] or deterministic.key_supports,
        key_risks=key_risks[:4] or deterministic.key_risks,
    )


def synthesize_candidates_ai_enhanced(
    candidates: list[AggregatedCandidate],
    signals: list[StrategySignal],
) -> list[SignalSynthesis]:
    """AI-enhanced synthesis with deterministic fallback for every candidate."""
    grouped_signals = _signals_by_ticker(signals)
    return [
        synthesize_candidate_with_ai(candidate, grouped_signals.get(candidate.ticker, []))
        for candidate in candidates
    ]
