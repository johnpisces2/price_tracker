import argparse
import json
import math
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


def _bootstrap_windows_qt_dll_path() -> None:
    if os.name != "nt":
        return

    base_dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            base_dirs.append(Path(meipass))
        exe_dir = Path(sys.executable).resolve().parent
        if exe_dir not in base_dirs:
            base_dirs.append(exe_dir)
        internal_dir = exe_dir / "_internal"
        if internal_dir not in base_dirs:
            base_dirs.append(internal_dir)
    base_dirs.append(Path(__file__).resolve().parent)

    existing_path = os.environ.get("PATH", "")
    path_parts = [p for p in existing_path.split(";") if p]
    normalized_parts = {p.lower() for p in path_parts}

    seen: set[str] = set()
    for base_dir in base_dirs:
        candidate_dirs = [
            base_dir,
            base_dir / "PyQt6",
            base_dir / "PyQt6" / "Qt6" / "bin",
        ]
        for dll_dir in candidate_dirs:
            if not dll_dir.is_dir():
                continue
            dll_dir_str = str(dll_dir)
            dll_key = dll_dir_str.lower()
            if dll_key in seen:
                continue
            seen.add(dll_key)

            try:
                os.add_dll_directory(dll_dir_str)
            except (AttributeError, FileNotFoundError, OSError):
                pass

            if dll_key not in normalized_parts:
                path_parts.insert(0, dll_dir_str)
                normalized_parts.add(dll_key)

        plugins_dir = base_dir / "PyQt6" / "Qt6" / "plugins"
        if plugins_dir.is_dir():
            os.environ.setdefault("QT_PLUGIN_PATH", str(plugins_dir))
            os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(plugins_dir / "platforms"))

    if path_parts:
        os.environ["PATH"] = ";".join(path_parts)


_bootstrap_windows_qt_dll_path()

import ccxt
import pandas as pd
import requests
import ta
import yfinance as yf
from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QColor, QPalette
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


CONFIG_PATH = Path("settings.json")
APP_INSTANCE_LABEL = "default"
CRYPTO_SYMBOLS = ["BTC/USDT", "ETH/USDT"]
TW_ETF_SYMBOLS = ["0050.TW", "0056.TW"]
US_ETF_SYMBOLS = ["SPY", "QQQ", "DIA", "VOO", "IVV"]
SYMBOL_OPTIONS = [*CRYPTO_SYMBOLS, *TW_ETF_SYMBOLS, *US_ETF_SYMBOLS]
METRICS = [
    ("Price", "price"),
    ("RSI", "rsi"),
    ("EMA1", "ema1"),
    ("EMA2", "ema2"),
    ("EMA3", "ema3"),
    ("EMA4", "ema4"),
    ("Volume", "volume"),
    ("BB Upper", "bb_upper"),
    ("BB Lower", "bb_lower"),
]
METRIC_NAME_TO_KEY = dict(METRICS)
RIGHT_COMPARISON_VALUE_KEY = "value"
RIGHT_COMPARISON_OPTIONS = [
    ("Value", RIGHT_COMPARISON_VALUE_KEY),
    ("RSI", "rsi"),
    ("EMA1", "ema1"),
    ("EMA2", "ema2"),
    ("EMA3", "ema3"),
    ("EMA4", "ema4"),
    ("BB Lower", "bb_lower"),
    ("BB Upper", "bb_upper"),
]
RIGHT_COMPARISON_KEYS = {key for _, key in RIGHT_COMPARISON_OPTIONS}
OPERATORS = [">", "<", ">=", "<=", "==", "Cross Above", "Cross Below"]
TIMEFRAMES = ["1d", "4h", "1h", "15m", "5m", "1m"]
TIMEFRAME_TO_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}
YF_INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "60m",
    "4h": "60m",
    "1d": "1d",
}


@dataclass
class IndicatorSettings:
    timeframe: str = "1h"
    ema1_period: int = 21
    ema2_period: int = 55
    ema3_period: int = 100
    ema4_period: int = 200
    rsi_period: int = 14
    bb_period: int = 55
    bb_std: float = 3.0


@dataclass
class AppSettings:
    symbol: str = "BTC/USDT"
    telegram_token: str = ""
    telegram_chat_id: str = ""
    update_seconds: int = 30
    cooldown_seconds: int = 600
    indicators: IndicatorSettings = field(default_factory=IndicatorSettings)
    conditions: List[dict] = field(default_factory=list)


@dataclass
class DataSnapshot:
    symbol: str
    quote_currency: str
    price: float
    prev_close: float
    rsi: float
    ema1: float
    ema2: float
    ema3: float
    ema4: float
    volume: float
    bb_upper: float
    bb_lower: float
    timestamp_ms: int
    candle_metrics: dict[str, float] = field(default_factory=dict)
    prev_candle_metrics: dict[str, float] = field(default_factory=dict)


