"""Read-only local Bybit Demo preflight diagnostic.

Run from the project folder:
    .venv\\Scripts\\python.exe bybit_demo_diagnostic.py

Reads credentials from local .env through config.py. Never prints API keys.
Never submits, cancels, or closes orders.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
import ccxt
from exchange_manager import create_exchange
from config import BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_ENVIRONMENT, LIVE_TRADING_ENABLED

def main() -> int:
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": "BYBIT_DEMO",
        "checks": [],
        "order_placement_test": "NOT_RUN_READ_ONLY_DIAGNOSTIC",
        "live_trading_enabled": LIVE_TRADING_ENABLED,
    }
    def add(name, status, detail=None):
        row = {"name": name, "status": status}
        if detail is not None:
            row["detail"] = str(detail)[:300]
        report["checks"].append(row)

    if BYBIT_ENVIRONMENT != "demo":
        add("Demo environment setting", "FAIL", "Set BYBIT_ENVIRONMENT=demo in local .env.")
        report["overall"] = "FAIL"
        print(json.dumps(report, indent=2))
        return 1
    add("Demo environment setting", "PASS", "Demo environment selected.")

    if not BYBIT_API_KEY or not BYBIT_API_SECRET:
        add("Local API credentials", "FAIL", "Configure BYBIT_API_KEY and BYBIT_API_SECRET in local .env.")
        report["overall"] = "FAIL"
        print(json.dumps(report, indent=2))
        return 1
    add("Local API credentials", "PASS", "Credentials are configured; values are not displayed.")

    ex = None
    try:
        ex = create_exchange("Bybit Demo", "swap", require_auth=True)
        ex.timeout = 30000
        ex.load_markets()
        add("Demo client initialization", "PASS", "CCXT client initialized with Demo Trading enabled.")
        add("Bybit server time", "PASS", ex.fetch_time())

        markets = [m for m in ex.markets.values()
                   if m.get("swap") and m.get("linear") and m.get("settle") == "USDT"
                   and m.get("active", True)]
        add("USDT perpetual markets", "PASS" if markets else "FAIL",
            f"{len(markets)} active USDT-settled linear perpetual markets found.")

        balance = ex.fetch_balance()
        usdt = balance.get("USDT") or {}
        add("Authenticated account balance", "PASS",
            {"free": usdt.get("free"), "used": usdt.get("used"), "total": usdt.get("total")})

        try:
            positions = ex.fetch_positions()
            count = sum(1 for p in positions if float(p.get("contracts") or 0) > 0)
            add("Position read permission", "PASS", f"{count} open position(s) returned.")
        except Exception as exc:
            add("Position read permission", "FAIL", f"{type(exc).__name__}: {exc}")

        try:
            orders = ex.fetch_open_orders()
            add("Open-order read permission", "PASS", f"{len(orders)} open order(s) returned.")
        except Exception as exc:
            add("Open-order read permission", "FAIL", f"{type(exc).__name__}: {exc}")

        add("Demo order placement", "NOT_TESTED",
            "This diagnostic is read-only. Use the dashboard's manual Demo order control for an explicitly reviewed test order.")
    except Exception as exc:
        add("Bybit Demo connection/authentication", "FAIL", f"{type(exc).__name__}: {exc}")
    finally:
        if ex is not None:
            try:
                ex.close()
            except Exception:
                pass

    failed = any(item["status"] == "FAIL" for item in report["checks"])
    report["overall"] = "FAIL" if failed else "READ_ONLY_CHECKS_PASSED"
    report_path = "bybit_demo_diagnostic_report.json"
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps(report, indent=2))
    print(f"\\nSaved report: {report_path}")
    return 1 if failed else 0

if __name__ == "__main__":
    raise SystemExit(main())
