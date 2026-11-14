# Multi-Exchange Trading Module Bot

A local dashboard and paper-trading research project. **Live order execution is disabled.**
The current implementation stores simulated trades in a local SQLite database and uses
exchange connections for market data and (when configured) account verification only.

## Safety first

- Do not paste API keys into chat, source files, screenshots, or GitHub.
- Copy `.env.example` to `.env` on your own Windows computer and enter credentials locally.
- Keep API permissions to read/account access for the connection test. Do not enable withdrawals or transfers.
- Restrict API access by IP where practical.
- The dashboard's local paper trades do not appear in the Bybit mobile app.
- This code does not submit exchange orders. Do not treat paper results as evidence of profitability.

## Bybit Demo Trading

Create the API key while switched into **Demo Trading** on Bybit. A Testnet key is not interchangeable.
This project uses CCXT's `enable_demo_trading(True)`; it does not use `set_sandbox_mode(True)`.
Bybit Demo API availability is not identical to production and some API functions may be unavailable.

## Windows setup

1. Install Python 3.10 or newer.
2. Download/clone this repository branch.
3. Open Command Prompt in the project folder.
4. Create and activate a virtual environment:

   ```bat
   py -m venv .venv
   .venv\Scripts\activate
   ```

5. Install dependencies:

   ```bat
   py -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

6. Copy the environment template and edit it locally:

   ```bat
   copy .env.example .env
   notepad .env
   ```

7. Set `BYBIT_API_KEY` and `BYBIT_API_SECRET` in `.env`. Never commit that file.
8. Start the dashboard:

   ```bat
   python bot_master.py
   ```

9. Open http://127.0.0.1:8000

## Current functionality

- Local SQLite paper account and trade ledger.
- Configurable initial paper capital (default 200 USDT).
- Public market data through CCXT.
- Bybit Demo connection verification when local credentials are configured.
- Manual local paper trades using the latest fetched market price.
- Read-only strategy scan endpoint for Modules I and II.
- Strategy signals are reported, not automatically traded.
- Dashboard API reports unavailable data explicitly rather than fabricating figures.

## Not yet implemented / not to be assumed available

- Automated paper position monitoring, stop/target execution and risk-based position sizing.
- Fully integrated scanner scheduler and duplicate-signal protection.
- Genuine OI, CVD, liquidation/heatmap, footprint, funding and large-trade providers.
- Reliable event-time macro calendar and X/social feeds.
- Real WhatsApp delivery.
- Fully functional dashboard sections for every navigation item.
- Live trading (intentionally disabled).

## API endpoints

- `GET /api/dashboard-data`
- `GET /api/connection-check`
- `GET /api/strategies`
- `GET /api/paper-trades`
- `POST /api/switch-exchange`
- `POST /api/switch-symbol`
- `POST /api/capital`
- `POST /api/place-trade` — local paper trade only
- `POST /api/close-paper-trade/{trade_id}` — local paper trade only
- `POST /api/scan-once` — read-only scan; no order execution

## Notes

The futures symbol format is typically `BTC/USDT:USDT`; spot uses `BTC/USDT`.
The configured default market is swap. Confirm a symbol exists on the selected exchange
before scanning or opening a simulated position.