def load_settings() -> AppSettings:
    if not CONFIG_PATH.exists():
        return AppSettings()
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        indicator_raw = raw.get("indicators", {})
        old_ema = int(indicator_raw.get("ema_period", 55))
        indicators = IndicatorSettings(
            timeframe=indicator_raw.get("timeframe", "1h"),
            ema1_period=int(indicator_raw.get("ema1_period", 21)),
            ema2_period=int(indicator_raw.get("ema2_period", old_ema)),
            ema3_period=int(indicator_raw.get("ema3_period", 100)),
            ema4_period=int(indicator_raw.get("ema4_period", 200)),
            rsi_period=int(indicator_raw.get("rsi_period", 14)),
            bb_period=int(indicator_raw.get("bb_period", 55)),
            bb_std=float(indicator_raw.get("bb_std", 3.0)),
        )
        # Migrate legacy defaults from early UI versions.
        if (
            indicators.ema2_period == 22
            and indicators.bb_period == 20
            and abs(indicators.bb_std - 2.0) < 1e-9
        ):
            indicators.ema2_period = 55
            indicators.bb_period = 55
            indicators.bb_std = 3.0
        symbol = str(raw.get("symbol", "BTC/USDT"))
        if symbol not in SYMBOL_OPTIONS:
            symbol = SYMBOL_OPTIONS[0]
        return AppSettings(
            symbol=symbol,
            telegram_token=str(raw.get("telegram_token", "")),
            telegram_chat_id=str(raw.get("telegram_chat_id", "")),
            update_seconds=int(raw.get("update_seconds", 30)),
            cooldown_seconds=int(raw.get("cooldown_seconds", 600)),
            indicators=indicators,
            conditions=list(raw.get("conditions", [])),
        )
    except Exception:
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    payload = asdict(settings)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _sanitize_profile_name(name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    return normalized or "default"


def _frozen_local_config_dir() -> Path:
    exe = Path(sys.executable).resolve()
    # macOS app bundle: .../AppName.app/Contents/MacOS/AppName
    if (
        sys.platform == "darwin"
        and exe.parent.name == "MacOS"
        and exe.parent.parent.name == "Contents"
        and exe.parent.parent.parent.suffix == ".app"
    ):
        return exe.parent.parent.parent.parent
    # Windows/Linux frozen binary: use executable directory.
    return exe.parent


def _user_fallback_config_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PriceTracker"
    if os.name == "nt":
        appdata = os.getenv("APPDATA", "").strip()
        if appdata:
            return Path(appdata) / "PriceTracker"
        return Path.home() / "AppData" / "Roaming" / "PriceTracker"
    xdg = os.getenv("XDG_CONFIG_HOME", "").strip()
    if xdg:
        return Path(xdg) / "PriceTracker"
    return Path.home() / ".config" / "PriceTracker"


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".pt_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _default_config_path() -> Path:
    # Prefer local folder for packaged app; fallback to user profile dir if not writable.
    if getattr(sys, "frozen", False):
        local_dir = _frozen_local_config_dir()
        if _is_writable_dir(local_dir):
            return local_dir / "settings.json"
        return _user_fallback_config_dir() / "settings.json"
    return Path("settings.json")


def resolve_runtime_config(argv: List[str]) -> Tuple[Path, str, List[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", type=str, default="")
    parser.add_argument("--profile", type=str, default="")
    args, remaining = parser.parse_known_args(argv)
    default_cfg = _default_config_path()
    default_dir = default_cfg.parent

    env_config = os.getenv("PRICE_TRACKER_CONFIG", "").strip()
    if args.config.strip():
        config_path = Path(args.config.strip()).expanduser()
        label = config_path.stem
    elif args.profile.strip():
        profile = _sanitize_profile_name(args.profile)
        config_path = default_dir / f"settings.{profile}.json"
        label = profile
    elif env_config:
        config_path = Path(env_config).expanduser()
        label = config_path.stem
    else:
        config_path = default_cfg
        label = "default"

    return config_path, label, remaining


class TelegramService:
    REQUEST_TIMEOUT_SEC = 10
    MAX_RETRIES = 2

    def __init__(self) -> None:
        self.token = ""
        self.chat_id = ""

    def set_credentials(self, token: str, chat_id: str) -> None:
        self.token = token.strip()
        self.chat_id = chat_id.strip()

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def _request_api(
        self,
        http_method: str,
        api_method: str,
        *,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
        timeout_sec: Optional[int] = None,
    ) -> Tuple[Optional[requests.Response], dict, str]:
        timeout = timeout_sec or self.REQUEST_TIMEOUT_SEC
        last_error = "Telegram request failed"
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                if http_method.upper() == "GET":
                    response = requests.get(self._api_url(api_method), params=params, timeout=timeout)
                else:
                    response = requests.post(self._api_url(api_method), data=data, timeout=timeout)
                payload = (
                    response.json()
                    if response.headers.get("content-type", "").startswith("application/json")
                    else {}
                )
                return response, payload, ""
            except requests.exceptions.Timeout:
                last_error = "Network timeout while connecting to Telegram"
            except requests.exceptions.ConnectionError:
                last_error = "Network connection failed to Telegram"
            except requests.exceptions.RequestException:
                last_error = "Telegram request failed"
            if attempt < self.MAX_RETRIES:
                time.sleep(0.5 * (attempt + 1))
        return None, {}, last_error

    @staticmethod
    def _extract_chat_id(update: dict) -> Optional[int]:
        # Handle common update payload types from Telegram.
        for key in (
            "message",
            "edited_message",
            "channel_post",
            "edited_channel_post",
            "my_chat_member",
            "chat_member",
            "business_message",
            "edited_business_message",
        ):
            msg = update.get(key)
            if isinstance(msg, dict):
                chat = msg.get("chat", {})
                if isinstance(chat, dict) and "id" in chat:
                    return int(chat["id"])

        callback = update.get("callback_query")
        if isinstance(callback, dict):
            msg = callback.get("message", {})
            if isinstance(msg, dict):
                chat = msg.get("chat", {})
                if isinstance(chat, dict) and "id" in chat:
                    return int(chat["id"])
        return None

    def resolve_chat_id(self, last_update_id: int = 0) -> Tuple[str, int, str]:
        if not self.token:
            return self.chat_id, last_update_id, "Missing token"
        bot_username = ""
        me_r, me_payload, me_err = self._request_api("GET", "getMe")
        if me_err:
            return self.chat_id, last_update_id, me_err
        if me_r and me_r.ok and me_payload.get("ok", False):
            bot_username = str(me_payload.get("result", {}).get("username", "")).strip()
        else:
            return self.chat_id, last_update_id, str(me_payload.get("description", "Token invalid"))

        params = {"timeout": 0, "limit": 100}
        if last_update_id > 0:
            params["offset"] = last_update_id + 1

        r, payload, err = self._request_api("GET", "getUpdates", params=params)
        if err:
            return self.chat_id, last_update_id, err
        if not (r and r.ok and payload.get("ok", False)):
            desc = str(payload.get("description", "Failed to fetch updates"))
            lower_desc = desc.lower()
            if "webhook" in lower_desc and "getupdates" in lower_desc:
                _, delete_payload, delete_err = self._request_api(
                    "POST",
                    "deleteWebhook",
                    data={"drop_pending_updates": "false"},
                )
                if delete_err:
                    return self.chat_id, last_update_id, f"{desc}; deleteWebhook failed: {delete_err}"
                if not bool(delete_payload.get("ok", False)):
                    delete_desc = str(delete_payload.get("description", "deleteWebhook failed"))
                    return self.chat_id, last_update_id, f"{desc}; {delete_desc}"
                r, payload, err = self._request_api("GET", "getUpdates", params=params)
                if err:
                    return self.chat_id, last_update_id, f"Webhook cleared but getUpdates failed: {err}"
                if not (r and r.ok and payload.get("ok", False)):
                    retry_desc = str(payload.get("description", "Failed to fetch updates"))
                    return self.chat_id, last_update_id, f"Webhook cleared but getUpdates failed: {retry_desc}"
                desc = "Webhook was active and has been cleared"
            else:
                return self.chat_id, last_update_id, desc

        updates = payload.get("result", [])
        newest_id = last_update_id
        resolved_chat_id: Optional[str] = None
        resolved_private_chat_id: Optional[str] = None

        for update in updates:
            update_id = int(update.get("update_id", newest_id))
            newest_id = max(newest_id, update_id)
            chat_id = self._extract_chat_id(update)
            if chat_id is not None:
                resolved_chat_id = str(chat_id)
                if chat_id > 0:
                    resolved_private_chat_id = str(chat_id)

        chosen_chat_id = resolved_private_chat_id or resolved_chat_id
        if chosen_chat_id:
            self.chat_id = str(chosen_chat_id)
            return str(chosen_chat_id), newest_id, f"Auto detected chat_id: {chosen_chat_id} from {len(updates)} updates"
        if self.chat_id:
            return self.chat_id, newest_id, f"No new updates ({len(updates)}), using existing chat_id"

        # Fallback: recover from older unconfirmed updates when offset has moved.
        if last_update_id > 0:
            r2, payload2, err2 = self._request_api("GET", "getUpdates", params={"timeout": 0, "limit": 100})
            if not err2 and r2 and r2.ok and payload2.get("ok", False):
                legacy_updates = payload2.get("result", [])
                legacy_chat: Optional[str] = None
                legacy_private_chat: Optional[str] = None
                for update in legacy_updates:
                    chat_id = self._extract_chat_id(update)
                    if chat_id is not None:
                        legacy_chat = str(chat_id)
                        if chat_id > 0:
                            legacy_private_chat = str(chat_id)
                recovered = legacy_private_chat or legacy_chat
                if recovered:
                    self.chat_id = recovered
                    return recovered, newest_id, f"Recovered chat_id from history: {recovered}"

        webhook_note = ""
        wr, wpayload, werr = self._request_api("GET", "getWebhookInfo")
        if not werr and wr and wr.ok and wpayload.get("ok", False):
            info = wpayload.get("result", {})
            if isinstance(info, dict):
                webhook_url = str(info.get("url", "")).strip()
                pending_cnt = int(info.get("pending_update_count", 0) or 0)
                last_err = str(info.get("last_error_message", "")).strip()
                if webhook_url:
                    webhook_note = "; webhook is active"
                elif pending_cnt > 0:
                    webhook_note = f"; pending updates: {pending_cnt}"
                if last_err:
                    webhook_note += f"; webhook error: {last_err}"
        bot_hint = f"@{bot_username}" if bot_username else "the bot"
        return "", newest_id, f"Waiting for chat_id (open {bot_hint} in private chat and send /start){webhook_note}"

    def validate(self) -> Tuple[bool, str]:
        if not self.token:
            return False, "Missing token"
        if not self.chat_id:
            return False, "Waiting for chat_id (send /start to bot)"
        r, payload, err = self._request_api("GET", "getMe")
        if err:
            return False, err
        if not (r and r.ok and payload.get("ok", False)):
            return False, str(payload.get("description", "Token invalid"))

        action, action_payload, err = self._request_api(
            "POST",
            "sendChatAction",
            data={"chat_id": self.chat_id, "action": "typing"},
        )
        if err:
            return False, err
        if not (action and action.ok and action_payload.get("ok", False)):
            return False, str(action_payload.get("description", "Chat ID invalid or bot not started"))
        return True, "Connected"

    def send_message(self, text: str) -> Tuple[bool, str]:
        if not self.token or not self.chat_id:
            return False, "Missing token or chat ID"
        r, payload, err = self._request_api(
            "POST",
            "sendMessage",
            data={"chat_id": self.chat_id, "text": text},
        )
        if err:
            return False, err
        if r and r.ok and payload.get("ok", False):
            return True, "Message sent"
        return False, str(payload.get("description", "Telegram API error"))


class MarketDataService:
    def __init__(self) -> None:
        self.exchange = ccxt.binance({"enableRateLimit": True})
        self._yf_tickers: dict[str, yf.Ticker] = {}

    def fetch_snapshot(self, symbol: str, settings: IndicatorSettings) -> DataSnapshot:
        if symbol in CRYPTO_SYMBOLS:
            return self._fetch_crypto_snapshot(symbol, settings)
        return self._fetch_yf_snapshot(symbol, settings)

    def _fetch_crypto_snapshot(self, symbol: str, settings: IndicatorSettings) -> DataSnapshot:
        max_period = max(
            settings.ema1_period,
            settings.ema2_period,
            settings.ema3_period,
            settings.ema4_period,
            settings.rsi_period,
            settings.bb_period,
        )
        candles = self.exchange.fetch_ohlcv(
            symbol,
            timeframe=settings.timeframe,
            limit=max(100, max_period * 4),
        )
        if len(candles) < max_period + 5:
            raise RuntimeError("Not enough candle data")

        df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])
        close = df["close"]
        volume_series = df["volume"]

        ema1_series = ta.trend.EMAIndicator(close, window=settings.ema1_period).ema_indicator()
        ema2_series = ta.trend.EMAIndicator(close, window=settings.ema2_period).ema_indicator()
        ema3_series = ta.trend.EMAIndicator(close, window=settings.ema3_period).ema_indicator()
        ema4_series = ta.trend.EMAIndicator(close, window=settings.ema4_period).ema_indicator()
        rsi_series = ta.momentum.RSIIndicator(close, window=settings.rsi_period).rsi()
        bb = ta.volatility.BollingerBands(
            close,
            window=settings.bb_period,
            window_dev=settings.bb_std,
        )
        bb_upper_series = bb.bollinger_hband()
        bb_lower_series = bb.bollinger_lband()

        candle_metrics = {
            "price": float(close.iloc[-1]),
            "rsi": float(rsi_series.iloc[-1]),
            "ema1": float(ema1_series.iloc[-1]),
            "ema2": float(ema2_series.iloc[-1]),
            "ema3": float(ema3_series.iloc[-1]),
            "ema4": float(ema4_series.iloc[-1]),
            "volume": float(volume_series.iloc[-1]),
            "bb_upper": float(bb_upper_series.iloc[-1]),
            "bb_lower": float(bb_lower_series.iloc[-1]),
        }
        prev_candle_metrics = {
            "price": float(close.iloc[-2]),
            "rsi": float(rsi_series.iloc[-2]),
            "ema1": float(ema1_series.iloc[-2]),
            "ema2": float(ema2_series.iloc[-2]),
            "ema3": float(ema3_series.iloc[-2]),
            "ema4": float(ema4_series.iloc[-2]),
            "volume": float(volume_series.iloc[-2]),
            "bb_upper": float(bb_upper_series.iloc[-2]),
            "bb_lower": float(bb_lower_series.iloc[-2]),
        }

        ticker = self.exchange.fetch_ticker(symbol)
        price = float(ticker.get("last") or close.iloc[-1])
        prev_close = float(close.iloc[-2])
        timestamp_ms = int(ticker.get("timestamp") or int(df["ts"].iloc[-1]))
        rsi = candle_metrics["rsi"]
        ema1 = candle_metrics["ema1"]
        ema2 = candle_metrics["ema2"]
        ema3 = candle_metrics["ema3"]
        ema4 = candle_metrics["ema4"]
        volume = candle_metrics["volume"]
        bb_upper = candle_metrics["bb_upper"]
        bb_lower = candle_metrics["bb_lower"]

        values = [
            price,
            prev_close,
            *candle_metrics.values(),
            *prev_candle_metrics.values(),
        ]
        if any(math.isnan(float(v)) for v in values):
            raise RuntimeError("Indicator calculation returned NaN")

        return DataSnapshot(
            symbol=symbol,
            quote_currency="USDT",
            price=price,
            prev_close=prev_close,
            rsi=float(rsi),
            ema1=float(ema1),
            ema2=float(ema2),
            ema3=float(ema3),
            ema4=float(ema4),
            volume=volume,
            bb_upper=float(bb_upper),
            bb_lower=float(bb_lower),
            timestamp_ms=timestamp_ms,
            candle_metrics=candle_metrics,
            prev_candle_metrics=prev_candle_metrics,
        )

    def _fetch_yf_snapshot(self, symbol: str, settings: IndicatorSettings) -> DataSnapshot:
        ticker = self._get_yf_ticker(symbol)
        self._ensure_market_open(ticker)

        max_period = max(
            settings.ema1_period,
            settings.ema2_period,
            settings.ema3_period,
            settings.ema4_period,
            settings.rsi_period,
            settings.bb_period,
        )
        interval = YF_INTERVAL_MAP.get(settings.timeframe, "1d")
        history = ticker.history(
            period=self._history_period(interval),
            interval=interval,
            auto_adjust=False,
            prepost=False,
        )
        df = self._normalize_yf_history(history)
        if settings.timeframe == "4h":
            df = self._resample_4h(df)
        if len(df) < max_period + 5:
            raise RuntimeError("Not enough candle data")

        close = df["close"]
        volume_series = df["volume"]
        ema1_series = ta.trend.EMAIndicator(close, window=settings.ema1_period).ema_indicator()
        ema2_series = ta.trend.EMAIndicator(close, window=settings.ema2_period).ema_indicator()
        ema3_series = ta.trend.EMAIndicator(close, window=settings.ema3_period).ema_indicator()
        ema4_series = ta.trend.EMAIndicator(close, window=settings.ema4_period).ema_indicator()
        rsi_series = ta.momentum.RSIIndicator(close, window=settings.rsi_period).rsi()
        bb = ta.volatility.BollingerBands(
            close,
            window=settings.bb_period,
            window_dev=settings.bb_std,
        )
        bb_upper_series = bb.bollinger_hband()
        bb_lower_series = bb.bollinger_lband()
        candle_metrics = {
            "price": float(close.iloc[-1]),
            "rsi": float(rsi_series.iloc[-1]),
            "ema1": float(ema1_series.iloc[-1]),
            "ema2": float(ema2_series.iloc[-1]),
            "ema3": float(ema3_series.iloc[-1]),
            "ema4": float(ema4_series.iloc[-1]),
            "volume": float(volume_series.iloc[-1]),
            "bb_upper": float(bb_upper_series.iloc[-1]),
            "bb_lower": float(bb_lower_series.iloc[-1]),
        }
        prev_candle_metrics = {
            "price": float(close.iloc[-2]),
            "rsi": float(rsi_series.iloc[-2]),
            "ema1": float(ema1_series.iloc[-2]),
            "ema2": float(ema2_series.iloc[-2]),
            "ema3": float(ema3_series.iloc[-2]),
            "ema4": float(ema4_series.iloc[-2]),
            "volume": float(volume_series.iloc[-2]),
            "bb_upper": float(bb_upper_series.iloc[-2]),
            "bb_lower": float(bb_lower_series.iloc[-2]),
        }

        price = float(close.iloc[-1])
        try:
            fast_info = ticker.fast_info
            last_price = fast_info.get("lastPrice") if hasattr(fast_info, "get") else None
            if last_price is not None:
                price = float(last_price)
        except Exception:
            pass

        prev_close = float(close.iloc[-2])
        last_ts = pd.Timestamp(df.index[-1])
        if last_ts.tzinfo is None:
            last_ts = last_ts.tz_localize("UTC")
        timestamp_ms = int(last_ts.timestamp() * 1000)
        quote_currency = "TWD" if symbol in TW_ETF_SYMBOLS else "USD"
        rsi = candle_metrics["rsi"]
        ema1 = candle_metrics["ema1"]
        ema2 = candle_metrics["ema2"]
        ema3 = candle_metrics["ema3"]
        ema4 = candle_metrics["ema4"]
        volume = candle_metrics["volume"]
        bb_upper = candle_metrics["bb_upper"]
        bb_lower = candle_metrics["bb_lower"]

        values = [
            price,
            prev_close,
            *candle_metrics.values(),
            *prev_candle_metrics.values(),
        ]
        if any(math.isnan(float(v)) for v in values):
            raise RuntimeError("Indicator calculation returned NaN")

        return DataSnapshot(
            symbol=symbol,
            quote_currency=quote_currency,
            price=price,
            prev_close=prev_close,
            rsi=float(rsi),
            ema1=float(ema1),
            ema2=float(ema2),
            ema3=float(ema3),
            ema4=float(ema4),
            volume=volume,
            bb_upper=float(bb_upper),
            bb_lower=float(bb_lower),
            timestamp_ms=timestamp_ms,
            candle_metrics=candle_metrics,
            prev_candle_metrics=prev_candle_metrics,
        )

    def _get_yf_ticker(self, symbol: str) -> yf.Ticker:
        ticker = self._yf_tickers.get(symbol)
        if ticker is None:
            ticker = yf.Ticker(symbol)
            self._yf_tickers[symbol] = ticker
        return ticker

    @staticmethod
    def _history_period(interval: str) -> str:
        if interval == "1m":
            return "7d"
        if interval in ("5m", "15m"):
            return "60d"
        if interval == "60m":
            return "730d"
        return "10y"

    @staticmethod
    def _normalize_yf_history(history: pd.DataFrame) -> pd.DataFrame:
        if history is None or history.empty:
            raise RuntimeError("No data source (market closed)")
        df = history.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        ).copy()
        for col in ("open", "high", "low", "close", "volume"):
            if col not in df.columns:
                if col == "volume":
                    df[col] = 0.0
                else:
                    raise RuntimeError("No data source (market closed)")
        df = df[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
        if df.empty:
            raise RuntimeError("No data source (market closed)")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
        return df

    @staticmethod
    def _resample_4h(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            raise RuntimeError("No data source (market closed)")
        out = df.resample("4h", label="right", closed="right").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        out = out.dropna(subset=["close"])
        if out.empty:
            raise RuntimeError("No data source (market closed)")
        return out

    @staticmethod
    def _ensure_market_open(ticker: yf.Ticker) -> None:
        minute_df = ticker.history(period="2d", interval="1m", auto_adjust=False, prepost=False)
        if minute_df is None or minute_df.empty:
            raise RuntimeError("No data source (market closed)")
        last_ts = pd.Timestamp(minute_df.index[-1])
        if last_ts.tzinfo is None:
            last_ts = last_ts.tz_localize("UTC")
        now = pd.Timestamp.now(tz=last_ts.tz)
        if (now - last_ts).total_seconds() > 45 * 60:
            raise RuntimeError("No data source (market closed)")


class FetchWorker(QThread):
    success = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, service: MarketDataService, symbol: str, indicator_settings: IndicatorSettings):
        super().__init__()
        self.service = service
        self.symbol = symbol
        self.indicator_settings = indicator_settings

    def run(self) -> None:
        try:
            snapshot = self.service.fetch_snapshot(self.symbol, self.indicator_settings)
            self.success.emit(snapshot)
        except Exception as exc:
            self.failed.emit(str(exc))


class TelegramSyncWorker(QThread):
    success = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, token: str, chat_id: str, last_update_id: int):
        super().__init__()
        self.token = token.strip()
        self.chat_id = chat_id.strip()
        self.last_update_id = last_update_id

    def run(self) -> None:
        try:
            service = TelegramService()
            service.set_credentials(self.token, self.chat_id)
            resolved_chat_id, new_last_update_id, note = service.resolve_chat_id(self.last_update_id)
            if resolved_chat_id:
                service.set_credentials(self.token, resolved_chat_id)
            ok, msg = service.validate()
            self.success.emit(
                {
                    "ok": ok,
                    "status": msg,
                    "chat_id": resolved_chat_id or self.chat_id,
                    "last_update_id": new_last_update_id,
                    "note": note,
                }
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class TelegramSendWorker(QThread):
    success = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, token: str, chat_id: str, text: str, context: str):
        super().__init__()
        self.token = token.strip()
        self.chat_id = chat_id.strip()
        self.text = text
        self.context = context

    def run(self) -> None:
        try:
            service = TelegramService()
            service.set_credentials(self.token, self.chat_id)
            ok, msg = service.send_message(self.text)
            self.success.emit({"ok": ok, "msg": msg, "context": self.context})
        except Exception as exc:
            self.failed.emit(str(exc))


