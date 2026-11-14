"""Exchange connections for public market data and Bybit Demo account checks.

No order-placement method is exposed here. All trading remains local paper trading.
"""
import os
import ccxt


SUPPORTED_EXCHANGES = {
    "Bybit Demo": "bybit",
    "Binance": "binance",
    "KuCoin": "kucoin",
    "Bitget": "bitget",
}


def _credentials_for(exchange_name: str) -> tuple[str, str]:
    prefix = exchange_name.upper().replace(" ", "_")
    if exchange_name == "Bybit Demo":
        return os.getenv("BYBIT_API_KEY", ""), os.getenv("BYBIT_API_SECRET", "")
    return os.getenv(f"{prefix}_API_KEY", ""), os.getenv(f"{prefix}_API_SECRET", "")


def create_exchange(exchange_name: str, market_type: str = "swap",
                    require_auth: bool = False):
    if exchange_name not in SUPPORTED_EXCHANGES:
        raise ValueError(f"Unsupported exchange: {exchange_name}")
    if market_type not in {"spot", "swap"}:
        raise ValueError("market_type must be 'spot' or 'swap'")

    exchange_id = SUPPORTED_EXCHANGES[exchange_name]
    api_key, secret = _credentials_for(exchange_name)
    if require_auth and (not api_key or not secret):
        raise RuntimeError(f"Local API credentials are not configured for {exchange_name}.")

    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({
        "enableRateLimit": True,
        "apiKey": api_key or None,
        "secret": secret or None,
        "options": {"defaultType": market_type},
    })

    if exchange_name == "Bybit Demo":
        if not hasattr(exchange, "enable_demo_trading"):
            raise RuntimeError(
                "Installed CCXT is too old for Bybit Demo. Upgrade CCXT to a version "
                "that supports enable_demo_trading(True)."
            )
        exchange.enable_demo_trading(True)
    return exchange


def connection_check(exchange_name: str = "Bybit Demo",
                     market_type: str = "swap") -> dict:
    """Check public market access; authenticate only when local credentials exist."""
    exchange = create_exchange(exchange_name, market_type, require_auth=False)
    result = {
        "exchange": exchange_name,
        "environment": "Demo Trading" if exchange_name == "Bybit Demo" else "Public market data",
        "market_type": market_type,
        "authenticated": False,
        "market_data": False,
        "status": "checking",
    }
    try:
        exchange.load_markets()
        result["market_data"] = True
        result["server_time"] = exchange.fetch_time()
        if exchange.apiKey and exchange.secret:
            balance = exchange.fetch_balance()
            result["authenticated"] = True
            result["account_check"] = "passed"
            result["usdt_balance_available"] = balance.get("free", {}).get("USDT")
        result["status"] = "connected"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
    finally:
        try:
            exchange.close()
        except Exception:
            pass
    return result
