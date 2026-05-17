"""
config/settings.py — Versi Multi-pair
Cara pakai: Ganti isi config/settings.py dengan file ini
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

@dataclass
class TradingConfig:
    # Multi-pair: SYMBOLS=SOLUSDT,DOGEUSDT di .env
    symbols:          list  = field(default_factory=lambda: os.getenv("SYMBOLS", "SOLUSDT").split(","))
    symbol:           str   = field(default_factory=lambda: os.getenv("SYMBOLS", "SOLUSDT").split(",")[0])
    timeframe:        str   = field(default_factory=lambda: os.getenv("TIMEFRAME", "1h"))
    leverage:         int   = field(default_factory=lambda: int(os.getenv("LEVERAGE", "3")))
    mode:             str   = field(default_factory=lambda: os.getenv("TRADE_MODE", "testnet"))

@dataclass
class RiskConfig:
    risk_per_trade:     float = field(default_factory=lambda: float(os.getenv("RISK_PER_TRADE", "1.0")))
    max_daily_drawdown: float = field(default_factory=lambda: float(os.getenv("MAX_DAILY_DRAWDOWN", "10.0")))
    max_trades_per_day: int   = field(default_factory=lambda: int(os.getenv("MAX_TRADES_PER_DAY", "6")))
    sl_atr_multiplier:  float = field(default_factory=lambda: float(os.getenv("SL_ATR_MULTIPLIER", "1.5")))
    rr_ratio:           float = field(default_factory=lambda: float(os.getenv("RR_RATIO", "2.0")))

@dataclass
class NotificationConfig:
    telegram_token:        str  = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id:      str  = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    anthropic_api_key:     str  = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    claude_filter_enabled: bool = field(default_factory=lambda: os.getenv("CLAUDE_FILTER_ENABLED", "false").lower() == "true")

    @property
    def telegram_enabled(self): return bool(self.telegram_token and self.telegram_chat_id)

@dataclass
class AppConfig:
    trading:      TradingConfig      = field(default_factory=TradingConfig)
    risk:         RiskConfig         = field(default_factory=RiskConfig)
    notification: NotificationConfig = field(default_factory=NotificationConfig)
    strategy:     str                = field(default_factory=lambda: os.getenv("STRATEGY", "trend_following"))
    check_interval: int              = field(default_factory=lambda: int(os.getenv("CHECK_INTERVAL", "60")))

config = AppConfig()

