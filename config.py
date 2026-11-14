"""Safe local configuration for the trading modules.

Credentials are read only from the local environment/.env file. Never commit .env.
The application is paper-trading-only; this file does not enable live order routing.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:
    pass

APP_MODE = os.getenv("APP_MODE", "PAPER").strip().upper()
LIVE_TRADING_ENABLED = False  # Hard safety lock: live orders are not implemented.
BYBIT_ENVIRONMENT = os.getenv("BYBIT_ENVIRONMENT", "demo").strip().lower()
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")

LEVERAGE = int(os.getenv("FUTURES_LEVERAGE", "7"))
TARGET_RR = float(os.getenv("TARGET_RR", "5.0"))
PAPER_CAPITAL_USDT = float(os.getenv("PAPER_CAPITAL_USDT", "200"))
SCAN_TIMEFRAME = os.getenv("SCAN_TIMEFRAME", "15m")
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "60"))

ACTIVE_PAIRS = [
    item.strip() for item in os.getenv(
        "ACTIVE_PAIRS", "BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT"
    ).split(",") if item.strip()
]
DEFAULT_EXCHANGE = os.getenv("DEFAULT_EXCHANGE", "Bybit Demo").strip()
DEFAULT_SYMBOL = os.getenv("DEFAULT_SYMBOL", "BTC/USDT:USDT").strip()
