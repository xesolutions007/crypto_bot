import pandas as pd


class StrategyModules:

    @staticmethod
    def evaluate_module_1(df, market_intel, news_bias):
        """Strategy Module I: SMA 20/200 trend crossover with Stochastic confirmation.

        LONG: SMA 20 crosses above SMA 200; bullish candle closes above both
        averages; Stochastic %K crosses above %D in the lower (25) band.
        SHORT: SMA 20 crosses below SMA 200; bearish candle closes below both
        averages; Stochastic %K crosses below %D in the upper (75) band.

        Stochastic settings: %K period=3, %D smoothing=3; bands=25/75.
        """
        try:
            required = {"open", "high", "low", "close"}
            if df is None or len(df) < 202 or not required.issubset(df.columns):
                return None

            data = df.copy()
            for column in ("open", "high", "low", "close"):
                data[column] = pd.to_numeric(data[column], errors="coerce")

            data["sma_20"] = data["close"].rolling(window=20, min_periods=20).mean()
            data["sma_200"] = data["close"].rolling(window=200, min_periods=200).mean()

            # Stochastic oscillator: 3-period %K and 3-period %D.
            lowest_low = data["low"].rolling(window=3, min_periods=3).min()
            highest_high = data["high"].rolling(window=3, min_periods=3).max()
            price_range = (highest_high - lowest_low).replace(0, float("nan"))
            data["stoch_k"] = 100 * (data["close"] - lowest_low) / price_range
            data["stoch_d"] = data["stoch_k"].rolling(window=3, min_periods=3).mean()

            previous = data.iloc[-2]
            latest = data.iloc[-1]
            values = [
                previous["sma_20"], previous["sma_200"],
                latest["sma_20"], latest["sma_200"],
                previous["stoch_k"], previous["stoch_d"],
                latest["stoch_k"], latest["stoch_d"],
            ]
            if any(pd.isna(value) for value in values):
                return None

            bullish_ma_cross = (
                previous["sma_20"] <= previous["sma_200"]
                and latest["sma_20"] > latest["sma_200"]
            )
            bearish_ma_cross = (
                previous["sma_20"] >= previous["sma_200"]
                and latest["sma_20"] < latest["sma_200"]
            )
            bullish_stoch_cross = (
                previous["stoch_k"] <= previous["stoch_d"]
                and latest["stoch_k"] > latest["stoch_d"]
                and latest["stoch_k"] <= 25
            )
            bearish_stoch_cross = (
                previous["stoch_k"] >= previous["stoch_d"]
                and latest["stoch_k"] < latest["stoch_d"]
                and latest["stoch_k"] >= 75
            )

            # Respect a bearish news pause/bias when considering a LONG signal.
            bearish_news = str(news_bias).upper() in {"BEARISH", "BEARISH_BIAS", "HIGH_IMPACT_PAUSE"}
            close = float(latest["close"])

            if (
                bullish_ma_cross
                and float(latest["close"]) > float(latest["open"])
                and close > float(latest["sma_20"])
                and close > float(latest["sma_200"])
                and bullish_stoch_cross
                and not bearish_news
            ):
                return {
                    "module": "Strategy Module I",
                    "direction": "LONG",
                    "entry": round(close, 2),
                    "sl": round(float(latest["low"]), 2),
                }

            if (
                bearish_ma_cross
                and float(latest["close"]) < float(latest["open"])
                and close < float(latest["sma_20"])
                and close < float(latest["sma_200"])
                and bearish_stoch_cross
            ):
                return {
                    "module": "Strategy Module I",
                    "direction": "SHORT",
                    "entry": round(close, 2),
                    "sl": round(float(latest["high"]), 2),
                }
        except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError):
            return None
        return None

    @staticmethod
    def evaluate_module_2(df, market_intel, news_bias):
        """Strategy II: Marubozu Candle Pattern"""
        try:
            last = df.iloc[-1]
            body = abs(last['close'] - last['open'])
            total_range = last['high'] - last['low']

            # Strong Marubozu candle (>80% body ratio)
            if total_range > 0 and (body / total_range) > 0.8:
                direction = "LONG" if last['close'] > last['open'] else "SHORT"
                return {
                    "module": "Strategy Module II",
                    "direction": direction,
                    "entry": round(last['close'], 2),
                    "sl": round(last['low'] if direction == "LONG" else last['high'], 2)
                }
        except Exception:
            pass
        return None

    @staticmethod
    def evaluate_module_3(df, trend_direction, market_intel, news_bias):
        """Strategy III: VWAP Breakout"""
        try:
            typical_price = (df['high'] + df['low'] + df['close']) / 3
            df['vwap'] = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()

            last_close = df['close'].iloc[-1]
            last_vwap = df['vwap'].iloc[-1]

            if str(trend_direction).upper() == "UP" and last_close > last_vwap and market_intel['cvd_spot'] > 0:
                return {
                    "module": "Strategy Module III",
                    "direction": "LONG",
                    "entry": round(last_close, 2),
                    "sl": round(last_vwap, 2)
                }
        except Exception:
            pass
        return None

    @staticmethod
    def evaluate_module_4(df, market_intel, news_bias, current_price):
        """Strategy IV: B2B (Range Boundary & Open Interest Filter)"""
        try:
            recent_low = df['low'].tail(20).min()
            recent_high = df['high'].tail(20).max()

            # Bounce near support
            if current_price <= recent_low * 1.002 and market_intel['open_interest'] > 1000000000:
                return {
                    "module": "Strategy Module IV",
                    "direction": "LONG",
                    "entry": round(current_price, 2),
                    "sl": round(recent_low * 0.99, 2)
                }
        except Exception:
            pass
        return None
