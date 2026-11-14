"""Persistent local futures paper ledger. Never submits exchange orders."""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import uuid

DB_PATH = Path(__file__).with_name("paper_trading.sqlite3")

def _now():
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

def initialize(db_path: Path = DB_PATH):
    with _connection(db_path) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS paper_account (
            id INTEGER PRIMARY KEY CHECK(id=1), starting_capital REAL NOT NULL,
            cash_balance REAL NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS paper_trades (
            id TEXT PRIMARY KEY, exchange TEXT NOT NULL, market_type TEXT NOT NULL,
            symbol TEXT NOT NULL, strategy TEXT NOT NULL,
            side TEXT NOT NULL CHECK(side IN ('LONG','SHORT')),
            entry_price REAL NOT NULL, quantity REAL NOT NULL,
            stop_loss REAL, take_profit REAL, status TEXT NOT NULL CHECK(status IN ('OPEN','CLOSED')),
            opened_at TEXT NOT NULL, closed_at TEXT, exit_price REAL, realized_pnl REAL)""")
        # Safe additive migrations preserve existing local paper-trade history.
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(paper_trades)")}
        additions = {
            "leverage": "REAL NOT NULL DEFAULT 1",
            "margin_used": "REAL NOT NULL DEFAULT 0",
            "initial_stop_loss": "REAL",
            "break_even_activated": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE paper_trades ADD COLUMN {name} {definition}")
        # Legacy positions reserved full notional; preserve their existing reserved cash.
        conn.execute("UPDATE paper_trades SET margin_used=entry_price*quantity WHERE margin_used=0 AND status='OPEN'")

def set_capital(amount: float, db_path: Path = DB_PATH):
    if amount <= 0: raise ValueError("Paper capital must be greater than zero.")
    initialize(db_path); now = _now()
    with _connection(db_path) as conn:
        if conn.execute("SELECT COUNT(*) FROM paper_trades WHERE status='OPEN'").fetchone()[0]:
            raise ValueError("Close all open paper positions before resetting capital.")
        conn.execute("""INSERT INTO paper_account VALUES(1,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET starting_capital=excluded.starting_capital,
            cash_balance=excluded.cash_balance,updated_at=excluded.updated_at""",
            (float(amount),float(amount),now,now))
    return account(db_path)

def account(db_path: Path = DB_PATH):
    initialize(db_path)
    with _connection(db_path) as conn:
        a=conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
        if a is None: return {"configured":False,"starting_capital":0.0,"cash_balance":0.0}
        rows=conn.execute("SELECT * FROM paper_trades WHERE status='OPEN'").fetchall()
        return {"configured":True,"starting_capital":a["starting_capital"],
            "cash_balance":a["cash_balance"],"open_positions":len(rows),
            "margin_used":sum(r["margin_used"] for r in rows),"updated_at":a["updated_at"]}

def open_trade(exchange: str, market_type: str, symbol: str, strategy: str,
               side: str, entry_price: float, quantity: float,
               stop_loss: Optional[float]=None, take_profit: Optional[float]=None,
               leverage: float=1.0, target_rr: float=5.0, db_path: Path=DB_PATH):
    side=side.upper()
    if side not in {"LONG","SHORT"}: raise ValueError("side must be LONG or SHORT")
    if entry_price<=0 or quantity<=0: raise ValueError("entry_price and quantity must be greater than zero")
    if leverage<1 or leverage>125: raise ValueError("Leverage must be between 1x and 125x.")
    if stop_loss is not None:
        if (side=="LONG" and not 0<stop_loss<entry_price) or (side=="SHORT" and stop_loss<=entry_price):
            raise ValueError("Stop-loss must be below entry for LONG and above entry for SHORT.")
        risk=abs(entry_price-stop_loss)
        if take_profit is None:
            take_profit=entry_price + risk*target_rr*(1 if side=="LONG" else -1)
    if take_profit is not None and ((side=="LONG" and take_profit<=entry_price) or (side=="SHORT" and take_profit>=entry_price)):
        raise ValueError("Take-profit must be above entry for LONG and below entry for SHORT.")
    initialize(db_path); trade_id=str(uuid.uuid4()); notional=float(entry_price)*float(quantity)
    margin=notional/float(leverage)
    with _connection(db_path) as conn:
        a=conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
        if a is None: raise ValueError("Set paper capital before opening a trade.")
        if margin>a["cash_balance"]: raise ValueError("Insufficient paper cash for the required leveraged margin.")
        now=_now()
        conn.execute("""INSERT INTO paper_trades(
            id,exchange,market_type,symbol,strategy,side,entry_price,quantity,stop_loss,
            take_profit,status,opened_at,leverage,margin_used,initial_stop_loss)
            VALUES(?,?,?,?,?,?,?,?,?,?, 'OPEN',?,?,?,?)""",
            (trade_id,exchange,market_type,symbol,strategy,side,float(entry_price),
             float(quantity),stop_loss,take_profit,now,float(leverage),margin,stop_loss))
        conn.execute("UPDATE paper_account SET cash_balance=cash_balance-?,updated_at=? WHERE id=1",(margin,now))
        return dict(conn.execute("SELECT * FROM paper_trades WHERE id=?",(trade_id,)).fetchone())

def close_trade(trade_id: str, exit_price: float, db_path: Path=DB_PATH):
    if exit_price<=0: raise ValueError("exit_price must be greater than zero.")
    initialize(db_path)
    with _connection(db_path) as conn:
        row=conn.execute("SELECT * FROM paper_trades WHERE id=? AND status='OPEN'",(trade_id,)).fetchone()
        if row is None: raise ValueError("Open paper trade not found.")
        sign=1.0 if row["side"]=="LONG" else -1.0
        pnl=(float(exit_price)-row["entry_price"])*row["quantity"]*sign
        now=_now()
        conn.execute("""UPDATE paper_trades SET status='CLOSED',closed_at=?,exit_price=?,realized_pnl=? WHERE id=?""",
                     (now,float(exit_price),pnl,trade_id))
        conn.execute("UPDATE paper_account SET cash_balance=cash_balance+?,updated_at=? WHERE id=?",
                     (row["margin_used"]+pnl,now,1))
        return dict(conn.execute("SELECT * FROM paper_trades WHERE id=?",(trade_id,)).fetchone())

def monitor_open_trades(prices: dict[str,float], db_path: Path=DB_PATH):
    """Apply 1.5R break-even and SL/TP to open positions using supplied market prices."""
    initialize(db_path); events=[]
    with _connection(db_path) as conn:
        rows=conn.execute("SELECT * FROM paper_trades WHERE status='OPEN'").fetchall()
        for row in rows:
            price=prices.get(row["symbol"])
            if price is None or float(price)<=0: continue
            if row["initial_stop_loss"] is None: continue
            risk=abs(row["entry_price"]-row["initial_stop_loss"])
            if risk<=0: continue
            long=row["side"]=="LONG"
            trigger=row["entry_price"]+(1 if long else -1)*risk*1.5
            stop=row["stop_loss"]
            be=bool(row["break_even_activated"])
            if not be and ((long and price>=trigger) or (not long and price<=trigger)):
                stop=row["entry_price"]; be=True
                conn.execute("UPDATE paper_trades SET stop_loss=?,break_even_activated=1 WHERE id=?",(stop,row["id"]))
                events.append({"trade_id":row["id"],"event":"BREAK_EVEN_ACTIVATED","stop_loss":stop})
            outcome=None
            if row["take_profit"] is not None and ((long and price>=row["take_profit"]) or (not long and price<=row["take_profit"])):
                outcome="TAKE_PROFIT"
            elif stop is not None and ((long and price<=stop) or (not long and price>=stop)):
                outcome="BREAK_EVEN" if be else "STOP_LOSS"
            if outcome:
                sign=1 if long else -1
                pnl=(float(price)-row["entry_price"])*row["quantity"]*sign
                now=_now()
                conn.execute("UPDATE paper_trades SET status='CLOSED',closed_at=?,exit_price=?,realized_pnl=? WHERE id=?",
                             (now,float(price),pnl,row["id"]))
                conn.execute("UPDATE paper_account SET cash_balance=cash_balance+?,updated_at=? WHERE id=1",
                             (row["margin_used"]+pnl,now))
                events.append({"trade_id":row["id"],"event":outcome,"exit_price":float(price),"realized_pnl":pnl})
    return events

def list_trades(status: Optional[str]=None, limit: int=100, db_path: Path=DB_PATH):
    initialize(db_path)
    if limit<1 or limit>1000: raise ValueError("limit must be between 1 and 1000")
    with _connection(db_path) as conn:
        if status:
            rows=conn.execute("SELECT * FROM paper_trades WHERE status=? ORDER BY opened_at DESC LIMIT ?",(status.upper(),limit)).fetchall()
        else: rows=conn.execute("SELECT * FROM paper_trades ORDER BY opened_at DESC LIMIT ?",(limit,)).fetchall()
        return [dict(r) for r in rows]

def mark_to_market(prices: dict[str,float], db_path: Path=DB_PATH):
    initialize(db_path)
    with _connection(db_path) as conn:
        a=conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
        if a is None: return {"configured":False,"equity":0.0,"unrealized_pnl":0.0}
        rows=conn.execute("SELECT * FROM paper_trades WHERE status='OPEN'").fetchall()
        unrealized=0.0
        for r in rows:
            price=prices.get(r["symbol"])
            if price is not None:
                unrealized+=(float(price)-r["entry_price"])*r["quantity"]*(1 if r["side"]=="LONG" else -1)
        margin=sum(r["margin_used"] for r in rows)
        return {"configured":True,"starting_capital":a["starting_capital"],
            "cash_balance":a["cash_balance"],"margin_used":margin,"open_positions":len(rows),
            "unrealized_pnl":unrealized,"equity":a["cash_balance"]+margin+unrealized}
