import pandas as pd

from strategies import StrategyModules


def candles(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])


def test_module_1_rejects_insufficient_history():
    frame = pd.DataFrame({
        "open": [100] * 50, "high": [101] * 50,
        "low": [99] * 50, "close": [100] * 50,
    })
    assert StrategyModules.evaluate_module_1(frame, {}, "NEUTRAL") is None


def test_module_2_detects_bullish_marubozu():
    frame = candles([[100, 111, 99, 110, 1000]])
    signal = StrategyModules.evaluate_module_2(frame, {}, "NEUTRAL")
    assert signal["module"] == "Strategy Module II"
    assert signal["direction"] == "LONG"
    assert signal["sl"] == 99


def test_module_2_detects_bearish_marubozu():
    frame = candles([[110, 111, 99, 100, 1000]])
    signal = StrategyModules.evaluate_module_2(frame, {}, "NEUTRAL")
    assert signal["direction"] == "SHORT"
    assert signal["sl"] == 111


def test_module_2_rejects_small_body():
    frame = candles([[100, 110, 90, 101, 1000]])
    assert StrategyModules.evaluate_module_2(frame, {}, "NEUTRAL") is None


def test_module_3_requires_uptrend_vwap_and_positive_cvd():
    frame = candles([
        [100, 102, 99, 101, 10],
        [101, 104, 100, 103, 10],
    ])
    signal = StrategyModules.evaluate_module_3(
        frame, "UP", {"cvd_spot": 1}, "NEUTRAL"
    )
    assert signal["module"] == "Strategy Module III"
    assert signal["direction"] == "LONG"
    assert signal["entry"] > signal["sl"]


def test_module_3_rejects_missing_or_nonpositive_cvd():
    frame = candles([[100, 102, 99, 101, 10], [101, 104, 100, 103, 10]])
    assert StrategyModules.evaluate_module_3(frame, "UP", {}, "NEUTRAL") is None
    assert StrategyModules.evaluate_module_3(
        frame, "UP", {"cvd_spot": 0}, "NEUTRAL"
    ) is None


def test_module_3_rejects_non_uptrend():
    frame = candles([[100, 102, 99, 101, 10], [101, 104, 100, 103, 10]])
    assert StrategyModules.evaluate_module_3(
        frame, "DOWN", {"cvd_spot": 10}, "NEUTRAL"
    ) is None


def test_module_4_detects_bounce_with_high_open_interest():
    rows = [[105, 106, 104, 105, 100] for _ in range(20)]
    rows[-1] = [104.9, 105.2, 104, 104.5, 100]
    frame = candles(rows)
    signal = StrategyModules.evaluate_module_4(
        frame, {"open_interest": 1_100_000_000}, "NEUTRAL", 104.5
    )
    assert signal["module"] == "Strategy Module IV"
    assert signal["direction"] == "LONG"
    assert signal["sl"] < 104


def test_module_4_rejects_low_open_interest_or_price_away_from_support():
    frame = candles([[105, 106, 104, 105, 100] for _ in range(20)])
    assert StrategyModules.evaluate_module_4(
        frame, {"open_interest": 999_000_000}, "NEUTRAL", 104.5
    ) is None
    assert StrategyModules.evaluate_module_4(
        frame, {"open_interest": 2_000_000_000}, "NEUTRAL", 110
    ) is None
