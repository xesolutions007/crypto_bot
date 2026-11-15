"""Bybit Demo USDT perpetual-only account and order helpers.

All authenticated calls use CCXT's Demo Trading endpoint. Never route live orders.
"""
from __future__ import annotations
from typing import Optional, Callable, Any
import time
import ccxt
from exchange_manager import create_exchange

READ_RETRY_ATTEMPTS = 3
READ_RETRY_BASE_DELAY = 1.0

def _client(require_auth: bool = True):
    return create_exchange("Bybit Demo", "swap", require_auth=require_auth)

def _is_transient_connection_error(exc: Exception) -> bool:
    if isinstance(exc, (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout,
                        ccxt.DDoSProtection, ConnectionError, TimeoutError, OSError)):
        return True
    message = str(exc).lower()
    return any(marker in message for marker in (
        "winerror 10054", "connection reset", "connection aborted", "connection refused",
        "remote end closed", "read timed out", "max retries exceeded",
        "temporarily unavailable"))

def _read_with_retry(operation: Callable[[Any], Any], *, authenticated: bool = True):
    """Retry idempotent reads only, with fresh clients and bounded exponential backoff."""
    last_error = None
    for attempt in range(READ_RETRY_ATTEMPTS):
        ex = None
        try:
            ex = _client(require_auth=authenticated)
            ex.timeout = 30000
            return operation(ex)
        except Exception as exc:
            last_error = exc
            if attempt == READ_RETRY_ATTEMPTS - 1 or not _is_transient_connection_error(exc):
                raise
            time.sleep(READ_RETRY_BASE_DELAY * (2 ** attempt))
        finally:
            if ex is not None:
                try: ex.close()
                except Exception: pass
    raise last_error


def account_snapshot() -> dict:
    def read(ex):
        balance = ex.fetch_balance()
        usdt = balance.get("USDT") or {}
        return {"environment": "BYBIT_DEMO", "market_type": "swap",
                "authenticated": True, "usdt": {
                    "free": usdt.get("free"), "used": usdt.get("used"),
                    "total": usdt.get("total")}}
    return _read_with_retry(read)


def supported_symbols() -> list[str]:
    def read(ex):
        ex.load_markets()
        return sorted(s for s, m in ex.markets.items()
                      if m.get("swap") and m.get("linear") and m.get("settle") == "USDT"
                      and m.get("active", True))
    return _read_with_retry(read, authenticated=False)


def positions() -> list[dict]:
    def read(ex):
        ex.load_markets()
        result = []
        for p in ex.fetch_positions():
            contracts = float(p.get("contracts") or 0)
            if contracts <= 0:
                continue
            info = p.get("info") or {}
            def first_value(*values):
                return next((value for value in values if value not in (None, "")), None)
            result.append({
                "id": str(info.get("positionIdx", p.get("id") or "")),
                "symbol": p.get("symbol"), "side": (p.get("side") or "").upper(),
                "contracts": contracts, "entry_price": p.get("entryPrice"),
                "mark_price": p.get("markPrice"), "unrealized_pnl": p.get("unrealizedPnl"),
                "leverage": first_value(p.get("leverage"), info.get("leverage")),
                "position_margin": first_value(p.get("initialMargin"), p.get("initialMarginValue"),
                                               info.get("positionIM"), info.get("positionBalance")),
                "maintenance_margin": first_value(p.get("maintenanceMargin"), info.get("positionMM")),
                "liquidation_price": first_value(p.get("liquidationPrice"), info.get("liqPrice")),
                "margin_mode": first_value(p.get("marginMode"), info.get("tradeMode")),
                "stop_loss": first_value(p.get("stopLoss"), info.get("stopLoss")),
                "take_profit": first_value(p.get("takeProfit"), info.get("takeProfit")),
                "position_idx": int(info.get("positionIdx") or 0),
                "exchange": "Bybit Demo", "mode": "BYBIT_DEMO"})
        return result
    return _read_with_retry(read)


def open_orders(limit: int = 100) -> list[dict]:
    return _read_with_retry(lambda ex: ex.fetch_open_orders(None, limit=limit))


def recent_trades(limit: int = 50) -> list[dict]:
    return _read_with_retry(lambda ex: ex.fetch_my_trades(None, limit=limit))


