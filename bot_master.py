"""FastAPI backend for Bybit Demo USDT perpetual Futures only.

Live trading is hard-disabled in config.py. Exchange credentials remain local.
"""
from __future__ import annotations

from datetime import datetime, timezone
import asyncio
from pathlib import Path
from typing import Literal, Optional

import ccxt
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from config import (
    ACTIVE_PAIRS, DEFAULT_EXCHANGE, DEFAULT_SYMBOL,
    SCAN_TIMEFRAME, SCAN_INTERVAL_SECONDS, LEVERAGE, TARGET_RR, LIVE_TRADING_ENABLED,
    BYBIT_DEMO_AUTO_EXECUTION, BYBIT_DEMO_ORDER_NOTIONAL_USDT, BYBIT_DEMO_TOTAL_BUDGET_USDT,
)
from exchange_manager import create_exchange, connection_check
import bybit_demo
from news_filter import NewsSentimentFilter
from strategies import StrategyModules

app = FastAPI(title="Bybit Demo Futures Bot")
news_filter = NewsSentimentFilter()
bot_running = False
current_exchange_name = "Bybit Demo"
current_symbol = DEFAULT_SYMBOL
market_type = "swap"
last_connection_check: dict = {"status": "not_checked"}
last_scan: dict = {"status": "not_started", "signals": []}
monitor_task = None
scanner_task = None
seen_signal_keys: set[str] = set()
latest_position_prices: dict[str, float] = {}


(BaseModel):
    exchange: str
    market_type: Literal["spot", "swap"] = "swap"


class DemoOrderRequest(BaseModel):
    symbol: str = Field(min_length=3, max_length=40)
    side: Literal["BUY", "SELL"]
    order_type: Literal["market", "limit", "stop-limit"] = "market"
    size_usdt: float = Field(gt=0, le=100000)
    leverage: int = Field(default=7, ge=1, le=7)
    price: Optional[float] = Field(default=None, gt=0)
    trigger_price: Optional[float] = Field(default=None, gt=0)
    stop_loss: Optional[float] = Field(default=None, gt=0)
    take_profit: Optional[float] = Field(default=None, gt=0)
    position_side: Optional[Literal["LONG", "SHORT"]] = None


class DemoCloseRequest(BaseModel):
    symbol: str
    side: Literal["LONG", "SHORT"]
    contracts: float = Field(gt=0)
    position_idx: int = Field(ge=0, le=2)



async def startup():
    global scanner_task
    scanner_task = asyncio.create_task(_scanner_loop())


@app.on_event("shutdown")
async def shutdown():
    for task in (scanner_task,):
        if task:
            task.cancel()
    for task in (monitor_task, scanner_task):
        if task:
            try:
                await task
            except asyncio.CancelledError:
                pass



    global last_scan
    while True:
        try:
            if bot_running:
                last_scan = await asyncio.to_thread(scan_once)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_scan = {"status": "error", "signals": [], "errors": [
                {"error": f"{type(exc).__name__}: {str(exc)[:180]}"}
            ]}
        await asyncio.sleep(max(10, SCAN_INTERVAL_SECONDS))


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    path = Path(__file__).with_name("index.html")
    return path.read_text(encoding="utf-8")


def _public_exchange():
    # Public market data can be fetched without API credentials.
    return create_exchange("Bybit Demo", "swap", require_auth=False)


@app.get("/api/connection-check")
def api_connection_check():
    global last_connection_check
    last_connection_check = connection_check("Bybit Demo", "swap")
    return last_connection_check


