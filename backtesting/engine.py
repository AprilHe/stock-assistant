"""Deterministic daily backtesting engine for built-in strategies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import math

import yfinance as yf

from domain.schemas.research import (
    BacktestMetrics,
    BacktestResponse,
    BacktestTrade,
    EquityPoint,
)

SUPPORTED_STRATEGIES = {
    "breakout",
    "pullback",
    "commodity_macro",
    "trend_following",
    "mean_reversion",
    "donchian_breakout",
}
_METAL_SYMBOLS = {"GC=F", "SI=F"}
_WARMUP_DAYS = 160
_OHLCV_COLUMNS = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}


@dataclass
class _Position:
    entry_date: str
    entry_price: float
    shares: float
    hold_days: int


def _pct_change(series, lookback: int, idx: int) -> float:
    if idx - lookback < 0:
        return 0.0
    start = float(series.iloc[idx - lookback])
    end = float(series.iloc[idx])
    if start == 0:
        return 0.0
    return ((end - start) / start) * 100


def _rolling_max_close(close, idx: int, lookback: int) -> float:
    start = idx - lookback
    if start < 0:
        return 0.0
    return float(close.iloc[start:idx].max())


def _rolling_min_close(close, idx: int, lookback: int) -> float:
    start = idx - lookback
    if start < 0:
        return 0.0
    return float(close.iloc[start:idx].min())


def _rsi(series, period: int = 14):
    delta = series.diff()
    gains = delta.clip(lower=0).rolling(period).mean()
    losses = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gains / losses.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def _strategy_entry_signal(
    strategy: str,
    symbol: str,
    idx: int,
    close,
    sma20,
    sma50,
    macro: dict | None,
) -> bool:
    latest_close = float(close.iloc[idx])
    sma20_now = float(sma20.iloc[idx])
    sma50_now = float(sma50.iloc[idx])

    if strategy == "breakout":
        prev_high_20 = _rolling_max_close(close, idx, 20)
        if prev_high_20 <= 0:
            return False
        return latest_close > prev_high_20 and latest_close > sma20_now and sma20_now > sma50_now

    if strategy == "pullback":
        if not (latest_close > sma50_now and sma20_now > sma50_now):
            return False
        prev_high_20 = _rolling_max_close(close, idx, 20)
        if prev_high_20 <= 0 or sma20_now <= 0:
            return False
        pullback_pct = ((latest_close - sma20_now) / sma20_now) * 100
        distance_to_high = ((prev_high_20 - latest_close) / prev_high_20) * 100
        return -3.5 <= pullback_pct <= 1.5 and 1.0 <= distance_to_high <= 8.0

    if strategy == "commodity_macro":
        if macro is None:
            return False
        ret20 = _pct_change(close, 20, idx)
        ret60 = _pct_change(close, 60, idx)
        if latest_close > sma20_now > sma50_now and ret20 > 0:
            trend_ok = True
        elif latest_close > sma50_now and ret60 > 0:
            trend_ok = True
        else:
            trend_ok = False
        if not trend_ok:
            return False
        dxy_ret20 = _pct_change(macro["dxy"], 20, idx)
        tnx_ret20 = _pct_change(macro["tnx"], 20, idx)
        spy_ret20 = _pct_change(macro["spy"], 20, idx)
        if symbol in _METAL_SYMBOLS:
            return dxy_ret20 < 0 and tnx_ret20 <= 0
        return spy_ret20 > 0 and dxy_ret20 <= 0

    if strategy == "trend_following":
        if idx < 60:
            return False
        sma50_prev = float(sma50.iloc[idx - 10])
        if sma50_prev <= 0:
            return False
        slope_ok = float(sma50.iloc[idx]) > sma50_prev
        return latest_close > sma50_now and sma20_now > sma50_now and slope_ok

    if strategy == "mean_reversion":
        if idx < 30:
            return False
        window = close.iloc[idx - 20:idx]
        mean20 = float(window.mean())
        std20 = float(window.std())
        if mean20 <= 0 or std20 <= 0:
            return False
        lower_band = mean20 - 2 * std20
        rsi14 = float(_rsi(close.iloc[: idx + 1], period=14).iloc[-1])
        return latest_close < lower_band and rsi14 < 36

    if strategy == "donchian_breakout":
        if idx < 25:
            return False
        upper_20 = _rolling_max_close(close, idx, 20)
        return upper_20 > 0 and latest_close > upper_20

    return False


def _strategy_exit_signal(strategy: str, idx: int, close, sma20, sma50) -> bool:
    latest_close = float(close.iloc[idx])
    if strategy == "breakout":
        return latest_close < float(sma20.iloc[idx])
    if strategy == "pullback":
        return latest_close < float(sma50.iloc[idx])
    if strategy == "commodity_macro":
        return latest_close < float(sma20.iloc[idx])
    if strategy == "trend_following":
        return latest_close < float(sma50.iloc[idx]) or float(sma20.iloc[idx]) < float(sma50.iloc[idx])
    if strategy == "mean_reversion":
        if idx < 20:
            return False
        mean20 = float(close.iloc[idx - 20:idx].mean())
        rsi14 = float(_rsi(close.iloc[: idx + 1], period=14).iloc[-1])
        return latest_close >= mean20 or rsi14 >= 55
    if strategy == "donchian_breakout":
        if idx < 12:
            return False
        lower_10 = _rolling_min_close(close, idx, 10)
        return lower_10 > 0 and latest_close < lower_10
    return False


def _max_drawdown_pct(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            dd = ((equity - peak) / peak) * 100
            max_dd = min(max_dd, dd)
    return round(abs(max_dd), 2)


def _sharpe_ratio(equity_curve: list[float]) -> float:
    if len(equity_curve) < 3:
        return 0.0
    daily_returns: list[float] = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]
        curr = equity_curve[i]
        if prev <= 0:
            continue
        daily_returns.append((curr - prev) / prev)
    if len(daily_returns) < 2:
        return 0.0
    mean = sum(daily_returns) / len(daily_returns)
    variance = sum((x - mean) ** 2 for x in daily_returns) / (len(daily_returns) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return round((mean / std) * math.sqrt(252), 2)


def _normalize_ohlcv_frame(df):
    if df.empty:
        return df
    if getattr(df.columns, "nlevels", 1) == 1:
        return df

    # yfinance may return a MultiIndex like (Price, Ticker) even for one symbol.
    if "Close" in df.columns.get_level_values(0):
        flattened = df.xs(df.columns.get_level_values(1)[0], axis=1, level=-1)
        return flattened

    collapsed = df.copy()
    collapsed.columns = [
        col[0] if isinstance(col, tuple) and col and col[0] in _OHLCV_COLUMNS else str(col[0] if isinstance(col, tuple) else col)
        for col in collapsed.columns
    ]
    return collapsed


def _download(symbol: str, start_date: date, end_date: date):
    warmup_start = start_date - timedelta(days=_WARMUP_DAYS)
    df = yf.download(
        symbol,
        start=warmup_start.isoformat(),
        end=(end_date + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=False,
        progress=False,
    )
    return _normalize_ohlcv_frame(df)


def _download_macro(start_date: date, end_date: date, base_index) -> dict | None:
    dxy = _download("DX-Y.NYB", start_date, end_date)
    tnx = _download("^TNX", start_date, end_date)
    spy = _download("SPY", start_date, end_date)
    if dxy.empty or tnx.empty or spy.empty:
        return None
    return {
        "dxy": dxy["Close"].reindex(base_index).ffill().bfill(),
        "tnx": tnx["Close"].reindex(base_index).ffill().bfill(),
        "spy": spy["Close"].reindex(base_index).ffill().bfill(),
    }


def run_backtest(
    ticker: str,
    strategy: str,
    start_date: date,
    end_date: date,
    initial_cash: float = 10_000.0,
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
    stop_loss_pct: float = 8.0,
    take_profit_pct: float = 15.0,
    max_holding_days: int = 20,
) -> BacktestResponse:
    normalized_strategy = strategy.lower().strip()
    symbol = ticker.upper().strip()
    if normalized_strategy not in SUPPORTED_STRATEGIES:
        raise ValueError("Invalid strategy. Choose from: breakout | pullback | commodity_macro")
    if start_date >= end_date:
        raise ValueError("start_date must be before end_date.")
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive.")
    if max_holding_days < 1:
        raise ValueError("max_holding_days must be >= 1.")

    df = _download(symbol, start_date, end_date)
    if df.empty or len(df) < 80:
        raise ValueError("Not enough historical data for this ticker/date range.")

    close = df["Close"]
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    macro = _download_macro(start_date, end_date, df.index) if normalized_strategy == "commodity_macro" else None

    fee_rate = fee_bps / 10_000.0
    slippage_rate = slippage_bps / 10_000.0

    cash = initial_cash
    position: _Position | None = None
    trades: list[BacktestTrade] = []
    equity_points: list[EquityPoint] = []
    in_market_days = 0

    for idx in range(len(df)):
        row_date = df.index[idx].date()
        if row_date < start_date or row_date > end_date:
            continue
        if math.isnan(float(sma50.iloc[idx])):
            continue

        close_px = float(close.iloc[idx])
        exit_reason = ""

        if position is not None:
            position.hold_days += 1
            in_market_days += 1
            raw_return_pct = ((close_px - position.entry_price) / position.entry_price) * 100
            if raw_return_pct <= -stop_loss_pct:
                exit_reason = "stop_loss"
            elif raw_return_pct >= take_profit_pct:
                exit_reason = "take_profit"
            elif position.hold_days >= max_holding_days:
                exit_reason = "max_hold_days"
            elif _strategy_exit_signal(normalized_strategy, idx, close, sma20, sma50):
                exit_reason = "strategy_exit"

            if exit_reason:
                exit_px = close_px * (1 - slippage_rate)
                gross = position.shares * exit_px
                fee = gross * fee_rate
                net = gross - fee
                cash += net
                pnl = net - (position.shares * position.entry_price)
                return_pct = (pnl / (position.shares * position.entry_price)) * 100
                trades.append(
                    BacktestTrade(
                        entry_date=position.entry_date,
                        exit_date=row_date.isoformat(),
                        entry_price=round(position.entry_price, 4),
                        exit_price=round(exit_px, 4),
                        shares=round(position.shares, 6),
                        pnl=round(pnl, 2),
                        return_pct=round(return_pct, 2),
                        exit_reason=exit_reason,
                    )
                )
                position = None

        if position is None and _strategy_entry_signal(
            normalized_strategy, symbol, idx, close, sma20, sma50, macro
        ):
            entry_px = close_px * (1 + slippage_rate)
            shares = cash / (entry_px * (1 + fee_rate))
            if shares > 0:
                notional = shares * entry_px
                fee = notional * fee_rate
                cash -= notional + fee
                position = _Position(
                    entry_date=row_date.isoformat(),
                    entry_price=entry_px,
                    shares=shares,
                    hold_days=0,
                )

        equity = cash + (position.shares * close_px if position else 0.0)
        equity_points.append(EquityPoint(date=row_date.isoformat(), equity=round(equity, 2)))

    if position is not None:
        last_close = float(close.loc[:end_date.isoformat()].iloc[-1])
        exit_px = last_close * (1 - slippage_rate)
        gross = position.shares * exit_px
        fee = gross * fee_rate
        net = gross - fee
        cash += net
        pnl = net - (position.shares * position.entry_price)
        return_pct = (pnl / (position.shares * position.entry_price)) * 100
        trades.append(
            BacktestTrade(
                entry_date=position.entry_date,
                exit_date=end_date.isoformat(),
                entry_price=round(position.entry_price, 4),
                exit_price=round(exit_px, 4),
                shares=round(position.shares, 6),
                pnl=round(pnl, 2),
                return_pct=round(return_pct, 2),
                exit_reason="end_of_period",
            )
        )
        if equity_points:
            equity_points[-1] = EquityPoint(date=end_date.isoformat(), equity=round(cash, 2))
        position = None

    equity_series = [point.equity for point in equity_points]
    final_equity = round(cash, 2) if position is None else round(equity_series[-1], 2)
    total_return_pct = ((final_equity - initial_cash) / initial_cash) * 100

    years = max((end_date - start_date).days / 365.25, 1 / 365.25)
    annualized_return_pct = ((final_equity / initial_cash) ** (1 / years) - 1) * 100

    wins = sum(1 for t in trades if t.pnl > 0)
    win_rate_pct = (wins / len(trades) * 100) if trades else 0.0
    exposure_pct = (in_market_days / len(equity_points) * 100) if equity_points else 0.0

    metrics = BacktestMetrics(
        initial_cash=round(initial_cash, 2),
        final_equity=round(final_equity, 2),
        total_return_pct=round(total_return_pct, 2),
        annualized_return_pct=round(annualized_return_pct, 2),
        max_drawdown_pct=_max_drawdown_pct(equity_series),
        sharpe_ratio=_sharpe_ratio(equity_series),
        win_rate_pct=round(win_rate_pct, 2),
        trades=len(trades),
        exposure_pct=round(exposure_pct, 2),
    )

    return BacktestResponse(
        ticker=symbol,
        strategy=normalized_strategy,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        parameters={
            "initial_cash": round(initial_cash, 2),
            "fee_bps": round(fee_bps, 2),
            "slippage_bps": round(slippage_bps, 2),
            "stop_loss_pct": round(stop_loss_pct, 2),
            "take_profit_pct": round(take_profit_pct, 2),
            "max_holding_days": int(max_holding_days),
        },
        metrics=metrics,
        trades=trades,
        equity_curve=equity_points,
    )