def place_order(*, symbol: str, side: str, order_type: str, notional: float,
                leverage: int = 7, price: Optional[float] = None,
                trigger_price: Optional[float] = None, stop_loss: Optional[float] = None,
                take_profit: Optional[float] = None, position_side: str) -> dict:
    if notional <= 0:
        raise ValueError("Order size must be greater than zero USDT notional.")
    side, order_type = side.lower(), order_type.lower().replace("_", "-")
    if side not in {"buy", "sell"}:
        raise ValueError("Side must be buy or sell.")
    if position_side not in {"LONG", "SHORT"}:
        raise ValueError("Select LONG or SHORT position side.")
    if order_type not in {"market", "limit", "stop-limit"}:
        raise ValueError("Order type must be Market, Limit or Stop-Limit.")
    if not 1 <= int(leverage) <= 7:
        raise ValueError("Futures leverage is capped at 7x.")
    if order_type in {"limit", "stop-limit"} and (price is None or price <= 0):
        raise ValueError("A positive limit price is required.")
    if order_type == "stop-limit" and (trigger_price is None or trigger_price <= 0):
        raise ValueError("A positive trigger price is required for Stop-Limit.")
    ex = _client()
    try:
        ex.load_markets()
        market = ex.market(symbol)
        if not (market.get("swap") and market.get("linear") and market.get("settle") == "USDT"):
            raise ValueError("Only Bybit USDT-settled linear perpetual Futures are supported.")
        ticker = ex.fetch_ticker(symbol)
        ref_price = float(price or ticker.get("last") or 0)
        if ref_price <= 0:
            raise ValueError("Could not determine a valid reference price.")
        contract_size = float(market.get("contractSize") or 1)
        amount = float(ex.amount_to_precision(symbol, notional / ref_price / contract_size))
        if amount <= 0:
            raise ValueError("Order quantity rounds to zero at exchange precision.")
        # Require Hedge Mode; positionIdx 1 = Buy/Long, 2 = Sell/Short.
        try:
            ex.set_position_mode(True, symbol)
        except Exception as mode_exc:
            message = str(mode_exc).lower()
            if "110025" not in message and "not modified" not in message:
                raise RuntimeError("Could not enable/confirm Bybit Hedge Mode. Enable Hedge Mode in Bybit Demo settings, ensure no conflicting positions/orders, then retry. " + str(mode_exc)[:140])
        ex.set_leverage(int(leverage), symbol)
        position_idx = 1 if position_side == "LONG" else 2
        expected_side = "buy" if position_side == "LONG" else "sell"
        if side != expected_side:
            raise ValueError(f"{position_side} positions must be opened with {expected_side.upper()} orders.")
        params = {"positionIdx": position_idx}
        if stop_loss is not None:
            params.update({"stopLoss": ex.price_to_precision(symbol, stop_loss),
                           "slTriggerBy": "MarkPrice"})
        if take_profit is not None:
            params.update({"takeProfit": ex.price_to_precision(symbol, take_profit),
                           "tpTriggerBy": "MarkPrice"})
        if order_type == "market":
            order = ex.create_order(symbol, "market", side, amount, None, params)
        elif order_type == "limit":
            order = ex.create_order(symbol, "limit", side, amount, price, params)
        else:
            # Trigger direction is relative to mark price: upward trigger=1, downward=2.
            direction = 1 if float(trigger_price) > float(ticker.get("last") or ref_price) else 2
            params.update({"triggerPrice": ex.price_to_precision(symbol, trigger_price),
                           "triggerDirection": direction, "triggerBy": "MarkPrice"})
            order = ex.create_order(symbol, "limit", side, amount, price, params)
        if not order or not order.get("id"):
            raise RuntimeError("Bybit Demo did not return an order ID.")
        return {"environment": "BYBIT_DEMO", "market_type": "swap",
                "order_id": str(order["id"]), "client_order_id": order.get("clientOrderId"),
                "symbol": symbol, "side": side.upper(), "position_side": position_side,
                "type": order_type.upper(), "status": order.get("status") or "submitted",
                "amount": amount, "price": order.get("price"), "average": order.get("average"),
                "leverage": int(leverage), "position_idx": position_idx}
    finally:
        ex.close()


def close_position(symbol: str, side: str, contracts: float, position_idx: int) -> dict:
    if contracts <= 0:
        raise ValueError("Position size must be positive.")
    if (side.upper(), int(position_idx)) not in {("LONG", 1), ("SHORT", 2)}:
        raise ValueError("Position side and Hedge Mode index do not match.")
    ex = _client()
    try:
        amount = float(ex.amount_to_precision(symbol, contracts))
        close_side = "sell" if side.upper() == "LONG" else "buy"
        order = ex.create_order(symbol, "market", close_side, amount, None,
                                {"reduceOnly": True, "positionIdx": int(position_idx)})
        return {"environment": "BYBIT_DEMO", "order_id": str(order.get("id")),
                "status": order.get("status") or "submitted", "symbol": symbol}
    finally:
        ex.close()