@app.get("/api/dashboard-data")
def get_dashboard_data():
    price = None
    price_change = None
    market_error = None
    try:
        ex = _public_exchange()
        ex.load_markets()
        ticker = ex.fetch_ticker(current_symbol)
        price = ticker.get("last")
        price_change = ticker.get("percentage")
        try:
            ex.close()
        except Exception:
            pass
    except Exception as exc:
        market_error = f"{type(exc).__name__}: {str(exc)[:180]}"

    return {
        "status": "Running" if bot_running else "Paused",
        "scanner_running": bool(bot_running),
        "active_exchange": "Bybit Demo",
        "active_symbol": current_symbol,
        "market_type": "swap",
        "live_trading_enabled": LIVE_TRADING_ENABLED,
        "bybit_demo_auto_execution": BYBIT_DEMO_AUTO_EXECUTION,
        "connection_status": last_connection_check.get("status", "not_checked"),
        "exchange_balance": last_connection_check.get("usdt_balance_available"),
        "exchange_balance_label": "Bybit Demo available USDT" if last_connection_check.get("authenticated") else "Not authenticated",
        "exchange_authenticated": bool(last_connection_check.get("authenticated")),
        "exchange_account_check": last_connection_check.get("account_check", "not_checked"),
        "current_price": price,
        "price_change": price_change,
        "market_data_error": market_error,
        "risk_events": risk_events + last_scan.get("risk_events", []),
        "funding_events": last_scan.get("funding_events", []),
        "last_scan": last_scan,
        "market_intelligence": {
            "open_interest": None,
            "open_interest_change": None,
            "cvd_spot": None,
            "status": "Provider not configured",
        },
        "news": [],
        "news_bias": "UNAVAILABLE",
    }


@app.post("/api/switch-exchange")
def switch_exchange(data: ExchangeSwitch):
    global current_exchange_name, market_type, last_connection_check
    if data.exchange != "Bybit Demo" or data.market_type != "swap":
        raise HTTPException(400, "Only Bybit Demo USDT perpetual Futures are supported.")
    current_exchange_name = "Bybit Demo"
    market_type = "swap"
    last_connection_check = {"status": "not_checked"}
    return {"status": "selected", "active_exchange": current_exchange_name,
            "market_type": market_type, "note": "Run connection check to verify access."}


@app.post("/api/switch-symbol")
def switch_symbol(data: dict):
    global current_symbol
    symbol = str(data.get("symbol", "")).strip()
    if not symbol or len(symbol) > 40:
        raise HTTPException(400, "A valid symbol is required.")
    current_symbol = symbol
    return {"status": "selected", "symbol": current_symbol}


@app.post("/api/toggle")
def toggle_bot():
    global bot_running
    bot_running = not bot_running
    return {
        "status": "success",
        "bot_running": bot_running,
        "automated_execution": bool(
            bot_running and BYBIT_DEMO_AUTO_EXECUTION
            and current_exchange_name == "Bybit Demo" and market_type == "swap"
            and not LIVE_TRADING_ENABLED
        ),
        "note": (
            "Scanner is running. Eligible Strategy I/II signals may submit protected "
            "orders to Bybit Demo when Demo auto-execution is enabled. Live trading remains disabled."
            if bot_running else "Scanner is paused; no new automatic signals will be processed."
        ),
    }


@app.get("/api/open-positions")
def get_open_positions():
    try:
        positions = bybit_demo.positions()
        return {"positions": positions, "count": len(positions), "mode": "BYBIT_DEMO"}
    except Exception as exc:
        raise HTTPException(502, f"Could not load Bybit Demo positions: {type(exc).__name__}: {str(exc)[:180]}")


@app.get("/api/bybit-demo/account")
def bybit_demo_account():
    try:
        return bybit_demo.account_snapshot()
    except Exception as exc:
        raise HTTPException(502, f"Bybit Demo account check failed: {type(exc).__name__}: {str(exc)[:180]}")


@app.get("/api/bybit-demo/symbols")
def bybit_demo_symbols():
    try:
        rows = bybit_demo.supported_symbols()
        return {"environment": "BYBIT_DEMO", "market_type": "swap", "symbols": rows, "count": len(rows)}
    except Exception as exc:
        raise HTTPException(502, f"Could not load Bybit USDT perpetual symbols: {type(exc).__name__}: {str(exc)[:180]}")


@app.get("/api/bybit-demo/positions")
def bybit_demo_positions():
    try:
        rows = bybit_demo.positions()
        return {"environment": "BYBIT_DEMO", "positions": rows, "count": len(rows)}
    except Exception as exc:
        raise HTTPException(502, f"Could not fetch Bybit Demo positions: {type(exc).__name__}: {str(exc)[:180]}")


