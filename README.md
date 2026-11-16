# Bybit Demo Futures Trading Bot

A local dashboard and automated scanner for **Bybit Demo USDT-settled linear perpetual Futures only**. Paper trading, local simulated accounts, Spot trading and other exchanges are not part of this project.

## Safety
- Live order routing is hard-disabled in code.
- All order requests must use the Bybit Demo environment and USDT perpetual swap markets.
- Never paste API credentials into chat, screenshots or GitHub. Store them only in your local ignored `.env` file.
- Use a Bybit Demo API key with only the permissions needed for reading account data and placing derivatives orders. Do not enable withdrawals or transfers.
- A successful local API response or CI test does not prove your personal exchange credentials work. Verify orders and fills inside Bybit Demo.

## Windows setup
1. Extract the ZIP.
2. Copy `.env.example` to `.env`.
3. Add your Bybit Demo API key and secret locally.
4. Run `start_bot.bat`.
5. Open the local dashboard at https://botstrategiesmodules:8000/.

## Configuration
- `BYBIT_ENVIRONMENT=demo` — required Demo environment.
- `BYBIT_DEMO_AUTO_EXECUTION=true` — automatic Demo execution.
- `BYBIT_DEMO_ORDER_NOTIONAL_USDT=3` — default automatic order notional.
- `BYBIT_DEMO_TOTAL_BUDGET_USDT=250` — combined open-position notional ceiling.
- `FUTURES_LEVERAGE=7` — maximum leverage.
- `ACTIVE_PAIRS=` — blank means all active eligible Bybit USDT linear perpetual pairs.
- `SCAN_TIMEFRAME=15m`, `SCAN_INTERVAL_SECONDS=60`.

## Features
- Bybit Demo account balance, positions, orders and exchange-reported trade history.
- Manual Market, Limit and Stop-Limit Demo orders.
- Hedge Mode Long and Short positions, with adjustable leverage and protective prices.
- All-eligible-pairs scanner and strategy signal generation.
- Automatic Demo orders subject to notional, total exposure and leverage safeguards.
- Live trading is unavailable.

## Tests
Run `.venv\\Scripts\\python.exe -m pytest -q` from the project folder.
Passing tests validate local code only, not authenticated exchange connectivity or order fills.

## API
- `GET /api/bybit-demo/account`
- `GET /api/bybit-demo/symbols`
- `GET /api/bybit-demo/positions`
- `GET /api/bybit-demo/orders`
- `GET /api/bybit-demo/trades`
- `POST /api/bybit-demo/order`
- `POST /api/bybit-demo/close-position`
- `POST /api/toggle` — scanner start/stop
- `POST /api/scan-once` — read-only scan
