import asyncio
from types import SimpleNamespace

from fastapi import Response

import main


def test_api_screen_sets_legacy_compatibility_headers(monkeypatch):
    monkeypatch.setattr(
        "app.services.research_service.build_screen_response",
        lambda **kwargs: SimpleNamespace(model_dump=lambda: {"strategy": "breakout", "candidates": []}),
    )

    response = Response()
    payload = asyncio.run(
        main.api_screen(
            strategy="breakout",
            asset_type="stock",
            top_n=5,
            tickers="AAPL",
            response=response,
        )
    )

    assert payload["strategy"] == "breakout"
    assert response.headers["X-Stock-Assistant-Endpoint-Status"] == "legacy-compatible"
    assert response.headers["X-Stock-Assistant-Replacement"] == "/api/candidates/latest"