@app.get("/api/bybit-demo/orders")
def bybit_demo_orders():
    try:
        rows = bybit_demo.open_orders()
        return {"environment": "BYBIT_DEMO", "orders": rows, "count": len(rows)}
    except Exception as exc:
        raise HTTPException(502, f"Could not fetch Bybit Demo open orders: {type(exc).__name__}: {str(exc)[:180]}")


@app.get("/api/bybit-demo/trades")
def bybit_demo_trades(limit: int = 50):
    try:
        rows = bybit_demo.recent_trades(max(1, min(limit, 100)))
        return {"environment": "BYBIT_DEMO", "trades": rows, "count": len(rows)}
    except Exception as exc:
        raise HTTPException(502, f"Could not fetch Bybit Demo trade history: {type(exc).__name__}: {str(exc)[:180]}")


@app.post("/api/bybit-demo/order")
def place_bybit_demo_order(data: DemoOrderRequest):
    if LIVE_TRADING_ENABLED:
        raise HTTPException(403, "Safety lock: live trading is disabled.")
    if data.position_side is None:
        raise HTTPException(400, "Choose LONG or SHORT explicitly for separate Futures positions.")
    try:
        result = bybit_demo.place_order(
            symbol=data.symbol, side=data.side,
            order_type=data.order_type, notional=data.size_usdt, leverage=data.leverage,
            price=data.price, trigger_price=data.trigger_price,
            stop_loss=data.stop_loss, take_profit=data.take_profit,
            position_side=data.position_side)
        return {"status": "submitted_to_bybit_demo", "order": result,
                "note": "Check order status and resulting position in Bybit Demo. Submitted does not mean filled."}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Bybit Demo order failed: {type(exc).__name__}: {str(exc)[:180]}")


@app.post("/api/bybit-demo/close-position")
def close_bybit_demo_position(data: DemoCloseRequest):
    try:
        return bybit_demo.close_position(data.symbol, data.side, data.contracts, data.position_idx)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Bybit Demo close failed: {type(exc).__name__}: {str(exc)[:180]}")


@app.get("/api/strategies")
def get_strategies():
    return {
        "modules": [
            {"name": "Strategy Module I", "description": "SMA 20/200 crossover with Stochastic 3/3 confirmation", "configured": True},
            {"name": "Strategy Module II", "description": "Marubozu candle pattern", "configured": True},
            {"name": "Strategy Module III", "description": "VWAP breakout with CVD and trend confirmation", "configured": True},
            {"name": "Strategy Module IV", "description": "B2B setup using 20-candle low and open interest", "configured": True},
        ],
        "automated_execution": bool(BYBIT_DEMO_AUTO_EXECUTION and current_exchange_name == "Bybit Demo" and market_type == "swap"),
        "scanner_running": bot_running,
        "monitoring": "Bybit Demo exchange positions and protective orders are exchange-managed",
    }


@app.get("/api/signals")
def get_latest_signals():
    return last_scan



