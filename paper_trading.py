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
            "entry_fee": "REAL NOT NULL DEFAULT 0",
            "fee_rate": "REAL NOT NULL DEFAULT 0.0006",
            "exit_fee": "REAL NOT NULL DEFAULT 0",
            "slippage_rate": "REAL NOT NULL DEFAULT 0",
            "liquidation_price": "REAL",
            "cumulative_funding": "REAL NOT NULL DEFAULT 0",
            "last_funding_timestamp": "INTEGER NOT NULL DEFAULT 0",
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
               leverage: float=1.0, target_rr: float=5.0,
               fee_rate: float=0.0006, slippage_rate: float=0.0005,
               maintenance_margin_rate: float=0.005, db_path: Path=DB_PATH):
    side=side.upper()
    if side not in {"LONG","SHORT"}: raise ValueError("side must be LONG or SHORT")
    if entry_price<=0 or quantity<=0: raise ValueError("entry_price and quantity must be greater than zero")
    if leverage<1 or leverage>125: raise ValueError("Leverage must be between 1x and 125x.")
    if not 0 <= fee_rate <= 0.02 or not 0 <= slippage_rate <= 0.02:
        raise ValueError("Fee and slippage rates must be between 0 and 2%.")
    if not 0 <= maintenance_margin_rate < 0.5:
        raise ValueError("Maintenance margin rate must be between 0 and 50%.")
    entry_price = float(entry_price) * (1 + slippage_rate if side == "LONG" else 1 - slippage_rate)
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
    entry_fee=notional*float(fee_rate)
    liq_distance=max(0.0, (1.0/float(leverage))-float(maintenance_margin_rate))
    liquidation_price=(entry_price*(1-liq_distance) if side=="LONG" else entry_price*(1+liq_distance))
    with _connection(db_path) as conn:
        a=conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
        if a is None: raise ValueError("Set paper capital before opening a trade.")
        if margin+entry_fee>a["cash_balance"]: raise ValueError("Insufficient paper cash for margin and entry fee.")
        now=_now()
        conn.execute("""INSERT INTO paper_trades(
            id,exchange,market_type,symbol,strategy,side,entry_price,quantity,stop_loss,
            take_profit,status,opened_at,leverage,margin_used,initial_stop_loss,
            entry_fee,fee_rate,slippage_rate,liquidation_price)
            VALUES(?,?,?,?,?,?,?,?,?,?, 'OPEN',?,?,?,?,?,?,?,?)""",
            (trade_id,exchange,market_type,symbol,strategy,side,float(entry_price),
             float(quantity),stop_loss,take_profit,now,float(leverage),margin,stop_loss,
             entry_fee,float(fee_rate),float(slippage_rate),liquidation_price))
        conn.execute("UPDATE paper_account SET cash_balance=cash_balance-?,updated_at=? WHERE id=1",(margin+entry_fee,now))
        return dict(conn.execute("SELECT * FROM paper_trades WHERE id=?",(trade_id,)).fetchone())

def close_trade(trade_id: str, exit_price: float, db_path: Path=DB_PATH):
    if exit_price<=0: raise ValueError("exit_price must be greater than zero.")
    initialize(db_path)
    with _connection(db_path) as conn:
        row=conn.execute("SELECT * FROM paper_trades WHERE id=? AND status='OPEN'",(trade_id,)).fetchone()
        if row is None: raise ValueError("Open paper trade not found.")
        sign=1.0 if row["side"]=="LONG" else -1.0
        fill=float(exit_price)*(1-row["slippage_rate"] if row["side"]=="LONG" else 1+row["slippage_rate"])
        gross_pnl=(fill-row["entry_price"])*row["quantity"]*sign
        exit_fee=fill*row["quantity"]*row["fee_rate"]
        pnl=gross_pnl-row["entry_fee"]-exit_fee+row["cumulative_funding"]
        now=_now()
        conn.execute("""UPDATE paper_trades SET status='CLOSED',closed_at=?,exit_price=?,realized_pnl=?,exit_fee=? WHERE id=?""",
                     (now,fill,pnl,exit_fee,trade_id))
        conn.execute("UPDATE paper_account SET cash_balance=cash_balance+?,updated_at=? WHERE id=?",
                     (row["margin_used"]+gross_pnl-exit_fee,now,1))
        return dict(conn.execute("SELECT * FROM paper_trades WHERE id=?",(trade_id,)).fetchone())

