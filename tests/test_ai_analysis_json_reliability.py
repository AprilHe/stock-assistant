import sys
from types import SimpleNamespace

sys.modules.setdefault("yfinance", SimpleNamespace(Ticker=lambda *args, **kwargs: None))
sys.modules.setdefault(
    "litellm",
    SimpleNamespace(completion=lambda *args, **kwargs: None),
)
sys.modules.setdefault("dotenv", SimpleNamespace(load_dotenv=lambda: None))

from core import ai_analysis


def test_call_llm_json_with_retries_recovers_on_second_attempt(monkeypatch):
    responses = iter([
        "not valid json",
        '{"tickers": [{"symbol": "AAPL", "signal": "Hold", "score": 50, "one_line": "range-bound", "validity": "This week", "risk": "no edge"}]}',
    ])

    monkeypatch.setattr(ai_analysis, "_call_llm", lambda prompt: next(responses))

    parsed = ai_analysis._call_llm_json_with_retries("return json", retries=2)

    assert parsed is not None
    assert parsed["tickers"][0]["symbol"] == "AAPL"


def test_generate_market_summary_uses_fallback_when_json_unavailable(monkeypatch):
    monkeypatch.setattr(ai_analysis, "_call_llm_json_with_retries", lambda prompt, retries=2, validator=None: None)

    market_data = {
        "_as_of": "2026-03-15",
        "Apple": {"ticker": "AAPL", "price": 200.0, "change_pct": 0.4},
        "Tesla": {"ticker": "TSLA", "price": 180.0, "change_pct": -2.1},
    }

    rendered = ai_analysis.generate_market_summary(market_data, news=[], schedule="daily", language="en")

    assert "AAPL" in rendered
    assert "TSLA" in rendered
    assert "Market Dashboard" in rendered


def test_analyze_ticker_structured_falls_back_cleanly_when_llm_json_fails(monkeypatch):
    fake_history = SimpleNamespace(
        empty=False,
        __getitem__=lambda self, key: SimpleNamespace(
            iloc=[100.0, 101.0],
            max=lambda: 105.0,
            min=lambda: 95.0,
        ),
    )

    class FakeTicker:
        def history(self, period="1mo"):
            return {
                "Close": SimpleNamespace(iloc=[100.0, 101.0]),
                "High": SimpleNamespace(max=lambda: 105.0),
                "Low": SimpleNamespace(min=lambda: 95.0),
                "empty": False,
            }

    class FakeFrame:
        empty = False

        def __getitem__(self, key):
            if key == "Close":
                return SimpleNamespace(iloc=[100.0, 101.0])
            if key == "High":
                return SimpleNamespace(max=lambda: 105.0)
            return SimpleNamespace(min=lambda: 95.0)

    monkeypatch.setattr(ai_analysis.yf, "Ticker", lambda ticker: SimpleNamespace(history=lambda period="1mo": FakeFrame()))
    monkeypatch.setattr(ai_analysis, "get_market_news", lambda query="", num_articles=5: [])
    monkeypatch.setattr(ai_analysis, "_call_llm_json_with_retries", lambda prompt, retries=2, validator=None: None)

    result = ai_analysis.analyze_ticker_structured("AAPL")

    assert result["proposal"] == "Hold"
    assert result["confidence"] == 50
    assert "unstructured output" in result["summary"].lower()


def test_validate_dashboard_json_rejects_missing_fields():
    """Valid JSON that lacks required fields should not pass schema validation."""
    good = {"tickers": [{"symbol": "AAPL", "signal": "Hold", "score": 50, "one_line": "flat"}]}
    assert ai_analysis._validate_dashboard_json(good) is True

    missing_signal = {"tickers": [{"symbol": "AAPL", "score": 50, "one_line": "flat"}]}
    assert ai_analysis._validate_dashboard_json(missing_signal) is False

    no_tickers_list = {"tickers": "AAPL"}
    assert ai_analysis._validate_dashboard_json(no_tickers_list) is False

    empty_root = {}
    assert ai_analysis._validate_dashboard_json(empty_root) is False


def test_validate_ticker_analysis_json_rejects_missing_fields():
    """Valid JSON that lacks required fields should not pass schema validation."""
    good = {"proposal": "Buy", "confidence": 72, "summary": "strong setup", "reasoning": ["r1"]}
    assert ai_analysis._validate_ticker_analysis_json(good) is True

    missing_reasoning = {"proposal": "Buy", "confidence": 72, "summary": "ok"}
    assert ai_analysis._validate_ticker_analysis_json(missing_reasoning) is False

    reasoning_not_list = {"proposal": "Buy", "confidence": 72, "summary": "ok", "reasoning": "r1"}
    assert ai_analysis._validate_ticker_analysis_json(reasoning_not_list) is False


def test_schema_validation_failure_triggers_retry(monkeypatch):
    """A structurally invalid response (missing required field) should trigger a retry."""
    # First response: valid JSON but missing 'one_line' — fails schema validation
    # Second response: valid JSON with all required fields — passes
    responses = iter([
        '{"tickers": [{"symbol": "AAPL", "signal": "Hold", "score": 50}]}',
        '{"tickers": [{"symbol": "AAPL", "signal": "Hold", "score": 50, "one_line": "ok", "validity": "Today", "risk": "none"}]}',
    ])

    monkeypatch.setattr(ai_analysis, "_call_llm", lambda prompt: next(responses))

    parsed = ai_analysis._call_llm_json_with_retries(
        "return json", retries=2, validator=ai_analysis._validate_dashboard_json
    )

    assert parsed is not None
    assert parsed["tickers"][0]["one_line"] == "ok"


def test_all_retries_exhausted_returns_none(monkeypatch):
    """When all retries are exhausted, the function returns None."""
    monkeypatch.setattr(ai_analysis, "_call_llm", lambda prompt: "not valid json at all")

    parsed = ai_analysis._call_llm_json_with_retries("return json", retries=2)
    assert parsed is None