def _execute_bybit_demo_signal(signal_row: dict) -> dict:
    """Submit a protected market order to Bybit Demo only; never route live."""
    if LIVE_TRADING_ENABLED or not BYBIT_DEMO_AUTO_EXECUTION:
        raise RuntimeError("Demo auto-execution is disabled by configuration.")
    if current_exchange_name != "Bybit Demo" or market_type != "swap":
        raise RuntimeError("Automatic execution is restricted to Bybit Demo USDT perpetuals.")
    if BYBIT_DEMO_ORDER_NOTIONAL_USDT <= 0 or BYBIT_DEMO_ORDER_NOTIONAL_USDT > 3:
        raise RuntimeError("Automatic Demo order notional must be greater than 0 and no more than 3 USDT.")
    if BYBIT_DEMO_TOTAL_BUDGET_USDT <= 0:
        raise RuntimeError("Total Demo trading budget must be greater than zero.")
    symbol = str(signal_row["symbol"])
    side = str(signal_row.get("direction", "")).upper()
    entry = float(signal_row.get("market_price") or 0)
    stop = float(signal_row.get("sl") or 0)
    if side not in {"LONG", "SHORT"} or entry <= 0 or stop <= 0:
        raise RuntimeError("Signal is missing a valid side, market price, or stop-loss.")
    if (side == "LONG" and not stop < entry) or (side == "SHORT" and not stop > entry):
        raise RuntimeError("Signal stop-loss is on the wrong side of the market; order blocked.")
    risk = abs(entry - stop)
    target = entry + (risk * TARGET_RR if side == "LONG" else -risk * TARGET_RR)
    ex = create_exchange("Bybit Demo", "swap", require_auth=True)
    try:
        ex.load_markets()
        market = ex.market(symbol)
        if not (market.get("swap") and market.get("linear") and market.get("settle") == "USDT"):
            raise RuntimeError("Only active USDT-settled linear Bybit perpetual markets are allowed.")
        used_notional = 0.0
        for position in ex.fetch_positions():
            contracts = float(position.get("contracts") or 0)
            if contracts <= 0:
                continue
            mark = float(position.get("markPrice") or position.get("entryPrice") or 0)
            position_market = ex.market(position["symbol"])
            contract_size_existing = float(position_market.get("contractSize") or 1)
            used_notional += contracts * contract_size_existing * mark
        if used_notional + BYBIT_DEMO_ORDER_NOTIONAL_USDT > BYBIT_DEMO_TOTAL_BUDGET_USDT:
            raise RuntimeError(
                f"Demo budget reached: existing position notional is about {used_notional:.2f} USDT; "
                f"the configured total cap is {BYBIT_DEMO_TOTAL_BUDGET_USDT:.2f} USDT."
            )
        # Scanner orders use the same Hedge Mode mapping as manual Demo orders.
        try:
            ex.set_position_mode(True, symbol)
        except Exception as mode_exc:
            message = str(mode_exc).lower()
            if "110025" not in message and "not modified" not in message:
                raise RuntimeError("Could not confirm Bybit Hedge Mode for scanner order: " + str(mode_exc)[:140])
        try:
            ex.set_leverage(min(7, int(LEVERAGE)), symbol)
        except Exception as leverage_exc:
            message = str(leverage_exc).lower()
            if "110043" not in message and "not modified" not in message:
                raise
        base_quantity = BYBIT_DEMO_ORDER_NOTIONAL_USDT / entry
        contract_size = float(market.get("contractSize") or 1)
        amount = float(ex.amount_to_precision(symbol, base_quantity / contract_size))
        if amount <= 0 or amount * contract_size * entry > BYBIT_DEMO_ORDER_NOTIONAL_USDT * 1.02:
            raise RuntimeError("Calculated order quantity is invalid or exceeds the configured notional cap.")
        params = {
            "positionIdx": 1 if side == "LONG" else 2, "tpslMode": "Full",
            "stopLoss": ex.price_to_precision(symbol, stop),
            "takeProfit": ex.price_to_precision(symbol, target),
            "slTriggerBy": "MarkPrice", "tpTriggerBy": "MarkPrice",
        }
        order = ex.create_order(symbol, "market", "buy" if side == "LONG" else "sell", amount, None, params)
        if not order or not order.get("id"):
            raise RuntimeError("Bybit did not return a confirmed order ID.")
        return {"exchange": "Bybit Demo", "symbol": symbol, "side": side,
                "order_id": str(order["id"]), "status": order.get("status") or "submitted",
                "amount": amount, "leverage": min(7, int(LEVERAGE)), "position_idx": params["positionIdx"], "reference_price": entry,
                "stop_loss": stop, "take_profit": target, "mode": "BYBIT_DEMO"}
    finally:
        try: ex.close()
        except Exception: pass