def monitor_open_trades(prices: dict[str,float], db_path: Path=DB_PATH):
    """Apply 1.5R break-even and SL/TP to open positions using supplied market prices."""
    initialize(db_path); events=[]
    with _connection(db_path) as conn:
        rows=conn.execute("SELECT * FROM paper_trades WHERE status='OPEN'").fetchall()
        for row in rows:
            price=prices.get(f'{row["exchange"]}|{row["symbol"]}', prices.get(row["symbol"]))
            if price is None or float(price)<=0: continue
            long=row["side"]=="LONG"
            stop=row["stop_loss"]
            be=bool(row["break_even_activated"])
            if row["initial_stop_loss"] is not None:
                risk=abs(row["entry_price"]-row["initial_stop_loss"])
                if risk>0:
                    trigger=row["entry_price"]+(1 if long else -1)*risk*1.5
                    if not be and ((long and price>=trigger) or (not long and price<=trigger)):
                        stop=row["entry_price"]; be=True
                        conn.execute("UPDATE paper_trades SET stop_loss=?,break_even_activated=1 WHERE id=?",(stop,row["id"]))
                        events.append({"trade_id":row["id"],"event":"BREAK_EVEN_ACTIVATED","stop_loss":stop})
            outcome=None
            liq=row["liquidation_price"]
            if liq is not None and ((long and price<=liq) or (not long and price>=liq)):
                outcome="ESTIMATED_LIQUIDATION"
            elif row["take_profit"] is not None and ((long and price>=row["take_profit"]) or (not long and price<=row["take_profit"])):
                outcome="TAKE_PROFIT"
            elif stop is not None and ((long and price<=stop) or (not long and price>=stop)):
                outcome="BREAK_EVEN" if be else "STOP_LOSS"
            if outcome:
                sign=1 if long else -1
                fill=float(price)*(1-row["slippage_rate"] if long else 1+row["slippage_rate"])
                gross_pnl=(fill-row["entry_price"])*row["quantity"]*sign
                exit_fee=fill*row["quantity"]*row["fee_rate"]
                pnl=gross_pnl-row["entry_fee"]-exit_fee
                now=_now()
                conn.execute("UPDATE paper_trades SET status='CLOSED',closed_at=?,exit_price=?,realized_pnl=?,exit_fee=? WHERE id=?",
                             (now,fill,pnl,exit_fee,row["id"]))
                conn.execute("UPDATE paper_account SET cash_balance=cash_balance+?,updated_at=? WHERE id=1",
                             (row["margin_used"]+gross_pnl-exit_fee,now))
                events.append({"trade_id":row["id"],"event":outcome,"exit_price":float(price),"realized_pnl":pnl})
    return events


def apply_funding_rate(exchange: str, symbol: str, funding_rate: float,
                       funding_timestamp: int, db_path: Path=DB_PATH):
    """Apply a funding settlement once per open position and exchange timestamp."""
    if not -0.1 <= float(funding_rate) <= 0.1:
        raise ValueError("Funding rate outside the supported safety range.")
    if int(funding_timestamp) <= 0:
        raise ValueError("A valid funding settlement timestamp is required.")
    initialize(db_path)
    applied = []
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if now_ms < int(funding_timestamp):
        return applied
    with _connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM paper_trades WHERE status='OPEN' AND exchange=? AND symbol=?",
            (exchange, symbol)
        ).fetchall()
        for row in rows:
            if int(row["last_funding_timestamp"] or 0) >= int(funding_timestamp):
                continue
            notional = row["entry_price"] * row["quantity"]
            direction = 1 if row["side"] == "LONG" else -1
            payment = -direction * notional * float(funding_rate)
            now = _now()
            conn.execute(
                "UPDATE paper_trades SET cumulative_funding=cumulative_funding+?,last_funding_timestamp=? WHERE id=?",
                (payment, int(funding_timestamp), row["id"])
            )
            conn.execute(
                "UPDATE paper_account SET cash_balance=cash_balance+?,updated_at=? WHERE id=1",
                (payment, now)
            )
            applied.append({"trade_id": row["id"], "funding_payment": payment,
                            "funding_rate": float(funding_rate),
                            "funding_timestamp": int(funding_timestamp)})
    return applied


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
            price=prices.get(f'{r["exchange"]}|{r["symbol"]}', prices.get(r["symbol"]))
            if price is not None:
                unrealized+=(float(price)-r["entry_price"])*r["quantity"]*(1 if r["side"]=="LONG" else -1)
        margin=sum(r["margin_used"] for r in rows)
        return {"configured":True,"starting_capital":a["starting_capital"],
            "cash_balance":a["cash_balance"],"margin_used":margin,"open_positions":len(rows),
            "unrealized_pnl":unrealized,"equity":a["cash_balance"]+margin+unrealized}