class ConditionRow(QWidget):
    remove_requested = pyqtSignal(object)

    def __init__(self, data: Optional[dict] = None):
        super().__init__()
        self.latest_snapshot: Optional[DataSnapshot] = None
        self.enabled = QCheckBox("Enable")
        self.left_metric = QComboBox()
        self.left_metric.addItems([name for name, _ in METRICS])
        self.operator = QComboBox()
        self.operator.addItems(OPERATORS)
        self.right_mode = QComboBox()
        for mode_name, mode_key in RIGHT_COMPARISON_OPTIONS:
            self.right_mode.addItem(mode_name, mode_key)
        self.right_value = QDoubleSpinBox()
        self.right_value.setRange(-1_000_000_000, 1_000_000_000)
        self.right_value.setDecimals(1)
        self.right_value.setValue(0.0)
        self.right_value.setSingleStep(0.1)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))

        layout = QHBoxLayout()
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)
        self.left_metric.setFixedWidth(140)
        self.operator.setFixedWidth(115)
        self.right_mode.setFixedWidth(120)
        self.right_value.setFixedWidth(150)
        self.remove_btn.setFixedWidth(100)
        layout.addWidget(self.enabled)
        layout.addWidget(self.left_metric)
        layout.addWidget(self.operator)
        layout.addWidget(self.right_mode)
        layout.addWidget(self.right_value)
        layout.addWidget(self.remove_btn)
        layout.addStretch(1)
        self.setLayout(layout)
        self.right_mode.currentIndexChanged.connect(self._on_right_mode_changed)
        self._on_right_mode_changed()

        if data:
            self.from_dict(data)

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled.isChecked(),
            "left_metric": self.left_metric.currentText(),
            "operator": self.operator.currentText(),
            "right_mode": self._current_right_mode(),
            "right_value": self.right_value.value(),
        }

    def from_dict(self, data: dict) -> None:
        self.enabled.setChecked(bool(data.get("enabled", False)))
        self.left_metric.setCurrentText(str(data.get("left_metric", "Price")))
        self.operator.setCurrentText(str(data.get("operator", ">")))
        self._set_right_mode(self._normalize_right_mode(data.get("right_mode", RIGHT_COMPARISON_VALUE_KEY)))
        self.right_value.setValue(float(data.get("right_value", 0.0)))
        self._on_right_mode_changed()

    def description(self) -> str:
        if self._current_right_mode() == RIGHT_COMPARISON_VALUE_KEY:
            right_text = f"{self.right_value.value():.1f}"
        else:
            right_text = self.right_mode.currentText()
        return f"{self.left_metric.currentText()} {self.operator.currentText()} {right_text}"

    def is_enabled(self) -> bool:
        return self.enabled.isChecked()

    @staticmethod
    def _metric_key(metric_name: str) -> str:
        key = METRIC_NAME_TO_KEY.get(metric_name)
        if not key:
            raise ValueError(f"Unknown metric: {metric_name}")
        return key

    @staticmethod
    def _metric_value_by_key(snapshot: DataSnapshot, metric_key: str) -> float:
        if not hasattr(snapshot, metric_key):
            raise ValueError(f"Unknown metric key: {metric_key}")
        return float(getattr(snapshot, metric_key))

    @staticmethod
    def _normalize_right_mode(raw: object) -> str:
        text = str(raw or "").strip()
        if not text:
            return RIGHT_COMPARISON_VALUE_KEY
        if text.lower() == RIGHT_COMPARISON_VALUE_KEY or text.lower() == "value":
            return RIGHT_COMPARISON_VALUE_KEY
        if text in RIGHT_COMPARISON_KEYS:
            return text
        metric_key = METRIC_NAME_TO_KEY.get(text)
        if metric_key in RIGHT_COMPARISON_KEYS:
            return metric_key
        return RIGHT_COMPARISON_VALUE_KEY

    def _set_right_mode(self, mode_key: str) -> None:
        for idx in range(self.right_mode.count()):
            if self.right_mode.itemData(idx) == mode_key:
                self.right_mode.setCurrentIndex(idx)
                return
        self.right_mode.setCurrentIndex(0)

    def _current_right_mode(self) -> str:
        mode_key = self.right_mode.currentData()
        if isinstance(mode_key, str):
            return mode_key
        return RIGHT_COMPARISON_VALUE_KEY

    def _on_right_mode_changed(self) -> None:
        self._refresh_right_display()

    def set_snapshot(self, snapshot: Optional[DataSnapshot]) -> None:
        self.latest_snapshot = snapshot
        self._refresh_right_display()

    def _refresh_right_display(self) -> None:
        use_fixed_value = self._current_right_mode() == RIGHT_COMPARISON_VALUE_KEY
        self.right_value.setReadOnly(not use_fixed_value)
        self.right_value.setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.UpDownArrows
            if use_fixed_value
            else QAbstractSpinBox.ButtonSymbols.NoButtons
        )
        if use_fixed_value:
            return
        if self.latest_snapshot is None:
            prev_block = self.right_value.blockSignals(True)
            self.right_value.setValue(0.0)
            self.right_value.blockSignals(prev_block)
            return
        try:
            value = self._metric_value_by_key(self.latest_snapshot, self._current_right_mode())
        except Exception:
            return
        prev_block = self.right_value.blockSignals(True)
        self.right_value.setValue(value)
        self.right_value.blockSignals(prev_block)

    @classmethod
    def _cross_pair(
        cls,
        current: DataSnapshot,
        previous: Optional[DataSnapshot],
        metric_key: str,
        current_value: float,
    ) -> Optional[Tuple[float, float]]:
        if metric_key in current.prev_candle_metrics and metric_key in current.candle_metrics:
            return float(current.prev_candle_metrics[metric_key]), float(current.candle_metrics[metric_key])
        if previous is None:
            return None
        return cls._metric_value_by_key(previous, metric_key), current_value

    def evaluate(self, current: DataSnapshot, previous: Optional[DataSnapshot]) -> bool:
        metric_name = self.left_metric.currentText()
        left_key = self._metric_key(metric_name)
        left = self._metric_value_by_key(current, left_key)
        right_mode = self._current_right_mode()
        if right_mode == RIGHT_COMPARISON_VALUE_KEY:
            right = self.right_value.value()
        else:
            right = self._metric_value_by_key(current, right_mode)
        op = self.operator.currentText()

        if op == ">":
            return left > right
        if op == "<":
            return left < right
        if op == ">=":
            return left >= right
        if op == "<=":
            return left <= right
        if op == "==":
            return abs(left - right) < 1e-10
        left_pair = self._cross_pair(current, previous, left_key, left)
        if left_pair is None:
            return False
        prev_left, candle_left = left_pair

        if right_mode == RIGHT_COMPARISON_VALUE_KEY:
            prev_right, candle_right = right, right
        else:
            right_pair = self._cross_pair(current, previous, right_mode, right)
            if right_pair is None:
                return False
            prev_right, candle_right = right_pair

        if op == "Cross Above":
            return prev_left <= prev_right and candle_left > candle_right
        if op == "Cross Below":
            return prev_left >= prev_right and candle_left < candle_right
        return False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        title = "Price Tracker"
        if APP_INSTANCE_LABEL != "default":
            title = f"{title} [{APP_INSTANCE_LABEL}]"
        self.setWindowTitle(title)
        self.market_service = MarketDataService()
        self.telegram_service = TelegramService()
        self.current_snapshot: Optional[DataSnapshot] = None
        self.previous_snapshot: Optional[DataSnapshot] = None
        self.last_condition_state = False
        self.last_alert_ts = 0.0
        self.fetch_in_progress = False
        self.fetch_worker: Optional[FetchWorker] = None
        self.telegram_sync_in_progress = False
        self.telegram_sync_worker: Optional[TelegramSyncWorker] = None
        self.telegram_send_workers: List[TelegramSendWorker] = []
        self.telegram_last_update_id = 0
        self.last_telegram_status_log = ""
        self.telegram_chat_id = ""
        self.condition_rows: List[ConditionRow] = []

        self._build_ui()
        self._load_from_settings()
        self._connect_signals()
        self._start_timer()
        if self.token_input.text().strip():
            self._sync_telegram_once()
        else:
            self._update_telegram_status()
        self.refresh_data()

    def _build_ui(self) -> None:
        root = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        self.setStyleSheet(
            """
            QWidget {
                font-size: 13px;
            }
            QGroupBox {
                border: 1px solid #5a5a5a;
                border-radius: 6px;
                margin-top: 7px;
                padding-top: 7px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPushButton {
                min-height: 24px;
                padding: 2px 6px;
            }
            QSpinBox::up-button, QSpinBox::down-button,
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
                width: 14px;
            }
            QTextEdit {
                border: 1px solid #4f4f4f;
            }
            """
        )

        def db_key_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setStyleSheet("font-weight: 700;")
            return label

        dashboard = QGroupBox("Dashboard")
        db_layout = QGridLayout()
        db_layout.setHorizontalSpacing(8)
        db_layout.setVerticalSpacing(4)
        db_layout.setContentsMargins(8, 6, 8, 8)
        self.price_title_label = QLabel("BTC/USDT Price")
        self.price_label = QLabel("-")
        self.price_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rsi_label = QLabel("-")
        self.ema1_label = QLabel("-")
        self.ema2_label = QLabel("-")
        self.ema3_label = QLabel("-")
        self.ema4_label = QLabel("-")
        self.volume_label = QLabel("-")
        self.bb_label = QLabel("-")
        self.updated_at_label = QLabel("-")
        self.telegram_status_label = QLabel("Disconnected")
        self.telegram_status_label.setStyleSheet("color: white; background: #8b0000; padding: 4px 8px;")
        self.telegram_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.telegram_status_label.setMinimumHeight(22)
        self.price_title_label.setStyleSheet("font-weight: 700;")
        self._set_price_trend_style(0)

        for value_label in (
            self.rsi_label,
            self.ema1_label,
            self.ema2_label,
            self.ema3_label,
            self.ema4_label,
            self.volume_label,
            self.bb_label,
        ):
            value_label.setStyleSheet("font-weight: 600;")

        db_layout.addWidget(self.price_title_label, 0, 0)
        db_layout.addWidget(self.price_label, 0, 1, 1, 7)

        db_layout.addWidget(db_key_label("EMA1"), 1, 0)
        db_layout.addWidget(self.ema1_label, 1, 1)
        db_layout.addWidget(db_key_label("RSI"), 1, 4)
        db_layout.addWidget(self.rsi_label, 1, 5)

        db_layout.addWidget(db_key_label("EMA2"), 2, 0)
        db_layout.addWidget(self.ema2_label, 2, 1)
        db_layout.addWidget(db_key_label("Volume"), 2, 4)
        db_layout.addWidget(self.volume_label, 2, 5)

        db_layout.addWidget(db_key_label("EMA3"), 3, 0)
        db_layout.addWidget(self.ema3_label, 3, 1)
        db_layout.addWidget(db_key_label("Bollinger Bands (BB)"), 3, 4)
        db_layout.addWidget(self.bb_label, 3, 5, 1, 3)

        db_layout.addWidget(db_key_label("EMA4"), 4, 0)
        db_layout.addWidget(self.ema4_label, 4, 1)
        db_layout.addWidget(db_key_label("Update Time"), 4, 4)
        db_layout.addWidget(self.updated_at_label, 4, 5, 1, 3)

        db_layout.addWidget(db_key_label("Telegram"), 5, 0)
        db_layout.addWidget(self.telegram_status_label, 5, 1, 1, 7)
        self.refresh_btn = QPushButton("Manual Refresh")
        db_layout.addWidget(self.refresh_btn, 6, 0, 1, 8)
        db_layout.setColumnMinimumWidth(0, 90)
        db_layout.setColumnMinimumWidth(4, 150)
        db_layout.setColumnStretch(1, 1)
        db_layout.setColumnStretch(3, 1)
        db_layout.setColumnStretch(5, 1)
        db_layout.setColumnStretch(7, 1)
        dashboard.setLayout(db_layout)
        dashboard.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        settings_box = QGroupBox("Settings")
        settings_layout = QGridLayout()
        settings_layout.setHorizontalSpacing(10)
        settings_layout.setVerticalSpacing(4)
        settings_layout.setContentsMargins(8, 6, 8, 2)
        self.symbol_input = QComboBox()
        self.symbol_input.addItems(SYMBOL_OPTIONS)
        self.symbol_input.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.symbol_input.setMinimumContentsLength(10)
        self.symbol_input.setMinimumWidth(150)
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("Telegram bot token")
        self.token_input.setFixedWidth(300)
        self.token_input.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.update_sec_input = QSpinBox()
        self.update_sec_input.setRange(5, 3600)
        self.update_sec_input.setValue(30)
        self.cooldown_input = QSpinBox()
        self.cooldown_input.setRange(0, 86400)
        self.cooldown_input.setValue(600)
        self.timeframe_input = QComboBox()
        self.timeframe_input.addItems(TIMEFRAMES)
        self.timeframe_input.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.timeframe_input.setMinimumContentsLength(6)
        self.timeframe_input.setMinimumWidth(150)
        self.ema1_input = QSpinBox()
        self.ema1_input.setRange(2, 500)
        self.ema1_input.setValue(21)
        self.ema2_input = QSpinBox()
        self.ema2_input.setRange(2, 500)
        self.ema2_input.setValue(55)
        self.ema3_input = QSpinBox()
        self.ema3_input.setRange(2, 500)
        self.ema3_input.setValue(100)
        self.ema4_input = QSpinBox()
        self.ema4_input.setRange(2, 500)
        self.ema4_input.setValue(200)
        self.rsi_input = QSpinBox()
        self.rsi_input.setRange(2, 500)
        self.rsi_input.setValue(14)
        self.bb_period_input = QSpinBox()
        self.bb_period_input.setRange(2, 500)
        self.bb_period_input.setValue(55)
        self.bb_std_input = QDoubleSpinBox()
        self.bb_std_input.setRange(0.5, 10.0)
        self.bb_std_input.setValue(3.0)
        self.bb_std_input.setSingleStep(0.1)
        self.bb_std_input.setDecimals(1)

        setting_field_w = 140
        for spin in (
            self.update_sec_input,
            self.cooldown_input,
            self.ema1_input,
            self.ema2_input,
            self.ema3_input,
            self.ema4_input,
            self.rsi_input,
            self.bb_period_input,
            self.bb_std_input,
        ):
            spin.setMinimumWidth(setting_field_w)

        settings_layout.addWidget(QLabel("Symbol"), 0, 0)
        settings_layout.addWidget(self.symbol_input, 0, 1)
        settings_layout.addWidget(QLabel("Update (sec)"), 0, 3)
        settings_layout.addWidget(self.update_sec_input, 0, 4)

        settings_layout.addWidget(QLabel("Timeframe"), 1, 0)
        settings_layout.addWidget(self.timeframe_input, 1, 1)
        settings_layout.addWidget(QLabel("Cooldown (sec)"), 1, 3)
        settings_layout.addWidget(self.cooldown_input, 1, 4)

        settings_layout.addWidget(QLabel("EMA1"), 3, 0)
        settings_layout.addWidget(self.ema1_input, 3, 1)
        settings_layout.addWidget(QLabel("RSI"), 3, 3)
        settings_layout.addWidget(self.rsi_input, 3, 4)

        settings_layout.addWidget(QLabel("EMA2"), 4, 0)
        settings_layout.addWidget(self.ema2_input, 4, 1)
        settings_layout.addWidget(QLabel("BB Period"), 4, 3)
        settings_layout.addWidget(self.bb_period_input, 4, 4)

        settings_layout.addWidget(QLabel("EMA3"), 5, 0)
        settings_layout.addWidget(self.ema3_input, 5, 1)
        settings_layout.addWidget(QLabel("BB Std Dev"), 5, 3)
        settings_layout.addWidget(self.bb_std_input, 5, 4)

        settings_layout.addWidget(QLabel("EMA4"), 6, 0)
        settings_layout.addWidget(self.ema4_input, 6, 1)

        settings_layout.addWidget(QLabel("Telegram Token"), 8, 0)
        self.test_telegram_btn = QPushButton("Test")
        self.test_telegram_btn.setFixedWidth(70)
        token_row_wrap = QWidget()
        token_row = QHBoxLayout()
        token_row.setContentsMargins(0, 0, 0, 0)
        token_row.setSpacing(8)
        token_row.addWidget(self.token_input, 0)
        token_row.addWidget(self.test_telegram_btn, 0)
        token_row.addStretch(1)
        token_row_wrap.setLayout(token_row)
        settings_layout.addWidget(token_row_wrap, 8, 1, 1, 4)
        self.save_btn = QPushButton("Save Settings")
        settings_layout.addWidget(self.save_btn, 9, 0, 1, 6)

        settings_layout.setColumnMinimumWidth(0, 90)
        settings_layout.setColumnMinimumWidth(3, 115)
        settings_layout.setColumnMinimumWidth(1, setting_field_w)
        settings_layout.setColumnMinimumWidth(2, 28)
        settings_layout.setColumnMinimumWidth(4, setting_field_w)
        settings_layout.setColumnStretch(1, 1)
        settings_layout.setColumnStretch(2, 1)
        settings_layout.setColumnStretch(4, 1)
        settings_layout.setRowStretch(7, 1)
        settings_box.setLayout(settings_layout)
        settings_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        top_panel_h = max(dashboard.sizeHint().height(), settings_box.sizeHint().height()) + 10
        dashboard.setFixedHeight(top_panel_h)
        settings_box.setFixedHeight(top_panel_h)

        self.conditions_box = QGroupBox("Condition Builder (AND logic)")
        self.conditions_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        conditions_layout = QVBoxLayout()
        conditions_layout.setContentsMargins(8, 8, 8, 4)
        conditions_layout.setSpacing(2)
        conditions_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        add_cond_btn = QPushButton("Add Condition")
        add_cond_btn.setFixedHeight(24)
        add_cond_btn.setAutoDefault(False)
        add_cond_btn.clicked.connect(lambda: self.add_condition())
        conditions_layout.addWidget(add_cond_btn)
        conditions_layout.addSpacing(6)

        self.conditions_scroll = QScrollArea()
        self.conditions_scroll.setWidgetResizable(True)
        self.conditions_scroll.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.conditions_scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        scroll_wrap = QWidget()
        self.conditions_container = QVBoxLayout()
        self.conditions_container.setContentsMargins(0, 4, 0, 0)
        self.conditions_container.setSpacing(4)
        self.conditions_container.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.conditions_container.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        scroll_wrap.setLayout(self.conditions_container)
        self.conditions_scroll.setWidget(scroll_wrap)
        conditions_layout.addWidget(self.conditions_scroll)
        self.conditions_box.setLayout(conditions_layout)
        self._condition_row_height = 66
        self._condition_visible_rows = 3
        self._update_conditions_area_height()
        fixed_h = self.conditions_box.layout().sizeHint().height() + 2
        self.conditions_box.setFixedHeight(fixed_h)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("Event log...")
        self.log_text.setMinimumHeight(85)

        top_layout = QHBoxLayout()
        top_layout.setSpacing(8)
        top_layout.addWidget(dashboard, 1)
        top_layout.addWidget(settings_box, 1)

        main_layout.addLayout(top_layout, 0)
        main_layout.addWidget(self.conditions_box, 0)
        main_layout.addWidget(self.log_text, 1)
        root.setLayout(main_layout)
        self.setCentralWidget(root)
        self.setMinimumSize(1180, 700)
        self.resize(1180, 700)

    def _connect_signals(self) -> None:
        self.save_btn.clicked.connect(self.on_save_clicked)
        self.refresh_btn.clicked.connect(self.on_manual_refresh)
        self.test_telegram_btn.clicked.connect(self.on_test_telegram)
        self.update_sec_input.valueChanged.connect(self._start_timer)
        self.symbol_input.currentTextChanged.connect(self.on_symbol_changed)

    def _start_timer(self) -> None:
        if hasattr(self, "timer"):
            self.timer.stop()
        else:
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.on_timer_refresh)
        self.timer.start(self.update_sec_input.value() * 1000)

    def _collect_indicator_settings(self) -> IndicatorSettings:
        return IndicatorSettings(
            timeframe=self.timeframe_input.currentText(),
            ema1_period=self.ema1_input.value(),
            ema2_period=self.ema2_input.value(),
            ema3_period=self.ema3_input.value(),
            ema4_period=self.ema4_input.value(),
            rsi_period=self.rsi_input.value(),
            bb_period=self.bb_period_input.value(),
            bb_std=self.bb_std_input.value(),
        )

    def _collect_settings(self) -> AppSettings:
        return AppSettings(
            symbol=self.symbol_input.currentText(),
            telegram_token=self.token_input.text().strip(),
            telegram_chat_id=self.telegram_chat_id,
            update_seconds=self.update_sec_input.value(),
            cooldown_seconds=self.cooldown_input.value(),
            indicators=self._collect_indicator_settings(),
            conditions=[row.to_dict() for row in self.condition_rows],
        )

    def _load_from_settings(self) -> None:
        settings = load_settings()
        self.symbol_input.setCurrentText(settings.symbol)
        self.token_input.setText(settings.telegram_token)
        self.telegram_chat_id = settings.telegram_chat_id
        self.update_sec_input.setValue(settings.update_seconds)
        self.cooldown_input.setValue(settings.cooldown_seconds)
        self.timeframe_input.setCurrentText(settings.indicators.timeframe)
        self.ema1_input.setValue(settings.indicators.ema1_period)
        self.ema2_input.setValue(settings.indicators.ema2_period)
        self.ema3_input.setValue(settings.indicators.ema3_period)
        self.ema4_input.setValue(settings.indicators.ema4_period)
        self.rsi_input.setValue(settings.indicators.rsi_period)
        self.bb_period_input.setValue(settings.indicators.bb_period)
        self.bb_std_input.setValue(settings.indicators.bb_std)
        for item in settings.conditions:
            self.add_condition(item)
        self.telegram_service.set_credentials(settings.telegram_token, self.telegram_chat_id)

    def _save_settings(self) -> bool:
        try:
            save_settings(self._collect_settings())
        except Exception as exc:
            self.log(f"Settings save failed ({type(exc).__name__}): {exc} [path={CONFIG_PATH}]")
            return False
        self.log("Settings saved")
        return True

    def add_condition(self, data: Optional[dict] = None) -> None:
        row = ConditionRow(data)
        row.set_snapshot(self.current_snapshot)
        row.remove_requested.connect(self.remove_condition)
        self.condition_rows.append(row)
        self.conditions_container.addWidget(row)
        self._update_conditions_area_height()
        # Ensure newly added row can be fully reached at the bottom.
        QTimer.singleShot(0, lambda r=row: self.conditions_scroll.ensureWidgetVisible(r, 0, 8))

    def remove_condition(self, row: ConditionRow) -> None:
        if row in self.condition_rows:
            self.condition_rows.remove(row)
        self.conditions_container.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._update_conditions_area_height()

    def _update_conditions_area_height(self) -> None:
        if not hasattr(self, "conditions_scroll"):
            return
        row_h = getattr(self, "_condition_row_height", 66)
        if self.condition_rows:
            row_h = max(row_h, self.condition_rows[0].sizeHint().height())
            self._condition_row_height = row_h
        visible_rows = getattr(self, "_condition_visible_rows", 3)
        spacing = self.conditions_container.spacing()
        cm = self.conditions_container.contentsMargins()
        scroll_h = row_h * visible_rows + spacing * (visible_rows - 1) + cm.top() + cm.bottom() + 8
        self.conditions_scroll.setFixedHeight(scroll_h)
        widget = self.conditions_scroll.widget()
        if widget is not None:
            widget.adjustSize()
            widget.updateGeometry()
        if hasattr(self, "conditions_box") and self.conditions_box.layout() is not None:
            # Keep group box height in sync with scroll area real height to avoid overlap with log.
            self.conditions_box.setFixedHeight(self.conditions_box.layout().sizeHint().height() + 2)
            self.conditions_box.updateGeometry()
        self.conditions_scroll.updateGeometry()

    def on_timer_refresh(self) -> None:
        self.refresh_data()

    def on_manual_refresh(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        if self.fetch_in_progress:
            return
        self.fetch_in_progress = True
        self.fetch_worker = FetchWorker(
            self.market_service,
            self.symbol_input.currentText(),
            self._collect_indicator_settings(),
        )
        self.fetch_worker.success.connect(self.on_fetch_success)
        self.fetch_worker.failed.connect(self.on_fetch_failed)
        self.fetch_worker.finished.connect(self._on_fetch_finished)
        self.fetch_worker.start()

    def _on_fetch_finished(self) -> None:
        self.fetch_in_progress = False
        self.fetch_worker = None

    def on_fetch_success(self, snapshot: DataSnapshot) -> None:
        self.previous_snapshot = self.current_snapshot
        self.current_snapshot = snapshot
        for row in self.condition_rows:
            row.set_snapshot(snapshot)
        self.price_title_label.setText(f"{snapshot.symbol} Price")
        self.price_label.setText(f"{snapshot.price:,.1f} {snapshot.quote_currency}")
        trend = 1 if snapshot.price > snapshot.prev_close else (-1 if snapshot.price < snapshot.prev_close else 0)
        self._set_price_trend_style(trend)
        self.price_label.setToolTip("")
        self.rsi_label.setText(f"{snapshot.rsi:.1f}")
        self.ema1_label.setText(f"{snapshot.ema1:,.1f}")
        self.ema2_label.setText(f"{snapshot.ema2:,.1f}")
        self.ema3_label.setText(f"{snapshot.ema3:,.1f}")
        self.ema4_label.setText(f"{snapshot.ema4:,.1f}")
        self.volume_label.setText(f"{snapshot.volume:,.1f}")
        self.bb_label.setText(f"{snapshot.bb_lower:,.1f} - {snapshot.bb_upper:,.1f}")
        self.updated_at_label.setText(
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snapshot.timestamp_ms / 1000))
        )
        self.evaluate_conditions()
        self.log("Market data updated")

    def on_fetch_failed(self, err: str) -> None:
        if "No data source (market closed)" in err:
            self.current_snapshot = None
            for row in self.condition_rows:
                row.set_snapshot(None)
            self._show_no_data_state(self.symbol_input.currentText())
        self.log(f"Fetch failed: {err}")

    def on_save_clicked(self) -> None:
        try:
            new_token = self.token_input.text().strip()
            old_token = self.telegram_service.token
            token_changed = new_token != old_token
            if token_changed:
                self.telegram_chat_id = ""
                self.telegram_last_update_id = 0
                self.last_telegram_status_log = ""
            self.telegram_service.set_credentials(new_token, self.telegram_chat_id)
            saved_ok = self._save_settings()
            self._sync_telegram_once()
            self._start_timer()
            if not saved_ok:
                self.log("Save settings requested (not persisted)")
            else:
                self.log("Save settings requested")
        except Exception as exc:
            self.log(f"Save settings failed ({type(exc).__name__}): {exc}")

    def on_symbol_changed(self) -> None:
        symbol = self.symbol_input.currentText()
        self.price_title_label.setText(f"{symbol} Price")
        self._show_no_data_state(symbol)
        self._save_settings()
        self.refresh_data()

    def on_test_telegram(self) -> None:
        self.telegram_service.set_credentials(self.token_input.text(), self.telegram_chat_id)
        if not self.telegram_chat_id.strip():
            self._sync_telegram_once()
            self.log("Trying to auto-detect chat_id. Please test again in a few seconds.")
            return
        self._send_telegram_async("Price tracker test message.", "Telegram test")

    def _update_telegram_status(self) -> None:
        self.telegram_service.set_credentials(self.token_input.text(), self.telegram_chat_id)
        ok, msg = self.telegram_service.validate()
        self._set_telegram_status(ok, msg)

    def _sync_telegram_once(self) -> None:
        token = self.token_input.text().strip()
        if not token:
            self._set_telegram_status(False, "Missing token")
            return
        if self.telegram_sync_in_progress:
            return
        self.telegram_sync_in_progress = True
        self.telegram_sync_worker = TelegramSyncWorker(
            token=token,
            chat_id=self.telegram_chat_id,
            last_update_id=self.telegram_last_update_id,
        )
        self.telegram_sync_worker.success.connect(self._on_telegram_sync_success)
        self.telegram_sync_worker.failed.connect(self._on_telegram_sync_failed)
        self.telegram_sync_worker.finished.connect(self._on_telegram_sync_finished)
        self.telegram_sync_worker.start()

    def _on_telegram_sync_finished(self) -> None:
        self.telegram_sync_in_progress = False
        self.telegram_sync_worker = None

    def _on_telegram_sync_success(self, result: object) -> None:
        try:
            if not isinstance(result, dict):
                return
            self.telegram_last_update_id = int(result.get("last_update_id", self.telegram_last_update_id))
            new_chat_id = str(result.get("chat_id", "") or "")
            if new_chat_id and not self.telegram_chat_id:
                self.telegram_chat_id = new_chat_id
                self.telegram_service.set_credentials(self.token_input.text(), new_chat_id)
                self._save_settings()
                self.log(f"Auto detected chat_id: {new_chat_id}")
            elif new_chat_id and new_chat_id != self.telegram_chat_id:
                self.log(f"Ignored different detected chat_id: {new_chat_id}")
                self.telegram_service.set_credentials(self.token_input.text(), self.telegram_chat_id)
            else:
                self.telegram_service.set_credentials(self.token_input.text(), self.telegram_chat_id)

            status = str(result.get("status", "Disconnected"))
            ok = bool(result.get("ok", False))
            self._set_telegram_status(ok, status)

            note = str(result.get("note", "")).strip()
            if note:
                self.log(note)
            if status != self.last_telegram_status_log:
                self.log(f"Telegram status: {status}")
                self.last_telegram_status_log = status
        except Exception as exc:
            self._set_telegram_status(False, "Telegram sync failed")
            self.log(f"Telegram sync handling failed ({type(exc).__name__}): {exc}")

    def _on_telegram_sync_failed(self, err: str) -> None:
        msg = f"Telegram sync error: {err}"
        self._set_telegram_status(False, msg)
        if msg != self.last_telegram_status_log:
            self.log(msg)
            self.last_telegram_status_log = msg

    def _set_telegram_status(self, connected: bool, text: str) -> None:
        self.telegram_status_label.setText(text)
        if connected:
            self.telegram_status_label.setStyleSheet("color: white; background: #228b22; padding: 4px 8px;")
        else:
            self.telegram_status_label.setStyleSheet("color: white; background: #8b0000; padding: 4px 8px;")

    def _set_price_trend_style(self, trend: int) -> None:
        if trend > 0:
            self.price_label.setStyleSheet(
                "font-size: 28px; font-weight: 800; color: #e8ffe8; "
                "background: #1f7a35; border: 1px solid #4ca868; border-radius: 6px; padding: 6px 10px;"
            )
            return
        if trend < 0:
            self.price_label.setStyleSheet(
                "font-size: 28px; font-weight: 800; color: #ffe8e8; "
                "background: #8f2e2e; border: 1px solid #c55a5a; border-radius: 6px; padding: 6px 10px;"
            )
            return
        self.price_label.setStyleSheet(
            "font-size: 28px; font-weight: 800; color: #f2f2f2; "
            "background: #2f2f2f; border: 1px solid #676767; border-radius: 6px; padding: 6px 10px;"
        )

    def evaluate_conditions(self) -> None:
        if not self.current_snapshot:
            return
        enabled_rows = [row for row in self.condition_rows if row.is_enabled()]
        if not enabled_rows:
            self.last_condition_state = False
            return

        results = []
        for row in enabled_rows:
            try:
                results.append(row.evaluate(self.current_snapshot, self.previous_snapshot))
            except Exception as exc:
                self.log(f"Condition evaluation error: {exc}")
                results.append(False)
        all_true = all(results)

        cooldown_ok = (time.time() - self.last_alert_ts) >= self.cooldown_input.value()
        if all_true and (not self.last_condition_state) and cooldown_ok:
            self.send_alert(enabled_rows)
            self.last_alert_ts = time.time()
        self.last_condition_state = all_true

    def send_alert(self, enabled_rows: List[ConditionRow]) -> None:
        if not self.current_snapshot:
            return
        conditions_text = " AND ".join(row.description() for row in enabled_rows)
        s = self.current_snapshot
        message = (
            f"[{s.symbol} Alert]\n"
            f"Symbol: {s.symbol}\n"
            f"Price: {s.price:.1f} {s.quote_currency}\n"
            f"RSI: {s.rsi:.1f}\n"
            f"EMA1/2/3/4: {s.ema1:.1f} / {s.ema2:.1f} / {s.ema3:.1f} / {s.ema4:.1f}\n"
            f"Volume: {s.volume:.1f}\n"
            f"BB: {s.bb_lower:.1f} - {s.bb_upper:.1f}\n"
            f"Condition: {conditions_text}\n"
            f"Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(s.timestamp_ms / 1000))}"
        )
        self._send_telegram_async(message, "Alert send result")

    def _show_no_data_state(self, symbol: Optional[str] = None) -> None:
        if symbol:
            self.price_title_label.setText(f"{symbol} Price")
        self.price_label.setText("-")
        self._set_price_trend_style(0)
        self.rsi_label.setText("-")
        self.ema1_label.setText("-")
        self.ema2_label.setText("-")
        self.ema3_label.setText("-")
        self.ema4_label.setText("-")
        self.volume_label.setText("-")
        self.bb_label.setText("-")
        self.updated_at_label.setText("-")

    def _send_telegram_async(self, text: str, context: str) -> bool:
        token = self.token_input.text().strip()
        chat_id = self.telegram_chat_id.strip()
        if not token or not chat_id:
            self._set_telegram_status(False, "Missing token or chat ID")
            self.log(f"{context}: Missing token or chat ID")
            return False

        worker = TelegramSendWorker(token, chat_id, text, context)
        self.telegram_send_workers.append(worker)
        worker.success.connect(lambda payload, w=worker: self._on_telegram_send_success(w, payload))
        worker.failed.connect(lambda err, w=worker, c=context: self._on_telegram_send_failed(w, c, err))
        worker.finished.connect(lambda w=worker: self._on_telegram_send_finished(w))
        worker.start()
        return True

    def _on_telegram_send_success(self, worker: TelegramSendWorker, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        ok = bool(payload.get("ok", False))
        msg = str(payload.get("msg", "Telegram API error"))
        context = str(payload.get("context", "Telegram send"))
        self._set_telegram_status(ok, "Connected" if ok else "Disconnected")
        self.log(f"{context}: {msg}")

    def _on_telegram_send_failed(self, worker: TelegramSendWorker, context: str, err: str) -> None:
        self._set_telegram_status(False, "Disconnected")
        self.log(f"{context}: {err}")

    def _on_telegram_send_finished(self, worker: TelegramSendWorker) -> None:
        if worker in self.telegram_send_workers:
            self.telegram_send_workers.remove(worker)

    def closeEvent(self, event: QCloseEvent) -> None:
        if hasattr(self, "timer"):
            self.timer.stop()

        workers: List[QThread] = []
        if self.fetch_worker is not None:
            workers.append(self.fetch_worker)
        if self.telegram_sync_worker is not None:
            workers.append(self.telegram_sync_worker)
        workers.extend(self.telegram_send_workers)

        for worker in workers:
            if worker.isRunning():
                worker.wait(35000)

        super().closeEvent(event)

    def log(self, text: str) -> None:
        now = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{now}] {text}")


