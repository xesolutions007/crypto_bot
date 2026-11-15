"""Bybit Demo-only execution and account data helpers.

This module never creates a live Bybit client. Credentials are read locally from .env.
"""
from __future__ import annotations
from typing import Optional
from exchange_manager import create_exchange


def _client(market_type: str):
    if market_type not in {"spot", "swap"}:
        raise ValueError("Market must be spot or swap.")
    return create_exchange("Bybit Demo", market_type, require_auth=True)


def account_snapshot(market_type: str = "swap") -> dict:
    ex = _client(market_type)
    try:
        balance = ex.fetch_balance()
        usdt = balance.get("USDT") or {}
        return {
            "environment": "BYBIT_DEMO",
            "market_type": market_type,
            "authenticated": True,
            "usdt": {"free": usdt.get("free"), "used": usdt.get("used"),
                     "total": usdt.get("total")},
        }
    finally:
        ex.close()


def positions() -> list[dict]:
    ex = _client("swap")
    try:
        ex.load_markets()
        rows = ex.fetch_positions()
        result = []
        for p in rows:
            contracts = float(p.get("contracts") or 0)
            if contracts <= 0:
                continue
            info = p.get("info") or {}
            result.append({
                "id": str(info.get("positionIdx", p.get("id") or "")),
                "symbol": p.get("symbol"), "side": (p.get("side") or "").upper(),
                "contracts": contracts, "entry_price": p.get("entryPrice"),
                "mark_price": p.get("markPrice"), "unrealized_pnl": p.get("unrealizedPnl"),
                "leverage": p.get("leverage"), "stop_loss": p.get("stopLoss"),
                "take_profit": p.get("takeProfit"), "position_idx": int(info.get("positionIdx") or 0),
                "exchange": "Bybit Demo", "mode": "BYBIT_DEMO",
            })
        return result
    finally:
        ex.close()


def open_orders(market_type: str = "swap") -> list[dict]:
    ex = _client(market_type)
    try:
        return ex.fetch_open_orders()
    finally:
        ex.close()


def recent_trades(market_type: str = "swap", limit: int = 50) -> list[dict]:
    ex = _client(market_type)
    try:
        return ex.fetch_my_trades(None, limit=limit)
    finally:
        ex.close()


def place_order(*, market_type: str, symbol: str, side: str, order_type: str,
                notional: float, leverage: int = 7, price: Optional[float] = None,
                trigger_price: Optional[float] = None, stop_loss: Optional[float] = None,
                take_profit: Optional[float] = None, position_side: Optional[str] = None) -> dict:
    if notional <= 0:
        raise ValueError("Order size must be greater than zero.")
    side = side.lower()
    order_type = order_type.lower().replace("_", "-")
    if side not in {"buy", "sell"}:
        raise ValueError("Side must be buy or sell.")
    if order_type not in {"market", "limit", "stop-limit"}:
        raise ValueError("Order type must be Market, Limit or Stop-Limit.")
    if market_type == "spot" and position_side:
        raise ValueError("Long/Short position mode applies to Futures, not Spot.")
    if order_type in {"limit", "stop-limit"} and (price is None or price <= 0):
        raise ValueError("A positive limit price is required.")
    if order_type == "stop-limit" and (trigger_price is None or trigger_price <= 0):
        raise ValueError("A positive trigger price is required for Stop-Limit.")
    ex = _client(market_type)
    try:
        ex.load_markets()
        market = ex.market(symbol)
        if market_type == "swap" and (not market.get("swap") or market.get("settle") != "USDT"):
            raise ValueError("Only USDT-settled linear perpetual contracts are supported.")
        if market_type == "spot" and not market.get("spot"):
            raise ValueError("Selected symbol is not a Spot market.")
        ticker = ex.fetch_ticker(symbol)
        ref_price = float(price or ticker.get("last") or 0)
        if ref_price <= 0:
            raise ValueError("Could not determine a valid reference price.")
        contract_size = float(market.get("contractSize") or 1)
        amount = float(ex.amount_to_precision(symbol, notional / ref_price / contract_size))
        if amount <= 0:
            raise ValueError("Order quantity rounds to zero at exchange precision.")
        params = {}
        if market_type == "swap":
            if not 1 <= int(leverage) <= 7:
                raise ValueError("Futures leverage is capped at 7x.")
            ex.set_leverage(int(leverage), symbol)
            # Bybit Hedge Mode: 1 = Buy/Long, 2 = Sell/Short. One-way is 0.
            if position_side:
                ps = position_side.upper()
                if ps not in {"LONG", "SHORT"}:
                    raise ValueError("Position side must be LONG or SHORT.")
                params["positionIdx"] = 1 if ps == "LONG" else 2
            else:
                params["positionIdx"] = 0
            if stop_loss is not None:
                params["stopLoss"] = ex.price_to_precision(symbol, stop_loss)
                params["slTriggerBy"] = "MarkPrice"
            if take_profit is not None:
                params["takeProfit"] = ex.price_to_precision(symbol, take_profit)
                params["tpTriggerBy"] = "MarkPrice"
        if order_type == "market":
            order = ex.create_order(symbol, "market", side, amount, None, params)
        elif order_type == "limit":
            order = ex.create_order(symbol, "limit", side, amount, price, params)
        else:
            params.update({"triggerPrice": ex.price_to_precision(symbol, trigger_price),
                           "triggerDirection": 1 if side == "buy" else 2,
                           "triggerBy": "MarkPrice"})
            order = ex.create_order(symbol, "limit", side, amount, price, params)
        if not order or not order.get("id"):
            raise RuntimeError("Bybit Demo did not return an order ID.")
        return {"environment": "BYBIT_DEMO", "market_type": market_type,
                "order_id": str(order["id"]), "client_order_id": order.get("clientOrderId"),
                "symbol": symbol, "side": side.upper(), "type": order_type.upper(),
                "status": order.get("status") or "submitted", "amount": amount,
                "price": order.get("price"), "average": order.get("average"),
                "leverage": int(leverage) if market_type == "swap" else None}
    finally:
        ex.close()


def close_position(symbol: str, side: str, contracts: float, position_idx: int) -> dict:
    if contracts <= 0:
        raise ValueError("Position size must be positive.")
    ex = _client("swap")
    try:
        close_side = "sell" if side.upper() == "LONG" else "buy"
        amount = float(ex.amount_to_precision(symbol, contracts))
        order = ex.create_order(symbol, "market", close_side, amount, None,
                                {"reduceOnly": True, "positionIdx": int(position_idx)})
        return {"environment": "BYBIT_DEMO", "order_id": str(order.get("id")),
                "status": order.get("status") or "submitted", "symbol": symbol}
    finally:
        ex.close()
