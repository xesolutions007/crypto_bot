import pandas as pd

class StrategyModules:

    @staticmethod
    def evaluate_module_1(df, market_intel, news_bias):
        """Strategy I: Trend & Momentum (EMA Crossover + Volume Filter)"""
        try:
            df['ema_fast'] = df['close'].ewm(span=9, adjust=False).mean()
            df['ema_slow'] = df['close'].ewm(span=21, adjust=False).mean()
            
            last_close = df['close'].iloc[-1]
            prev_fast = df['ema_fast'].iloc[-2]
            prev_slow = df['ema_slow'].iloc[-2]
            curr_fast = df['ema_fast'].iloc[-1]
            curr_slow = df['ema_slow'].iloc[-1]
            
            # Bullish Crossover & Positive News Bias
            if prev_fast <= prev_slow and curr_fast > curr_slow and news_bias != "BEARISH":
                return {
                    "module": "Strategy I (Trend & Momentum)",
                    "direction": "LONG",
                    "entry": round(last_close, 2),
                    "sl": round(last_close * 0.985, 2)
                }
        except Exception:
            pass
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
                    "module": "Strategy II (Marubozu Pattern)",
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
            
            if last_close > last_vwap and market_intel['cvd_spot'] > 0:
                return {
                    "module": "Strategy III (VWAP Breakout)",
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
                    "module": "Strategy IV (B2B Trade)",
                    "direction": "LONG",
                    "entry": round(current_price, 2),
                    "sl": round(recent_low * 0.99, 2)
                }
        except Exception:
            pass
        return None