def apply_dark_theme(app: QApplication) -> None:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#1e1f22"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e6e6e6"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#2b2d31"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#23252a"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e6e6e6"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#2b2d31"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e6e6e6"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2b2d31"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#e6e6e6"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#3d74f5"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#8a8f98"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#8a8f98"))
    app.setPalette(palette)

    app.setStyleSheet(
        """
        QWidget {
            background: #1e1f22;
            color: #e6e6e6;
            font-size: 12px;
        }
        QGroupBox {
            border: 1px solid #3a3d41;
            margin-top: 18px;
            border-radius: 6px;
            padding: 6px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 6px;
            color: #cfd2d6;
        }
        QLabel {
            color: #e6e6e6;
        }
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit {
            background: #2b2d31;
            border: 1px solid #3a3d41;
            border-radius: 4px;
            padding: 3px 6px;
            selection-background-color: #3d74f5;
            selection-color: #ffffff;
        }
        QComboBox::drop-down {
            border: 0;
        }
        QComboBox QAbstractItemView {
            background: #2b2d31;
            color: #e6e6e6;
            selection-background-color: #3d74f5;
        }
        QPushButton {
            background: #2f6fcb;
            color: #ffffff;
            border: 1px solid #3b7bd8;
            border-radius: 4px;
            padding: 4px 10px;
        }
        QPushButton:hover {
            background: #3a7be0;
        }
        QPushButton:pressed {
            background: #2b64b8;
        }
        QPushButton:disabled {
            background: #3a3d41;
            color: #8a8f98;
            border-color: #3a3d41;
        }
        QScrollArea {
            border: 1px solid #3a3d41;
            border-radius: 6px;
        }
        QTextEdit {
            background: #202226;
        }
        QScrollBar:vertical {
            background: #1f2024;
            width: 12px;
            margin: 2px 0 2px 0;
        }
        QScrollBar::handle:vertical {
            background: #3a3d41;
            border-radius: 6px;
            min-height: 20px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0;
        }
        """
    )


def main() -> None:
    global CONFIG_PATH, APP_INSTANCE_LABEL
    config_path, instance_label, qt_remaining_argv = resolve_runtime_config(sys.argv[1:])
    CONFIG_PATH = config_path
    APP_INSTANCE_LABEL = instance_label

    qt_argv = [sys.argv[0], *qt_remaining_argv]
    app = QApplication(qt_argv)
    apply_dark_theme(app)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
