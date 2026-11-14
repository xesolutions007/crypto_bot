import pytest
import paper_trading


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "paper.sqlite3"
    paper_trading.initialize(path)
    paper_trading.set_capital(200, path)
    return path


def open_position(path, side="LONG", stop=99, leverage=7):
    return paper_trading.open_trade(
        exchange="Bybit Demo", market_type="swap", symbol="BTC/USDT:USDT",
        strategy="test", side=side, entry_price=100, quantity=1,
        stop_loss=stop, leverage=leverage, target_rr=5, fee_rate=0, slippage_rate=0, db_path=path,
    )


def test_leverage_reserves_margin_not_full_notional(db):
    trade = open_position(db)
    assert trade["margin_used"] == pytest.approx(100 / 7)
    account = paper_trading.account(db)
    assert account["cash_balance"] == pytest.approx(200 - 100 / 7)
    assert account["margin_used"] == pytest.approx(100 / 7)


def test_close_releases_margin_and_applies_pnl(db):
    trade = open_position(db)
    closed = paper_trading.close_trade(trade["id"], 105, db)
    assert closed["realized_pnl"] == pytest.approx(5)
    assert paper_trading.account(db)["cash_balance"] == pytest.approx(200 - 100 / 7 + 100 / 7 + 5)


def test_break_even_activates_at_one_point_five_r(db):
    trade = open_position(db, stop=99)
    events = paper_trading.monitor_open_trades({"BTC/USDT:USDT": 101.5}, db)
    assert any(e["event"] == "BREAK_EVEN_ACTIVATED" for e in events)
    current = paper_trading.list_trades("OPEN", db_path=db)[0]
    assert current["stop_loss"] == pytest.approx(100)
    assert current["break_even_activated"] == 1


def test_break_even_stop_closes_position(db):
    trade = open_position(db, stop=99)
    paper_trading.monitor_open_trades({"BTC/USDT:USDT": 101.5}, db)
    events = paper_trading.monitor_open_trades({"BTC/USDT:USDT": 100}, db)
    assert any(e["event"] == "BREAK_EVEN" for e in events)
    closed = paper_trading.list_trades("CLOSED", db_path=db)[0]
    assert closed["realized_pnl"] == pytest.approx(0)


def test_take_profit_is_five_r(db):
    trade = open_position(db, stop=99)
    assert trade["take_profit"] == pytest.approx(105)
    events = paper_trading.monitor_open_trades({"BTC/USDT:USDT": 105}, db)
    assert any(e["event"] == "TAKE_PROFIT" for e in events)

def test_monitor_uses_exchange_specific_prices(db):
    bybit = open_position(db, stop=99)
    binance = paper_trading.open_trade(
        exchange="Binance", market_type="swap", symbol="BTC/USDT:USDT",
        strategy="test", side="LONG", entry_price=100, quantity=1,
        stop_loss=99, leverage=7, target_rr=5, db_path=db,
    )
    events = paper_trading.monitor_open_trades({
        "Bybit Demo|BTC/USDT:USDT": 98,
        "Binance|BTC/USDT:USDT": 101,
    }, db)
    closed_ids = {e["trade_id"] for e in events if e["event"] == "STOP_LOSS"}
    assert bybit["id"] in closed_ids
    assert binance["id"] not in closed_ids
    open_ids = {t["id"] for t in paper_trading.list_trades("OPEN", db_path=db)}
    assert binance["id"] in open_ids



def test_fees_reduce_net_realized_pnl(db):
    trade = paper_trading.open_trade(
        exchange="Bybit Demo", market_type="swap", symbol="BTC/USDT:USDT",
        strategy="cost-test", side="LONG", entry_price=100, quantity=1,
        leverage=7, fee_rate=0.001, slippage_rate=0, db_path=db,
    )
    closed = paper_trading.close_trade(trade["id"], 110, db)
    assert closed["entry_fee"] == pytest.approx(0.1)
    assert closed["exit_fee"] == pytest.approx(0.11)
    assert closed["realized_pnl"] == pytest.approx(9.79)


def test_long_estimated_liquidation_price_is_below_entry(db):
    trade = open_position(db)
    assert trade["liquidation_price"] < trade["entry_price"]
    assert trade["liquidation_price"] == pytest.approx(100 * (1 - (1/7 - 0.005)))


def test_adverse_slippage_adjusts_long_entry(db):
    trade = paper_trading.open_trade(
        exchange="Bybit Demo", market_type="swap", symbol="BTC/USDT:USDT",
        strategy="slippage-test", side="LONG", entry_price=100, quantity=1,
        leverage=7, fee_rate=0, slippage_rate=0.001, db_path=db,
    )
    assert trade["entry_price"] == pytest.approx(100.1)



def test_funding_is_applied_once_and_included_in_pnl(db):
    from datetime import datetime, timezone
    trade = paper_trading.open_trade(
        exchange="Bybit Demo", market_type="swap", symbol="BTC/USDT:USDT",
        strategy="funding-test", side="LONG", entry_price=100, quantity=1,
        leverage=7, fee_rate=0, slippage_rate=0, db_path=db,
    )
    settlement = int(datetime.now(timezone.utc).timestamp() * 1000) - 1000
    first = paper_trading.apply_funding_rate("Bybit Demo", "BTC/USDT:USDT", 0.001, settlement, db_path=db)
    second = paper_trading.apply_funding_rate("Bybit Demo", "BTC/USDT:USDT", 0.001, settlement, db)
    assert len(first) == 1
    assert second == []
    current = paper_trading.list_trades("OPEN", db_path=db)[0]
    assert current["cumulative_funding"] == pytest.approx(-0.1)
    closed = paper_trading.close_trade(trade["id"], 100, db)
    assert closed["realized_pnl"] == pytest.approx(-0.1)


def test_negative_funding_credits_long(db):
    from datetime import datetime, timezone
    paper_trading.open_trade(
        exchange="Bybit Demo", market_type="swap", symbol="BTC/USDT:USDT",
        strategy="funding-test", side="LONG", entry_price=100, quantity=1,
        leverage=7, fee_rate=0, slippage_rate=0, db_path=db,
    )
    settlement = int(datetime.now(timezone.utc).timestamp() * 1000) - 1000
    events = paper_trading.apply_funding_rate("Bybit Demo", "BTC/USDT:USDT", -0.001, settlement, db_path=db)
    assert events[0]["funding_payment"] == pytest.approx(0.1)
