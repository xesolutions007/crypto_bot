# Multi-Exchange Trading Module Bot

A local dashboard and **paper-trading-only** research project for Binance, Bybit Demo, KuCoin and Bitget. The application does not submit live exchange orders.

## Safety

- Live trading is hard-disabled in the application. The dashboard and API create local simulated trades only.
- Never paste API keys into chat, source files, screenshots or GitHub.
- Copy `.env.example` to `.env` on your own Windows computer. The `.env` file is ignored by Git.
- For Bybit, create the key while switched into **Demo Trading**. A Testnet key is not interchangeable. The application uses CCXT `enable_demo_trading(True)`.
- Use the minimum API permissions required for account verification. Do not enable withdrawals or transfers. Restrict by IP where practical.
- Local paper trades are stored in SQLite and do not appear in the exchange mobile app.
- Paper results are simulations, not evidence of profitability or a promise of future results.

## Windows setup

### Easy start

1. Install Python 3.10 or newer and ensure the Python launcher (`py`) is available.
2. Extract the project ZIP into a folder you control.
3. Configure the friendly local hostname once (see **Friendly HTTPS address** below).
4. Double-click `start_bot.bat`. It creates a virtual environment, installs requirements, creates `.env` if missing, generates a local HTTPS certificate if needed, and starts the dashboard.
5. Open [https://botstrategiesmodules:8000/](https://botstrategiesmodules:8000/).

### Friendly HTTPS address (one-time Windows setup)

The hostname is local to your computer; it is not a public internet domain.

1. Open Notepad **as Administrator**.
2. Open this file: `C:\Windows\System32\drivers\etc\hosts` (choose **All Files** in the file picker).
3. Add this line at the bottom and save:

   ```text
   127.0.0.1 botstrategiesmodules
   ```

4. Run `start_bot.bat` once. It creates:
   - `certs\botstrategiesmodules.crt` (local HTTPS certificate)
   - `certs\botstrategiesmodules.key` (private key; keep it on this computer)
5. To remove the browser's certificate warning, press **Win + R**, run `certmgr.msc`, open **Trusted Root Certification Authorities > Certificates**, then import `certs\botstrategiesmodules.crt` into **Current User**'s Trusted Root store. Only trust this certificate on your own computer. Restart the browser and open the HTTPS address.
6. Keep the generated private key local. Do not upload the `certs` folder or share the private key.

If Windows or your browser still reports a certificate warning, check that the certificate was imported into the Current User Trusted Root store and that the certificate was generated for the exact hostname `botstrategiesmodules`.

### Manual setup (optional)

```bat
py -m venv .venv
.venv\Scripts\activate
py -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
notepad .env
python generate_local_cert.py
python -m uvicorn bot_master:app --host 127.0.0.1 --port 8000 --ssl-keyfile certs\botstrategiesmodules.key --ssl-certfile certs\botstrategiesmodules.crt
```

Enter API credentials only in the local `.env` file. Public market data can be accessed without credentials; the connection check attempts account verification only when credentials are configured.

## Configuration

Important local settings in `.env`:

| Setting | Default | Purpose |
|---|---:|---|
| `DEFAULT_EXCHANGE` | `Bybit Demo` | Initial exchange |
| `DEFAULT_SYMBOL` | `BTC/USDT:USDT` | Initial market |
| `ACTIVE_PAIRS` | BTC, ETH, SOL USDT swaps | Scanner watchlist |
| `PAPER_CAPITAL_USDT` | `200` | Initial local paper capital |
| `FUTURES_LEVERAGE` | `7` | Default simulated leverage |
| `TARGET_RR` | `5.0` | Default target risk/reward ratio when a stop is supplied |
| `SCAN_TIMEFRAME` | `15m` | Scanner candle timeframe |
| `SCAN_INTERVAL_SECONDS` | `60` | Scanner interval |

The paper ledger applies configurable-in-code fee and slippage assumptions. Estimated liquidation is simplified and is not an exchange liquidation calculation. Funding is applied only when the exchange exposes the required funding-rate fields and the settlement timestamp is reached.

## Current functionality

- FastAPI local dashboard and JSON API.
- CCXT public market connections for Binance, Bybit Demo, KuCoin and Bitget; spot and swap market selection.
- Bybit Demo account verification when local credentials are configured.
- SQLite paper account and trade ledger, with separate exchange/symbol identity on positions.
- Configurable paper capital and simulated leverage.
- Manual local paper trades using a fetched exchange ticker price.
- Background paper-position monitoring for stop-loss, take-profit, break-even and estimated liquidation events.
- Funding settlement simulation when the exchange provides usable funding data.
- Read-only scheduled scanner for Strategy Modules I and II; signals are reported, never automatically traded.
- Dashboard API uses unavailable values when a real data provider is not configured.

## Strategy module status

| Module | Rule | Scanner status |
|---|---|---|
| I | SMA 20/200 crossover with Stochastic 3/3 confirmation | Scanned |
| II | Marubozu candle; body/range greater than 0.8 | Scanned |
| III | VWAP breakout, positive CVD and upward trend confirmation | Function and unit tests present; not connected to scanner |
| IV | Support bounce near the recent 20-candle low with open interest above the configured threshold | Function and unit tests present; not connected to scanner |

Modules III and IV are deliberately not scanned until genuine, correctly-scaled CVD and open-interest providers are connected. The application must not substitute guessed or hard-coded market-intelligence values.

## Known limitations

- The dashboard is an early implementation; some navigation sections and advanced analytics are placeholders.
- Open-interest, CVD, liquidation heatmap, footprint and large-trade data providers are not configured.
- News RSS scoring is experimental and is not a verified macro-event calendar or real-time trading pause service.
- WhatsApp delivery is not implemented. The notification module returns a clear not-configured status and sends nothing.
- The simplified paper liquidation estimate does not model exchange maintenance-margin tiers, fees, cross-margin or liquidation rules exactly.
- Background price monitoring depends on network access and exchange API availability. Gaps in polling can affect simulated fills and funding settlement accuracy.
- Live order placement is intentionally unavailable.

## Tests

Run locally from the project folder:

```bat
.venv\Scripts\python.exe -m pytest -q
```

The GitHub Actions workflow runs the test suite on pushes to the working branch and builds a clean project ZIP artifact after successful tests.

## API endpoints

- `GET /api/dashboard-data`
- `GET /api/connection-check`
- `GET /api/strategies`
- `GET /api/signals`
- `GET /api/paper-trades`
- `POST /api/switch-exchange`
- `POST /api/switch-symbol`
- `POST /api/capital`
- `POST /api/toggle` — scanner only
- `POST /api/place-trade` — local paper trade only
- `POST /api/close-paper-trade/{trade_id}` — local paper trade only
- `POST /api/scan-once` — read-only scan; no order execution

## Local address

Dashboard: [https://botstrategiesmodules:8000/](https://botstrategiesmodules:8000/). The hostname resolves locally through the Windows hosts file. HTTPS uses a self-signed certificate generated locally; trust it in Windows to avoid browser warnings. The app listens only on 127.0.0.1.
