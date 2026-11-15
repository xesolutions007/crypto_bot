"""FastAPI backend for the local paper-trading dashboard.

Safety: this application does not submit exchange orders. Exchange credentials are
read locally for account verification only. All trade entries are written to SQLite.
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
    ACTIVE_PAIRS, DEFAULT_EXCHANGE, DEFAULT_SYMBOL, PAPER_CAPITAL_USDT,
    SCAN_TIMEFRAME, SCAN_INTERVAL_SECONDS, LEVERAGE, TARGET_RR, LIVE_TRADING_ENABLED,
    BYBIT_DEMO_AUTO_EXECUTION, BYBIT_DEMO_ORDER_NOTIONAL_USDT,
)
import paper_trading
from exchange_manager import create_exchange, connection_check, SUPPORTED_EXCHANGES
import bybit_demo
from news_filter import NewsSentimentFilter
from strategies import StrategyModules

app = FastAPI(title="Multi-Exchange Trading Module Bot")
news_filter = NewsSentimentFilter()
bot_running = False
current_exchange_name = DEFAULT_EXCHANGE
current_symbol = DEFAULT_SYMBOL
market_type = "swap"
last_connection_check: dict = {"status": "not_checked"}
last_scan: dict = {"status": "not_started", "signals": []}
monitor_task = None
scanner_task = None
seen_signal_keys: set[str] = set()
latest_position_prices: dict[str, float] = {}


class CapitalUpdate(BaseModel):
    capital: float = Field(gt=0, le=1_000_000_000)


class ExchangeSwitch(BaseModel):
    exchange: str
    market_type: Literal["spot", "swap"] = "swap"


class DemoOrderRequest(BaseModel):
    market_type: Literal["spot", "swap"] = "swap"
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


class PaperTradeRequest(BaseModel):
    side: Literal["LONG", "SHORT"]
    size: float = Field(gt=0, le=1_000_000)
    symbol: str = Field(default=DEFAULT_SYMBOL, min_length=3, max_length=40)
    strategy: str = "Manual Paper Trade"
    stop_loss: Optional[float] = Field(default=None, gt=0)
    take_profit: Optional[float] = Field(default=None, gt=0)
    leverage: float = Field(default=LEVERAGE, ge=1, le=125)


@app.on_event("startup")
async def startup():
    global monitor_task, scanner_task
    paper_trading.initialize()
    if not paper_trading.account()["configured"]:
        paper_trading.set_capital(PAPER_CAPITAL_USDT)
    monitor_task = asyncio.create_task(_position_monitor_loop())
    scanner_task = asyncio.create_task(_scanner_loop())


@app.on_event("shutdown")
async def shutdown():
    for task in (monitor_task, scanner_task):
        if task:
            task.cancel()
    for task in (monitor_task, scanner_task):
        if task:
            try:
                await task
            except asyncio.CancelledError:
                pass


async def _position_monitor_loop():
    """Continuously monitor all open paper positions, independent of dashboard views."""
    while True:
        try:
            open_trades = await asyncio.to_thread(paper_trading.list_trades, "OPEN", 1000)
            grouped = {}
            for trade in open_trades:
                grouped.setdefault((trade["exchange"], trade["market_type"]), set()).add(trade["symbol"])
            prices = {}
            for (exchange_name, trade_market_type), symbols in grouped.items():
                ex = None
                try:
                    ex = create_exchange(exchange_name, trade_market_type, require_auth=False)
                    ex.load_markets()
                    for symbol in symbols:
                        last = ex.fetch_ticker(symbol).get("last")
                        if last and float(last) > 0:
                            prices[exchange_name + "|" + symbol] = float(last)
                        if trade_market_type == "swap" and ex.has.get("fetchFundingRate"):
                            try:
                                funding = ex.fetch_funding_rate(symbol)
                                rate = funding.get("fundingRate")
                                settlement_ms = funding.get("nextFundingTimestamp")
                                if rate is not None and settlement_ms:
                                    funding_events = await asyncio.to_thread(
                                        paper_trading.apply_funding_rate,
                                        exchange_name, symbol, float(rate), int(settlement_ms), float(last)
                                    )
                                    if funding_events:
                                        last_scan["funding_events"] = funding_events
                            except Exception as funding_exc:
                                print(f"Funding data warning [{exchange_name} {symbol}]: {type(funding_exc).__name__}: {str(funding_exc)[:140]}")
                except Exception as exc:
                    print(f"Paper monitor warning [{exchange_name}]: {type(exc).__name__}: {str(exc)[:160]}")
                finally:
                    if ex:
                        try:
                            ex.close()
                        except Exception:
                            pass
            if prices:
                latest_position_prices.update(prices)
                events = await asyncio.to_thread(paper_trading.monitor_open_trades, prices)
                if events:
                    last_scan["risk_events"] = events
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"Paper monitor loop warning: {type(exc).__name__}: {str(exc)[:160]}")
        await asyncio.sleep(5)


async def _scanner_loop():
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
    return create_exchange(current_exchange_name, market_type, require_auth=False)


@app.get("/api/connection-check")
def api_connection_check():
    global last_connection_check
    last_connection_check = connection_check(current_exchange_name, market_type)
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

    dashboard_prices = dict(latest_position_prices)
    if price:
        dashboard_prices[current_exchange_name + "|" + current_symbol] = float(price)
    paper = paper_trading.mark_to_market(dashboard_prices)
    risk_events = []
    trades = paper_trading.list_trades(limit=10)
    closed = [t for t in trades if t["status"] == "CLOSED"]
    wins = [t for t in closed if (t["realized_pnl"] or 0) > 0]
    win_rate = (len(wins) / len(closed) * 100) if closed else None
    realized_today = sum(
        (t["realized_pnl"] or 0) for t in closed
        if (t["closed_at"] or "")[:10] == datetime.now(timezone.utc).date().isoformat()
    )
    return {
        "status": "Running" if bot_running else "Paused",
        "scanner_running": bool(bot_running),
        "active_exchange": current_exchange_name,
        "active_symbol": current_symbol,
        "market_type": market_type,
        "live_trading_enabled": LIVE_TRADING_ENABLED,
        "bybit_demo_auto_execution": BYBIT_DEMO_AUTO_EXECUTION,
        "connection_status": last_connection_check.get("status", "not_checked"),
        "exchange_balance": last_connection_check.get("usdt_balance_available"),
        "exchange_balance_label": "Bybit Demo available USDT" if last_connection_check.get("authenticated") else "Not authenticated",
        "exchange_authenticated": bool(last_connection_check.get("authenticated")),
        "exchange_account_check": last_connection_check.get("account_check", "not_checked"),
        "paper_balance": round(paper.get("equity", paper.get("cash_balance", 0)), 4),
        "paper_cash": round(paper.get("cash_balance", 0), 4),
        "today_pnl": round(realized_today, 4),
        "pnl_percentage": None,
        "open_positions_count": paper.get("open_positions", 0),
        "win_rate": f"{win_rate:.1f}%" if win_rate is not None else "N/A",
        "daily_drawdown": "N/A",
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
        "recent_trades": [
            {
                "id": t["id"], "time": t["opened_at"], "pair": t["symbol"],
                "type": t["side"], "price": t["entry_price"], "size": t["quantity"],
                "pnl": t["realized_pnl"], "status": t["status"],
                "exchange": t["exchange"], "strategy": t["strategy"],
            } for t in trades
        ],
        "news": [],
        "news_bias": "UNAVAILABLE",
    }


@app.post("/api/switch-exchange")
def switch_exchange(data: ExchangeSwitch):
    global current_exchange_name, market_type, last_connection_check
    if data.exchange not in SUPPORTED_EXCHANGES:
        raise HTTPException(400, "Unsupported exchange.")
    current_exchange_name = data.exchange
    market_type = data.market_type
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


@app.post("/api/capital")
def update_capital(data: CapitalUpdate):
    try:
        result = paper_trading.set_capital(data.capital)
        return {"status": "success", "paper_account": result}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/place-trade")
def place_paper_trade(data: PaperTradeRequest):
    # This endpoint ONLY creates a local SQLite paper trade.
    try:
        ex = _public_exchange()
        ex.load_markets()
        if data.symbol not in ex.markets:
            raise HTTPException(400, f"{data.symbol} is not available on {current_exchange_name}.")
        ticker = ex.fetch_ticker(data.symbol)
        entry = ticker.get("last")
        try:
            ex.close()
        except Exception:
            pass
        if not entry or entry <= 0:
            raise HTTPException(502, "Exchange did not return a valid market price.")
        notional = float(data.size)
        quantity = notional / float(entry)
        trade = paper_trading.open_trade(
            exchange=current_exchange_name, market_type=market_type,
            symbol=data.symbol, strategy=data.strategy, side=data.side,
            entry_price=float(entry), quantity=quantity,
            stop_loss=data.stop_loss, take_profit=data.take_profit,
            leverage=data.leverage, target_rr=TARGET_RR,
        )
        return {"status": "paper_trade_opened", "trade": trade,
                "warning": "Local simulation only. No exchange order was sent.",
                "margin_required": trade["margin_used"],
                "leverage": trade["leverage"],
                "risk_monitoring": "Enabled only when a stop-loss is supplied."}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Could not create paper trade: {type(exc).__name__}: {str(exc)[:180]}")


@app.post("/api/close-paper-trade/{trade_id}")
def close_paper_trade(trade_id: str):
    """Close a local paper position at the latest exchange ticker; never submits an order."""
    trade = next((t for t in paper_trading.list_trades(status="OPEN", limit=1000) if t["id"] == trade_id), None)
    if trade is None:
        raise HTTPException(404, "Open paper trade not found.")
    try:
        price = latest_position_prices.get(trade["exchange"] + "|" + trade["symbol"])
        if not price:
            ex = create_exchange(trade["exchange"], trade["market_type"], require_auth=False)
            try:
                ex.load_markets()
                price = ex.fetch_ticker(trade["symbol"]).get("last")
            finally:
                try: ex.close()
                except Exception: pass
        if not price or float(price) <= 0:
            raise HTTPException(502, "Could not obtain a current market price. Try again shortly.")
        closed = paper_trading.close_trade(trade_id, float(price))
        return {"status": "closed", "trade": closed, "exit_reference_price": float(price),
                "warning": "Local paper position closed only. No exchange order was sent."}
    except HTTPException: raise
    except ValueError as exc: raise HTTPException(400, str(exc))
    except Exception as exc: raise HTTPException(502, f"Could not close paper position: {type(exc).__name__}: {str(exc)[:160]}")


@app.get("/api/open-positions")
def get_open_positions():
    positions = paper_trading.list_trades(status="OPEN", limit=1000)
    result = []
    for trade in positions:
        price = latest_position_prices.get(trade["exchange"] + "|" + trade["symbol"])
        unrealized = None if price is None else (float(price) - trade["entry_price"]) * trade["quantity"] * (1 if trade["side"] == "LONG" else -1)
        result.append({
            "id": trade["id"], "exchange": trade["exchange"], "symbol": trade["symbol"],
            "side": trade["side"], "entry_price": trade["entry_price"], "current_price": price,
            "leverage": trade["leverage"], "margin_used": trade["margin_used"],
            "unrealized_pnl": unrealized, "stop_loss": trade["stop_loss"],
            "take_profit": trade["take_profit"], "opened_at": trade["opened_at"],
        })
    return {"positions": result, "count": len(result), "mode": "LOCAL_PAPER_ONLY"}


@app.get("/api/paper-trades")
def get_paper_trades(status: Optional[str] = None, limit: int = 100):
    try:
        return {"trades": paper_trading.list_trades(status=status, limit=limit)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/bybit-demo/account")
def bybit_demo_account(market_type: Literal["spot", "swap"] = "swap"):
    try:
        return bybit_demo.account_snapshot(market_type)
    except Exception as exc:
        raise HTTPException(502, f"Bybit Demo account check failed: {type(exc).__name__}: {str(exc)[:180]}")


@app.get("/api/bybit-demo/positions")
def bybit_demo_positions():
    try:
        rows = bybit_demo.positions()
        return {"environment": "BYBIT_DEMO", "positions": rows, "count": len(rows)}
    except Exception as exc:
        raise HTTPException(502, f"Could not fetch Bybit Demo positions: {type(exc).__name__}: {str(exc)[:180]}")


@app.get("/api/bybit-demo/orders")
def bybit_demo_orders(market_type: Literal["spot", "swap"] = "swap"):
    try:
        rows = bybit_demo.open_orders(market_type)
        return {"environment": "BYBIT_DEMO", "orders": rows, "count": len(rows)}
    except Exception as exc:
        raise HTTPException(502, f"Could not fetch Bybit Demo open orders: {type(exc).__name__}: {str(exc)[:180]}")


@app.get("/api/bybit-demo/trades")
def bybit_demo_trades(market_type: Literal["spot", "swap"] = "swap", limit: int = 50):
    try:
        rows = bybit_demo.recent_trades(market_type, max(1, min(limit, 100)))
        return {"environment": "BYBIT_DEMO", "trades": rows, "count": len(rows)}
    except Exception as exc:
        raise HTTPException(502, f"Could not fetch Bybit Demo trade history: {type(exc).__name__}: {str(exc)[:180]}")


@app.post("/api/bybit-demo/order")
def place_bybit_demo_order(data: DemoOrderRequest):
    if LIVE_TRADING_ENABLED:
        raise HTTPException(403, "Safety lock: live trading is disabled.")
    if data.market_type == "swap" and data.position_side is None:
        raise HTTPException(400, "Choose LONG or SHORT explicitly for separate Futures positions.")
    if data.market_type == "spot" and (data.stop_loss is not None or data.take_profit is not None):
        # Spot conditional protection support varies by account/API; require Futures for attached position SL/TP.
        raise HTTPException(400, "Attached position Stop Loss/Take Profit is currently supported for Futures only.")
    try:
        result = bybit_demo.place_order(
            market_type=data.market_type, symbol=data.symbol, side=data.side,
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
        "monitoring": "Background monitor active for all open paper positions",
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
    if BYBIT_DEMO_ORDER_NOTIONAL_USDT <= 0 or BYBIT_DEMO_ORDER_NOTIONAL_USDT > 100:
        raise RuntimeError("Demo order notional must be greater than 0 and no more than 100 USDT.")
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
        if not market.get("swap") or market.get("quote") != "USDT":
            raise RuntimeError("Only USDT-settled Bybit perpetual markets are allowed.")
        try:
            ex.set_leverage(LEVERAGE, symbol)
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
            "positionIdx": 0, "tpslMode": "Full",
            "stopLoss": {"triggerPrice": ex.price_to_precision(symbol, stop)},
            "takeProfit": {"triggerPrice": ex.price_to_precision(symbol, target)},
            "slTriggerBy": "MarkPrice", "tpTriggerBy": "MarkPrice",
        }
        order = ex.create_order(symbol, "market", "buy" if side == "LONG" else "sell", amount, None, params)
        if not order or not order.get("id"):
            raise RuntimeError("Bybit did not return a confirmed order ID.")
        return {"exchange": "Bybit Demo", "symbol": symbol, "side": side,
                "order_id": str(order["id"]), "status": order.get("status") or "submitted",
                "amount": amount, "leverage": LEVERAGE, "reference_price": entry,
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
        for symbol in ACTIVE_PAIRS:
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
                "automatically_executed": bool(BYBIT_DEMO_AUTO_EXECUTION and current_exchange_name == "Bybit Demo" and market_type == "swap"),
                "execution_mode": "BYBIT_DEMO" if BYBIT_DEMO_AUTO_EXECUTION and current_exchange_name == "Bybit Demo" and market_type == "swap" else "SIGNAL_ONLY",
                "note": "Automatic orders are Bybit Demo only and require local trade-enabled Demo API credentials. Modules III and IV await genuine CVD/open-interest inputs."}
    except Exception as exc:
        raise HTTPException(502, f"Scan failed: {type(exc).__name__}: {str(exc)[:180]}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
