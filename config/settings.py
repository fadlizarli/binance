import os
from dataclasses import dataclass, field
from dotenv import load_dotenv
load_dotenv()

@dataclass
class APIConfig:
    api_key:    str = field(default_factory=lambda: os.getenv("BINANCE_API_KEY", ""))
    secret_key: str = field(default_factory=lambda: os.getenv("BINANCE_SECRET_KEY", ""))
    trade_mode: str = field(default_factory=lambda: os.getenv("TRADE_MODE", "testnet"))

    @property
    def is_testnet(self): return self.trade_mode.lower() == "testnet"

@dataclass
class TradingConfig:
    symbol:       str  = field(default_factory=lambda: os.getenv("SYMBOL", "BTCUSDT"))
    timeframe:    str  = field(default_factory=lambda: os.getenv("TIMEFRAME", "1h"))
    leverage:     int  = field(default_factory=lambda: int(os.getenv("LEVERAGE", "5")))
    strategy:     str  = field(default_factory=lambda: os.getenv("STRATEGY", "trend_following"))
    scan_symbols: list = field(default_factory=lambda: [
        s.strip() for s in os.getenv("SCAN_SYMBOLS", "").split(",") if s.strip()
    ])


@dataclass
class RiskConfig:
    risk_per_trade:      float = field(default_factory=lambda: float(os.getenv("RISK_PER_TRADE", "1.0")))
    sl_atr_multiplier:   float = field(default_factory=lambda: float(os.getenv("SL_ATR_MULTIPLIER", "1.5")))
    rr_ratio:            float = field(default_factory=lambda: float(os.getenv("RR_RATIO", "2.0")))
    max_daily_drawdown:  float = field(default_factory=lambda: float(os.getenv("MAX_DAILY_DRAWDOWN", "5.0")))
    max_trades_per_day:  int   = field(default_factory=lambda: int(os.getenv("MAX_TRADES_PER_DAY", "5")))
    min_balance:         float = field(default_factory=lambda: float(os.getenv("MIN_BALANCE", "50.0")))
    trailing_stop_enabled: bool = True
    min_rr_ratio:        float = 1.5

@dataclass
class NotificationConfig:
    telegram_token:   str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    claude_filter_enabled: bool = field(default_factory=lambda: os.getenv("CLAUDE_FILTER_ENABLED", "false").lower() == "true")

    @property
    def telegram_enabled(self): return bool(self.telegram_token and self.telegram_chat_id)

@dataclass
class BotConfig:
    api:            APIConfig          = field(default_factory=APIConfig)
    trading:        TradingConfig      = field(default_factory=TradingConfig)
    risk:           RiskConfig         = field(default_factory=RiskConfig)
    notification:   NotificationConfig = field(default_factory=NotificationConfig)
    check_interval: int  = 60
    candle_limit:   int  = 200
    log_dir:        str  = "logs"
    data_dir:       str  = "data"

config = BotConfig()
