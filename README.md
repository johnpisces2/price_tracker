# PriceTracker

PriceTracker is a PyQt6 desktop app for monitoring crypto and ETF prices, calculating technical indicators, and sending Telegram alerts when your conditions are met.

## Screenshot

![PriceTracker Screenshot](screenshot.png)

## Features

- Track supported symbols:
  - Crypto: `BTC/USDT`, `ETH/USDT`
  - Taiwan ETFs: `0050.TW`, `0056.TW`
  - US ETFs: `SPY`, `QQQ`, `DIA`, `VOO`, `IVV`
- Built-in indicators:
  - `Price`
  - `RSI`
  - `EMA1` to `EMA4`
  - `Volume`
  - `Bollinger Bands (BB Upper / BB Lower)`
- Configurable timeframe:
  - `1m`, `5m`, `15m`, `1h`, `4h`, `1d`
- Condition builder with `AND` logic
- Operators:
  - `>`
  - `<`
  - `>=`
  - `<=`
  - `==`
  - `Cross Above`
  - `Cross Below`
- Right-hand side comparison can use:
  - a fixed numeric value
  - another indicator value
- Background data refresh with manual refresh support
- Telegram bot integration with background long-poll listener
- Telegram commands:
  - `/start`
  - `/status`
  - `/condition`
- Quiet heartbeat logging:
  - successful refreshes stay silent
  - market-closed state stays silent
  - network errors are logged

## Alert Behavior

- `Update (sec)` controls how often market data is refreshed.
- Indicators are recalculated on every refresh.
- Alerts are sent only when all enabled conditions become true.
- A condition must transition from `false` to `true` before a new alert is sent.
- `Cooldown (sec)` limits how soon another alert can be sent after the previous alert.
- If a condition stays true continuously, the app does not keep spamming alerts every refresh.

## Telegram Bot Behavior

The app runs a background Telegram long-poll listener after a valid bot token is configured.

- Send `/start` to open the chat with the bot and let the app detect your private `chat_id`
- Send `/status` to receive:
  - symbol
  - timeframe
  - current price
  - RSI
  - EMA1 to EMA4
  - volume
  - Bollinger Bands
  - last update time
- Send `/condition` to receive:
  - current symbol
  - timeframe
  - configured condition count
  - enabled condition count
  - cooldown
  - all enabled monitoring conditions

## Installation

```bash
pip install -r requirements.txt
python main.py
```

## Requirements

- Python 3.13 is recommended in this repo's current setup
- See [requirements.txt](requirements.txt) for Python packages

Main dependencies:

- `PyQt6`
- `ccxt`
- `numpy`
- `pandas`
- `requests`
- `ta`
- `yfinance`

## How To Use

1. Launch the app.
2. Select a `Symbol`.
3. Choose a `Timeframe`.
4. Adjust indicator parameters if needed:
   - `EMA1`
   - `EMA2`
   - `EMA3`
   - `EMA4`
   - `RSI`
   - `BB Period`
   - `BB Std Dev`
5. Set `Update (sec)`.
6. Set `Cooldown (sec)`.
7. Enter your Telegram bot token.
8. Click `Save Settings`.
9. Click `Add Condition` and enable the conditions you want to monitor.
10. Optional: click `Manual Refresh` to fetch data immediately.

## Telegram Setup

1. Create a bot with `@BotFather`.
2. Copy the bot token.
3. Paste the token into the app's `Telegram Token` field.
4. Click `Save Settings`.
5. Open a private chat with your bot.
6. Send `/start`.
7. Wait for the app to detect and save your `chat_id`.
8. You can then:
   - click `Test`
   - use `/status`
   - use `/condition`
   - receive automatic alerts

Notes:

- If the dashboard shows `Waiting for chat_id`, send `/start` to the bot first.
- The app prefers a private chat `chat_id` when auto-detecting Telegram updates.
- Telegram listener status is shown in the dashboard.

## Condition Builder

Each condition row includes:

- `Enable`
- left metric
- operator
- right comparison mode
- right value / indicator value

Examples:

- `Price > 70000`
- `RSI < 30`
- `EMA1 Cross Above EMA2`
- `Price Cross Below BB Lower`

## Data Sources

- Crypto data: `ccxt` with Binance
- ETF / stock data: `yfinance`

Notes:

- `4h` Yahoo Finance data is resampled from `60m` candles
- If market data is unavailable, the dashboard shows `-`
- For Yahoo Finance symbols, the app treats stale data as market closed

## Configuration Files

By default:

- source run: `./settings.json`
- `--profile dev`: `./settings.dev.json`

Runtime options:

```bash
python main.py --profile myprofile
python main.py --config /path/to/custom-settings.json
```

Environment variable:

```bash
PRICE_TRACKER_CONFIG=/path/to/custom-settings.json
```

Packaged app config fallback:

- macOS: `~/Library/Application Support/PriceTracker/settings.json`
- Windows: `%APPDATA%\PriceTracker\settings.json`

## Multiple Instances

You can run multiple app instances with separate config files.

Using profiles:

```bash
python main.py --profile a
python main.py --profile b
```

Using explicit config paths:

```bash
python main.py --config /path/to/trader1.json
python main.py --config /path/to/trader2.json
```

## Build

### macOS

```bash
bash scripts/build_macos.sh all -v 1.0
```

Expected outputs:

- `dist/PriceTracker-1.0.app`
- `dist/PriceTracker-1.0.dmg`
- `dist/PriceTracker-1.0.pkg`

### Windows

```bat
scripts\build_windows.bat exe -v 1.0
```

Files in [scripts](scripts):

- `scripts/build_macos.sh`
- `scripts/build_windows.bat`
- `scripts/PriceTracker.win.spec`

## Windows Build Notes

- Use a regular CPython install for packaging.
- Avoid building with a Conda Python bootstrap environment.
- If needed, point the script to CPython explicitly:

```bat
set PRICE_TRACKER_CPYTHON=C:\Users\<your_user>\AppData\Local\Programs\Python\Python313\python.exe
scripts\build_windows.bat clean
scripts\build_windows.bat exe -v 1.0
```

Common packaging issues:

- `.build-venv was created from Conda Python`
  - clean the build venv and rebuild with CPython
- `Bootstrap CPython path is empty`
  - set `PRICE_TRACKER_CPYTHON` to a valid `python.exe`

## Recent Behavior Changes

The current app version includes:

- Telegram background long-poll instead of one-shot sync
- `/status` Telegram command
- `/condition` Telegram command
- quieter log output during normal heartbeat updates
- fixed-height condition panel to avoid layout jumping when adding rows
