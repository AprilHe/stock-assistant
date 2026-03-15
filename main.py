"""
main.py
FastAPI application — serves the web dashboard and API endpoints.
Also starts the APScheduler and Telegram bot on startup.
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    # Start APScheduler
    from core.scheduler import create_scheduler
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("APScheduler started — weekly report scheduled for Monday 08:00.")

    # Start Telegram bot in a background thread (if token is configured)
    if TELEGRAM_BOT_TOKEN:
        from channels.telegram.bot import start_bot_thread
        start_bot_thread(TELEGRAM_BOT_TOKEN)
        logger.info("Telegram bot started in background thread.")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram bot disabled.")

    yield

    # --- Shutdown ---
    scheduler.shutdown(wait=False)
    logger.info("APScheduler stopped.")


app = FastAPI(
    title="Stock Assistant",
    description="AI-powered market analysis — weekly summaries + on-demand ticker analysis.",
    version="1.0.0",
    lifespan=lifespan,
)

# Serve static files from web/
app.mount("/static", StaticFiles(directory="web"), name="static")


class PreferencesUpdateRequest(BaseModel):
    watchlist: list[str]
    strategies: list[str]
    report_sections: list[str]
    report_mode: str
    schedule: str
    language: str
    timezone: str
    push_time: str
    push_mode: str = "simple"


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def index():
    return FileResponse("web/index.html")


@app.get("/api/summary")
async def api_summary():
    """
    Returns an AI-generated market summary as JSON.
    Fetches live price data and news, then calls the LLM.
    """
    try:
        from app.services.research_service import build_global_summary_response
        return build_global_summary_response().model_dump()
    except Exception as e:
        logger.error(f"GET /api/summary failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analyze/{ticker}")
async def api_analyze(ticker: str, strategy: str = ""):
    """
    Returns an AI analysis for the given ticker symbol (e.g. AAPL, META).
    Optional query param:
      - strategy=<strategy_id from /api/strategies>
    """
    try:
        from app.services.research_service import build_ticker_analysis_response
        return build_ticker_analysis_response(ticker, strategy=strategy).model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"GET /api/analyze/{ticker} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/strategies")
async def api_strategies(capability: str = ""):
    """Lists strategy definitions. Optional capability=analysis|screen|backtest."""
    try:
        from app.services.research_service import build_strategy_list_response
        return build_strategy_list_response(capability=capability).model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"GET /api/strategies failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/strategies/{strategy_id}")
async def api_strategy_detail(strategy_id: str, capability: str = ""):
    """Returns full strategy config and documentation."""
    try:
        from app.services.research_service import build_strategy_detail_response
        return build_strategy_detail_response(strategy_id, capability=capability).model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"GET /api/strategies/{strategy_id} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/market")
async def api_market():
    """Returns raw market snapshot data (prices + % change) without LLM."""
    try:
        from app.services.research_service import build_market_snapshot_response
        return build_market_snapshot_response().model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/screen")
async def api_screen(
    strategy: str = "breakout",
    asset_type: str = "stock",
    top_n: int = 5,
    tickers: str = "",
):
    """
    Returns ranked daily/swing candidates by strategy.
    Optional query params:
      - strategy=<strategy_id from /api/strategies?capability=screen>
      - asset_type=stock|commodity
      - top_n=1..50
      - tickers=AAPL,NVDA,MSFT
    """
    try:
        from app.services.research_service import build_screen_response

        parsed_tickers = [t.strip() for t in tickers.split(",") if t.strip()] if tickers else None
        return build_screen_response(
            strategy=strategy,
            asset_type=asset_type,
            tickers=parsed_tickers,
            top_n=top_n,
        ).model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"GET /api/screen failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/backtest")
async def api_backtest(
    ticker: str,
    strategy: str = "breakout",
    start_date: str = "2024-01-01",
    end_date: str = "2025-01-01",
    initial_cash: float = 10000,
    fee_bps: float = 10,
    slippage_bps: float = 5,
    stop_loss_pct: float = 8,
    take_profit_pct: float = 15,
    max_holding_days: int = 20,
):
    """
    Runs a deterministic daily backtest for one ticker and one strategy.
    Example:
      /api/backtest?ticker=AAPL&strategy=breakout&start_date=2024-01-01&end_date=2025-01-01
    """
    try:
        from app.services.research_service import build_backtest_response
        return build_backtest_response(
            ticker=ticker,
            strategy=strategy,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            max_holding_days=max_holding_days,
        ).model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"GET /api/backtest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/preferences/{profile_id}")
async def api_get_preferences(profile_id: str):
    """Returns persisted preferences for a web or messaging profile."""
    try:
        from core.preferences import get_prefs
        return get_prefs(profile_id)
    except Exception as e:
        logger.error(f"GET /api/preferences/{profile_id} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/preferences/{profile_id}")
async def api_update_preferences(profile_id: str, payload: PreferencesUpdateRequest):
    """Updates persisted preferences for a web or messaging profile."""
    try:
        from core.preferences import update_prefs
        return update_prefs(
            chat_id=profile_id,
            watchlist=payload.watchlist,
            strategies=payload.strategies,
            report_sections=payload.report_sections,
            report_mode=payload.report_mode,
            schedule=payload.schedule,
            language=payload.language,
            timezone=payload.timezone,
            push_time=payload.push_time,
            push_mode=payload.push_mode,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"PUT /api/preferences/{profile_id} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/report/{profile_id}")
async def api_profile_report(profile_id: str):
    """Builds a personalized report from persisted user preferences."""
    try:
        from core.preferences import get_prefs
        from app.services.report_service import generate_and_save_report

        prefs = get_prefs(profile_id)
        generated = generate_and_save_report(profile_id, prefs)
        return {
            "profile_id": profile_id,
            "report": generated["report"],
            "report_id": generated["report_id"],
            "created_at": generated["created_at"],
            "files": generated["files"],
            "preferences": prefs,
        }
    except Exception as e:
        logger.error(f"GET /api/report/{profile_id} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/report/{profile_id}/structured")
async def api_profile_report_structured(profile_id: str):
    """Builds a personalized report and returns structured sections for UI consumption."""
    try:
        from core.preferences import get_prefs
        from app.services.report_service import generate_and_save_report

        prefs = get_prefs(profile_id)
        generated = generate_and_save_report(profile_id, prefs)
        payload = generated["payload"]
        return {
            "profile_id": profile_id,
            "report_id": generated["report_id"],
            "created_at": generated["created_at"],
            "preferences": prefs,
            "report_config": payload.get("report_config", {}),
            "sections": payload.get("sections", {}),
            "files": generated["files"],
        }
    except Exception as e:
        logger.error(f"GET /api/report/{profile_id}/structured failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/reports/{profile_id}")
async def api_list_reports(profile_id: str):
    """Lists saved reports for a profile."""
    try:
        from app.services.report_service import list_saved_reports
        return {"profile_id": profile_id, "reports": list_saved_reports(profile_id)}
    except Exception as e:
        logger.error(f"GET /api/reports/{profile_id} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/reports/{profile_id}/{report_id}")
async def api_get_report(profile_id: str, report_id: str):
    """Loads a saved report payload."""
    try:
        from app.services.report_service import load_saved_report
        return load_saved_report(profile_id, report_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"GET /api/reports/{profile_id}/{report_id} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/reports/{profile_id}/{report_id}/structured")
async def api_get_report_structured(profile_id: str, report_id: str):
    """Loads a saved report and returns only the structured report sections."""
    try:
        from app.services.report_service import load_saved_report

        payload = load_saved_report(profile_id, report_id)
        return {
            "profile_id": profile_id,
            "report_id": report_id,
            "created_at": payload.get("created_at"),
            "report_config": payload.get("report_config", {}),
            "sections": payload.get("sections", {}),
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"GET /api/reports/{profile_id}/{report_id}/structured failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/reports/{profile_id}/{report_id}/download")
async def api_download_report(profile_id: str, report_id: str, format: str = "md"):
    """Downloads a saved report in markdown or json format."""
    try:
        from app.services.report_service import report_file_path
        path = report_file_path(profile_id, report_id, format)
        media_type = "application/json" if format == "json" else "text/markdown"
        return FileResponse(path, media_type=media_type, filename=path.name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"GET /api/reports/{profile_id}/{report_id}/download failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