@app.post("/api/scan-once")
def scan_once():
    """Scan Strategies I/II; auto-submit only when explicitly enabled for Bybit Demo."""
    signals = []
    errors = []
    try:
        ex = _public_exchange()
        ex.load_markets()
        bias = news_filter.get_market_bias()
        if ACTIVE_PAIRS:
            scan_symbols = [symbol for symbol in ACTIVE_PAIRS if symbol in ex.markets]
        elif current_exchange_name == "Bybit Demo" and market_type == "swap":
            scan_symbols = sorted(
                symbol for symbol, market in ex.markets.items()
                if market.get("active", True) and market.get("swap")
                and market.get("linear") and market.get("settle") == "USDT"
            )
        else:
            scan_symbols = [current_symbol]
        for symbol in scan_symbols:
            try:
                candles = ex.fetch_ohlcv(symbol, timeframe=SCAN_TIMEFRAME, limit=250)
                if not candles:
                    errors.append({"symbol": symbol, "error": "No candle data"})
                    continue
                frame = pd.DataFrame(candles, columns=[
                    "timestamp", "open", "high", "low", "close", "volume"
                ])
                frame = frame.iloc[:-1].copy()  # ignore the still-forming candle
                if len(frame) < 202:
                    errors.append({"symbol": symbol, "error": "Not enough closed candles"})
                    continue
                ticker = ex.fetch_ticker(symbol)
                price = ticker.get("last")
                # Market intelligence is not fabricated. Modules requiring OI/CVD
                # are skipped until a real provider is configured.
                signal = StrategyModules.evaluate_module_1(frame, {}, bias)
                if not signal:
                    signal = StrategyModules.evaluate_module_2(frame, {}, bias)
                if signal:
                    signal_row = {"symbol": symbol, **signal, "market_price": price,
                                  "candle_timestamp": int(frame.iloc[-1]["timestamp"])}
                    side = str(signal.get("side", signal.get("direction", ""))).upper()
                    strategy_name = str(signal.get("strategy", signal.get("module", "unknown")))
                    key = "|".join([current_exchange_name, symbol, SCAN_TIMEFRAME,
                                    strategy_name, side, str(signal_row["candle_timestamp"])])
                    if key not in seen_signal_keys:
                        seen_signal_keys.add(key)
                        if BYBIT_DEMO_AUTO_EXECUTION and current_exchange_name == "Bybit Demo" and market_type == "swap":
                            try:
                                signal_row["demo_order"] = _execute_bybit_demo_signal(signal_row)
                                signal_row["execution_status"] = "submitted_to_bybit_demo"
                            except Exception as order_exc:
                                signal_row["execution_status"] = "blocked_or_failed"
                                signal_row["execution_error"] = f"{type(order_exc).__name__}: {str(order_exc)[:180]}"
                        else:
                            signal_row["execution_status"] = "signal_only"
                        signals.append(signal_row)
            except Exception as exc:
                errors.append({"symbol": symbol, "error": f"{type(exc).__name__}: {str(exc)[:180]}"})
        try:
            ex.close()
        except Exception:
            pass
        return {"status": "completed", "signals": signals, "errors": errors,
                "pairs_scanned": len(scan_symbols),
                "watchlist": "ALL_ACTIVE_USDT_LINEAR_PERPETUALS" if not ACTIVE_PAIRS and current_exchange_name == "Bybit Demo" and market_type == "swap" else "CUSTOM",
                "order_notional_usdt": BYBIT_DEMO_ORDER_NOTIONAL_USDT,
                "total_demo_budget_usdt": BYBIT_DEMO_TOTAL_BUDGET_USDT,
                "automatically_executed": bool(BYBIT_DEMO_AUTO_EXECUTION and current_exchange_name == "Bybit Demo" and market_type == "swap"),
                "execution_mode": "BYBIT_DEMO" if BYBIT_DEMO_AUTO_EXECUTION and current_exchange_name == "Bybit Demo" and market_type == "swap" else "SIGNAL_ONLY",
                "note": "Automatic orders are Bybit Demo only and require local trade-enabled Demo API credentials. Modules III and IV await genuine CVD/open-interest inputs."}
    except Exception as exc:
        raise HTTPException(502, f"Scan failed: {type(exc).__name__}: {str(exc)[:180]}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
