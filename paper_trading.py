"""Persistent local paper-trading ledger.

This module never sends orders to an exchange. All balances and trades stored here
are simulated locally and are deliberately separate from exchange wallet balances.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import uuid


DB_PATH = Path(__file__).with_name("paper_trading.sqlite3")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connection(db_path: Path = DB_PATH):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize(db_path: Path = DB_PATH) -> None:
    with _connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                starting_capital REAL NOT NULL,
                cash_balance REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id TEXT PRIMARY KEY,
                exchange TEXT NOT NULL,
                market_type TEXT NOT NULL,
                symbol TEXT NOT NULL,
                strategy TEXT NOT NULL,
                side TEXT NOT NULL CHECK (side IN ('LONG', 'SHORT')),
                entry_price REAL NOT NULL,
                quantity REAL NOT NULL,
                stop_loss REAL,
                take_profit REAL,
                status TEXT NOT NULL CHECK (status IN ('OPEN', 'CLOSED')),
                opened_at TEXT NOT NULL,
                closed_at TEXT,
                exit_price REAL,
                realized_pnl REAL
            )
        """)


def set_capital(amount: float, db_path: Path = DB_PATH) -> dict:
    if amount <= 0:
        raise ValueError("Paper capital must be greater than zero.")
    initialize(db_path)
    now = _now()
    with _connection(db_path) as conn:
        open_count = conn.execute(
            "SELECT COUNT(*) FROM paper_trades WHERE status='OPEN'"
        ).fetchone()[0]
        if open_count:
            raise ValueError("Close all open paper positions before resetting capital.")
        conn.execute("""
            INSERT INTO paper_account(id, starting_capital, cash_balance, created_at, updated_at)
            VALUES(1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                starting_capital=excluded.starting_capital,
                cash_balance=excluded.cash_balance,
                updated_at=excluded.updated_at
        """, (float(amount), float(amount), now, now))
    return account(db_path)


def account(db_path: Path = DB_PATH) -> dict:
    initialize(db_path)
    with _connection(db_path) as conn:
        row = conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
        if row is None:
            return {"configured": False, "starting_capital": 0.0, "cash_balance": 0.0}
        open_rows = conn.execute(
            "SELECT side, entry_price, quantity FROM paper_trades WHERE status='OPEN'"
        ).fetchall()
        unrealized = 0.0
        return {
            "configured": True,
            "starting_capital": row["starting_capital"],
            "cash_balance": row["cash_balance"],
            "open_positions": len(open_rows),
            "unrealized_pnl": unrealized,
            "updated_at": row["updated_at"],
        }


def open_trade(exchange: str, market_type: str, symbol: str, strategy: str,
               side: str, entry_price: float, quantity: float,
               stop_loss: Optional[float] = None,
               take_profit: Optional[float] = None,
               db_path: Path = DB_PATH) -> dict:
    side = side.upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("side must be LONG or SHORT")
    if entry_price <= 0 or quantity <= 0:
        raise ValueError("entry_price and quantity must be greater than zero")
    initialize(db_path)
    trade_id = str(uuid.uuid4())
    with _connection(db_path) as conn:
        acc = conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
        if acc is None:
            raise ValueError("Set paper capital before opening a trade.")
        # Reserve the simulated notional from available cash; leverage is not
        # assumed here. A later margin model must be explicitly configured.
        required = entry_price * quantity
        if required > acc["cash_balance"]:
            raise ValueError("Insufficient paper cash for this position.")
        conn.execute("""
            INSERT INTO paper_trades(
                id, exchange, market_type, symbol, strategy, side, entry_price,
                quantity, stop_loss, take_profit, status, opened_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
        """, (trade_id, exchange, market_type, symbol, strategy, side,
              float(entry_price), float(quantity), stop_loss, take_profit, _now()))
        conn.execute(
            "UPDATE paper_account SET cash_balance=cash_balance-?, updated_at=? WHERE id=1",
            (required, _now())
        )
        row = conn.execute("SELECT * FROM paper_trades WHERE id=?", (trade_id,)).fetchone()
        return dict(row)


def close_trade(trade_id: str, exit_price: float, db_path: Path = DB_PATH) -> dict:
    if exit_price <= 0:
        raise ValueError("exit_price must be greater than zero")
    initialize(db_path)
    with _connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM paper_trades WHERE id=? AND status='OPEN'", (trade_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Open paper trade not found.")
        sign = 1.0 if row["side"] == "LONG" else -1.0
        pnl = (float(exit_price) - row["entry_price"]) * row["quantity"] * sign
        released = row["entry_price"] * row["quantity"] + pnl
        conn.execute("""
            UPDATE paper_trades SET status='CLOSED', closed_at=?, exit_price=?, realized_pnl=?
            WHERE id=?
        """, (_now(), float(exit_price), pnl, trade_id))
        conn.execute(
            "UPDATE paper_account SET cash_balance=cash_balance+?, updated_at=? WHERE id=1",
            (released, _now())
        )
        updated = conn.execute("SELECT * FROM paper_trades WHERE id=?", (trade_id,)).fetchone()
        return dict(updated)


def list_trades(status: Optional[str] = None, limit: int = 100,
                db_path: Path = DB_PATH) -> list[dict]:
    initialize(db_path)
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    with _connection(db_path) as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM paper_trades WHERE status=? ORDER BY opened_at DESC LIMIT ?",
                (status.upper(), limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM paper_trades ORDER BY opened_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]


def mark_to_market(prices: dict[str, float], db_path: Path = DB_PATH) -> dict:
    """Return paper equity and unrealized P&L using supplied live ticker prices."""
    initialize(db_path)
    with _connection(db_path) as conn:
        acc = conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
        if acc is None:
            return {"configured": False, "equity": 0.0, "unrealized_pnl": 0.0}
        rows = conn.execute("SELECT * FROM paper_trades WHERE status='OPEN'").fetchall()
        unrealized = 0.0
        for row in rows:
            price = prices.get(row["symbol"])
            if price is None:
                continue
            sign = 1.0 if row["side"] == "LONG" else -1.0
            unrealized += (float(price) - row["entry_price"]) * row["quantity"] * sign
        return {
            "configured": True,
            "starting_capital": acc["starting_capital"],
            "cash_balance": acc["cash_balance"],
            "open_positions": len(rows),
            "unrealized_pnl": unrealized,
            "equity": acc["cash_balance"] + sum(
                row["entry_price"] * row["quantity"] for row in rows
            ) + unrealized,
        }
