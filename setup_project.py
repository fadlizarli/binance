#!/usr/bin/env python3
"""
setup_project.py
Jalankan sekali untuk membuat struktur folder dan semua file yang kurang.
Usage: python setup_project.py
"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))

def write(path, content):
    full = os.path.join(BASE, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  ✅ {path}")

print("\n🔧 Setup CryptoBot Project...\n")

# ============================================================
# FOLDER __init__.py
# ============================================================
for folder in ["config", "core", "strategies", "risk", "exchange", "utils", "logs", "data"]:
    os.makedirs(os.path.join(BASE, folder), exist_ok=True)

write("config/__init__.py", "from .settings import config\n__all__ = ['config']\n")
write("core/__init__.py", "from .indicators import IndicatorEngine, IndicatorResult\nfrom .position import Position, TradeRecord\nfrom .bot_engine import BotEngine\n")
write("strategies/__init__.py", """\
from .base import BaseStrategy, Signal
from .trend_following import TrendFollowingStrategy
from .support_bounce import SupportBounceStrategy
from .breakout import BreakoutStrategy
from .scalping import ScalpingStrategy

STRATEGY_MAP = {
    "trend_following": TrendFollowingStrategy,
    "support_bounce":  SupportBounceStrategy,
    "breakout":        BreakoutStrategy,
    "scalping":        ScalpingStrategy,
}

def get_strategy(name: str):
    cls = STRATEGY_MAP.get(name.lower())
    if cls is None:
        raise ValueError(f"Strategi '{name}' tidak ada. Pilihan: {list(STRATEGY_MAP.keys())}")
    return cls()
""")
write("risk/__init__.py", "from .manager import RiskManager, RiskCalculation\n__all__ = ['RiskManager', 'RiskCalculation']\n")
write("exchange/__init__.py", "from .binance_client import BinanceClient\n__all__ = ['BinanceClient']\n")
write("utils/__init__.py", "from .logger import logger, trade_logger\nfrom .notifier import TelegramNotifier\n__all__ = ['logger', 'trade_logger', 'TelegramNotifier']\n")

# ============================================================
# CONFIG
# ============================================================
write("config/settings.py", """\
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
    symbol:    str = field(default_factory=lambda: os.getenv("SYMBOL", "BTCUSDT"))
    timeframe: str = field(default_factory=lambda: os.getenv("TIMEFRAME", "1h"))
    leverage:  int = field(default_factory=lambda: int(os.getenv("LEVERAGE", "5")))
    strategy:  str = field(default_factory=lambda: os.getenv("STRATEGY", "trend_following"))

@dataclass
class RiskConfig:
    risk_per_trade:      float = field(default_factory=lambda: float(os.getenv("RISK_PER_TRADE", "1.0")))
    sl_atr_multiplier:   float = field(default_factory=lambda: float(os.getenv("SL_ATR_MULTIPLIER", "1.5")))
    rr_ratio:            float = field(default_factory=lambda: float(os.getenv("RR_RATIO", "2.0")))
    max_daily_drawdown:  float = field(default_factory=lambda: float(os.getenv("MAX_DAILY_DRAWDOWN", "5.0")))
    max_trades_per_day:  int   = field(default_factory=lambda: int(os.getenv("MAX_TRADES_PER_DAY", "5")))
    trailing_stop_enabled: bool = True
    min_rr_ratio:        float = 1.5

@dataclass
class NotificationConfig:
    telegram_token:   str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))

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
""")

# ============================================================
# UTILS
# ============================================================
write("utils/logger.py", """\
import logging, os
from datetime import datetime
from logging.handlers import RotatingFileHandler

def setup_logger(name="CryptoBot", log_dir="logs"):
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return logger

    fmt = logging.Formatter("%(asctime)s [%(levelname)-8s] %(message)s", datefmt="%H:%M:%S")
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)
    logger.addHandler(ch)

    today = datetime.now().strftime("%Y%m%d")
    fh = RotatingFileHandler(
        os.path.join(log_dir, f"cryptobot_{today}.log"),
        maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-8s] %(message)s"))
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)
    return logger

def setup_trade_logger(log_dir="logs"):
    os.makedirs(log_dir, exist_ok=True)
    tl = logging.getLogger("TradeLog")
    tl.setLevel(logging.INFO)
    if tl.handlers:
        return tl
    today = datetime.now().strftime("%Y%m%d")
    fh = RotatingFileHandler(
        os.path.join(log_dir, f"trades_{today}.log"),
        maxBytes=2*1024*1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    tl.addHandler(fh)
    return tl

logger      = setup_logger()
trade_logger = setup_trade_logger()
""")

write("utils/notifier.py", """\
import requests
from utils.logger import logger

class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token   = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)

    def send(self, message: str) -> bool:
        if not self.enabled:
            return False
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.warning(f"Telegram error: {e}")
            return False

    def notify_entry(self, side, symbol, entry, sl, tp, risk, strategy):
        emoji = "🟢" if side == "LONG" else "🔴"
        self.send(
            f"{emoji} <b>ENTRY {side}</b>\\n"
            f"📊 <b>{symbol}</b>\\n"
            f"📍 Entry : <code>${entry:,.2f}</code>\\n"
            f"🛑 SL    : <code>${sl:,.2f}</code>\\n"
            f"🎯 TP    : <code>${tp:,.2f}</code>\\n"
            f"💰 Risk  : <code>${risk:.2f}</code>\\n"
            f"🧠 Strat : <code>{strategy}</code>"
        )

    def notify_exit(self, side, symbol, entry, exit_price, pnl, reason):
        emoji = "✅" if pnl > 0 else "❌"
        self.send(
            f"{emoji} <b>EXIT {side}</b>\\n"
            f"📊 <b>{symbol}</b>\\n"
            f"📍 Entry : <code>${entry:,.2f}</code>\\n"
            f"📤 Exit  : <code>${exit_price:,.2f}</code>\\n"
            f"💵 PnL   : <code>{'+'if pnl>=0 else ''}{pnl:.2f} USDT</code>\\n"
            f"📋 Alasan: <code>{reason}</code>"
        )

    def notify_daily_summary(self, trades, wins, pnl, balance):
        wr = (wins/trades*100) if trades > 0 else 0
        self.send(
            f"📊 <b>Ringkasan Harian</b>\\n"
            f"🔢 Total  : <code>{trades}</code>\\n"
            f"🎯 WinRate: <code>{wr:.1f}%</code>\\n"
            f"💵 PnL    : <code>{'+'if pnl>=0 else ''}{pnl:.2f}</code>\\n"
            f"💰 Balance: <code>${balance:,.2f}</code>"
        )
""")

# ============================================================
# CORE — indicators
# ============================================================
write("core/indicators.py", """\
from dataclasses import dataclass
from typing import Optional
import pandas as pd

@dataclass
class IndicatorResult:
    ema_9: float = 0.0; ema_21: float = 0.0; ema_55: float = 0.0; ema_200: float = 0.0
    ema_trend: str = "NEUTRAL"
    rsi: float = 50.0; rsi_signal: str = "NEUTRAL"; rsi_divergence: str = "NONE"
    macd_line: float = 0.0; macd_signal: float = 0.0; macd_hist: float = 0.0
    macd_cross: str = "NONE"
    bb_upper: float = 0.0; bb_middle: float = 0.0; bb_lower: float = 0.0
    bb_squeeze: bool = False; bb_position: str = "MID"
    atr: float = 0.0; atr_percent: float = 0.0
    volume_ratio: float = 1.0; volume_signal: str = "NORMAL"
    close: float = 0.0; high: float = 0.0; low: float = 0.0

class IndicatorEngine:
    def __init__(self): self.last_result = None

    def calculate(self, df: pd.DataFrame) -> Optional[IndicatorResult]:
        if df is None or len(df) < 55: return None
        r = IndicatorResult()
        try:
            c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
            r.ema_9   = self._ema(c, 9)
            r.ema_21  = self._ema(c, 21)
            r.ema_55  = self._ema(c, 55)
            r.ema_200 = self._ema(c, min(200, len(c)-1))
            r.ema_trend = "BULLISH" if r.ema_9 > r.ema_21 > r.ema_55 else "BEARISH" if r.ema_9 < r.ema_21 < r.ema_55 else "NEUTRAL"
            r.rsi = self._rsi(c)
            r.rsi_signal = "OVERSOLD" if r.rsi < 30 else "OVERBOUGHT" if r.rsi > 70 else "NEUTRAL"
            r.rsi_divergence = self._rsi_div(c)
            ml, ms, mh = self._macd(c)
            r.macd_line, r.macd_signal, r.macd_hist = ml, ms, mh
            r.macd_cross = self._macd_cross(c)
            bu, bm, bl = self._bb(c)
            r.bb_upper, r.bb_middle, r.bb_lower = bu, bm, bl
            r.bb_squeeze  = self._bb_squeeze(c)
            r.bb_position = "AT_UPPER" if c.iloc[-1] >= bu else "AT_LOWER" if c.iloc[-1] <= bl else "ABOVE_MID" if c.iloc[-1] > bm else "BELOW_MID"
            r.atr = self._atr(h, l, c)
            r.atr_percent = (r.atr / c.iloc[-1]) * 100
            r.volume_ratio = round(v.iloc[-1] / v.rolling(20).mean().iloc[-1], 2) if v.rolling(20).mean().iloc[-1] else 1.0
            r.volume_signal = "HIGH" if r.volume_ratio >= 1.5 else "LOW" if r.volume_ratio <= 0.6 else "NORMAL"
            r.close, r.high, r.low = c.iloc[-1], h.iloc[-1], l.iloc[-1]
            self.last_result = r
        except Exception as e:
            from utils.logger import logger
            logger.error(f"Indikator error: {e}")
        return r

    @staticmethod
    def _ema(s, p):
        k, e = 2/(p+1), s.iloc[0]
        for x in s.iloc[1:]: e = x*k + e*(1-k)
        return round(e, 6)

    @staticmethod
    def _rsi(s, p=14):
        d = s.diff().dropna()
        g = d.clip(lower=0).rolling(p).mean().iloc[-1]
        l = (-d).clip(lower=0).rolling(p).mean().iloc[-1]
        return round(100 - 100/(1 + g/l), 2) if l != 0 else 100.0

    @staticmethod
    def _rsi_div(c):
        if len(c) < 30: return "NONE"
        pc = c.iloc[-20] - c.iloc[-1]
        d  = c.diff().dropna()
        g  = d.clip(lower=0).rolling(14).mean()
        lo = (-d).clip(lower=0).rolling(14).mean()
        rsi_s = (100 - 100/(1 + g/lo.replace(0, 0.001))).iloc[-20:]
        pr = rsi_s.iloc[-1] - rsi_s.iloc[0]
        if pc < 0 and pr > 5: return "BULL_DIV"
        if pc > 0 and pr < -5: return "BEAR_DIV"
        return "NONE"

    @staticmethod
    def _macd(s, f=12, sl=26, sig=9):
        ef = s.ewm(span=f, adjust=False).mean()
        es = s.ewm(span=sl, adjust=False).mean()
        ml = ef - es
        ms = ml.ewm(span=sig, adjust=False).mean()
        return round(ml.iloc[-1],6), round(ms.iloc[-1],6), round((ml-ms).iloc[-1],6)

    @staticmethod
    def _macd_cross(s):
        ef = s.ewm(span=12, adjust=False).mean()
        es = s.ewm(span=26, adjust=False).mean()
        ml = ef - es; ms = ml.ewm(span=9, adjust=False).mean()
        pd_, cd = ml.iloc[-2]-ms.iloc[-2], ml.iloc[-1]-ms.iloc[-1]
        if pd_ < 0 and cd >= 0: return "BULLISH_CROSS"
        if pd_ > 0 and cd <= 0: return "BEARISH_CROSS"
        return "NONE"

    @staticmethod
    def _bb(s, p=20, std=2.0):
        m = s.rolling(p).mean(); sg = s.rolling(p).std()
        return round((m+std*sg).iloc[-1],6), round(m.iloc[-1],6), round((m-std*sg).iloc[-1],6)

    @staticmethod
    def _bb_squeeze(s, p=20):
        if len(s) < 55: return False
        m = s.rolling(p).mean(); sg = s.rolling(p).std()
        bw = (4*sg)/m
        return bw.iloc[-1] < bw.rolling(50).mean().iloc[-1]*0.7

    @staticmethod
    def _atr(h, l, c, p=14):
        pc = c.shift(1)
        tr = pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
        return round(tr.rolling(p).mean().iloc[-1], 6)

    def print_summary(self, r: IndicatorResult):
        from utils.logger import logger
        logger.info("="*55)
        logger.info(f"📊 Close: ${r.close:,.2f} | ATR: {r.atr:.2f} ({r.atr_percent:.2f}%)")
        logger.info(f"   EMA  : {r.ema_9:.2f}/{r.ema_21:.2f}/{r.ema_55:.2f} [{r.ema_trend}]")
        logger.info(f"   RSI  : {r.rsi:.1f} [{r.rsi_signal}] Div:{r.rsi_divergence}")
        logger.info(f"   MACD : {r.macd_line:.4f} hist:{r.macd_hist:.4f} [{r.macd_cross}]")
        logger.info(f"   BB   : {r.bb_lower:.2f}/{r.bb_middle:.2f}/{r.bb_upper:.2f} [{r.bb_position}] Squeeze:{r.bb_squeeze}")
        logger.info(f"   Vol  : {r.volume_ratio:.2f}x [{r.volume_signal}]")
        logger.info("="*55)
""")

# ============================================================
# CORE — position
# ============================================================
write("core/position.py", """\
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class Position:
    id: str; symbol: str; side: str
    entry_price: float; quantity: float
    stop_loss: float; take_profit: float
    risk_amount: float; strategy: str; leverage: int
    open_time: datetime = field(default_factory=datetime.now)
    entry_order_id: Optional[str] = None
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    partial_tp_done: bool = False
    sl_moved_to_be: bool = False
    pnl: float = 0.0; status: str = "OPEN"

    @property
    def close_side(self): return "SELL" if self.side == "LONG" else "BUY"

    def calculate_pnl(self, price: float) -> float:
        if self.side == "LONG":
            self.pnl = round((price - self.entry_price) * self.quantity * self.leverage, 4)
        else:
            self.pnl = round((self.entry_price - price) * self.quantity * self.leverage, 4)
        return self.pnl

    def __str__(self):
        return f"[{self.side}] {self.symbol} Entry:${self.entry_price:.2f} SL:${self.stop_loss:.2f} TP:${self.take_profit:.2f} PnL:${self.pnl:+.2f}"

@dataclass
class TradeRecord:
    position: Position; exit_price: float
    exit_time: datetime = field(default_factory=datetime.now)
    exit_reason: str = ""; final_pnl: float = 0.0
""")

# ============================================================
# RISK
# ============================================================
write("risk/manager.py", """\
from dataclasses import dataclass
from typing import Tuple, Optional
from config import config
from utils.logger import logger

@dataclass
class RiskCalculation:
    valid: bool; side: str; entry_price: float
    stop_loss: float; take_profit: float
    quantity: float; risk_amount: float; reward_amount: float
    rr_actual: float; sl_distance_pct: float; tp_distance_pct: float
    reason: str = ""

class RiskManager:
    def __init__(self):
        self.risk_cfg = config.risk
        self.daily_pnl = 0.0; self.daily_trades = 0
        self.session_high_balance = 0.0

    def calculate_position(self, side, entry_price, atr, balance) -> RiskCalculation:
        risk_amount = balance * (self.risk_cfg.risk_per_trade / 100)
        sl_dist = atr * self.risk_cfg.sl_atr_multiplier
        tp_dist = sl_dist * self.risk_cfg.rr_ratio
        sl = entry_price - sl_dist if side == "LONG" else entry_price + sl_dist
        tp = entry_price + tp_dist if side == "LONG" else entry_price - tp_dist
        qty = risk_amount / sl_dist
        sl_pct = (sl_dist / entry_price) * 100
        rr = tp_dist / sl_dist

        if rr < self.risk_cfg.min_rr_ratio:
            return RiskCalculation(False, side, entry_price, sl, tp, qty, risk_amount,
                risk_amount*rr, rr, sl_pct, (tp_dist/entry_price)*100,
                f"R:R terlalu rendah: {rr:.2f}")
        if sl_pct > 5.0:
            return RiskCalculation(False, side, entry_price, sl, tp, qty, risk_amount,
                risk_amount*rr, rr, sl_pct, (tp_dist/entry_price)*100,
                f"SL terlalu jauh: {sl_pct:.2f}%")

        logger.debug(f"Risk OK | {side} SL:${sl:.2f}({sl_pct:.2f}%) TP:${tp:.2f} Qty:{qty:.4f} Risk:${risk_amount:.2f}")
        return RiskCalculation(True, side, entry_price, sl, tp, qty, risk_amount,
            risk_amount*rr, rr, sl_pct, (tp_dist/entry_price)*100)

    def can_trade(self, balance: float) -> Tuple[bool, str]:
        if self.daily_trades >= self.risk_cfg.max_trades_per_day:
            return False, f"Max trade harian tercapai ({self.risk_cfg.max_trades_per_day})"
        if self.session_high_balance > 0:
            dd = ((self.session_high_balance - balance) / self.session_high_balance) * 100
            if dd >= self.risk_cfg.max_daily_drawdown:
                return False, f"Max drawdown {self.risk_cfg.max_daily_drawdown}% tercapai"
        if balance > self.session_high_balance:
            self.session_high_balance = balance
        return True, "OK"

    def calculate_trailing_stop(self, side, price, current_sl, entry_price, atr) -> Optional[float]:
        if not self.risk_cfg.trailing_stop_enabled: return None
        if side == "LONG":
            new_sl = price - atr * self.risk_cfg.sl_atr_multiplier
            if new_sl > current_sl and price > entry_price * 1.005: return round(new_sl, 2)
        else:
            new_sl = price + atr * self.risk_cfg.sl_atr_multiplier
            if new_sl < current_sl and price < entry_price * 0.995: return round(new_sl, 2)
        return None

    def should_move_to_breakeven(self, side, price, entry_price, take_profit) -> bool:
        if side == "LONG": return price >= entry_price + (take_profit - entry_price) * 0.5
        return price <= entry_price - (entry_price - take_profit) * 0.5

    def register_trade_open(self): self.daily_trades += 1
    def register_trade_close(self, pnl): self.daily_pnl += pnl
    def reset_daily(self):
        logger.info(f"Reset harian | Trades:{self.daily_trades} PnL:${self.daily_pnl:+.2f}")
        self.daily_pnl = 0.0; self.daily_trades = 0
""")

# ============================================================
# EXCHANGE
# ============================================================
write("exchange/binance_client.py", """\
from typing import Optional
import pandas as pd
from config import config
from utils.logger import logger

try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException
    HAS_BINANCE = True
except ImportError:
    HAS_BINANCE = False
    logger.warning("python-binance belum diinstall: pip install python-binance")

class BinanceClient:
    def __init__(self):
        self.api_key    = config.api.api_key
        self.secret_key = config.api.secret_key
        self.is_testnet = config.api.is_testnet
        self.client     = None
        self._connect()

    def _connect(self):
        if not HAS_BINANCE: return
        try:
            self.client = Client(self.api_key, self.secret_key, testnet=self.is_testnet)
            mode = "TESTNET" if self.is_testnet else "LIVE"
            logger.info(f"✅ Terhubung ke Binance {mode}")
        except Exception as e:
            logger.error(f"Gagal connect Binance: {e}"); self.client = None

    def is_connected(self): return self.client is not None

    def get_klines(self, symbol, interval, limit=200) -> Optional[pd.DataFrame]:
        if not self.is_connected(): return None
        try:
            raw = self.client.futures_klines(symbol=symbol, interval=interval, limit=limit)
            df  = pd.DataFrame(raw, columns=[
                "timestamp","open","high","low","close","volume",
                "close_time","quote_volume","trades","tb_base","tb_quote","ignore"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            for col in ["open","high","low","close","volume"]:
                df[col] = df[col].astype(float)
            return df[["open","high","low","close","volume"]]
        except Exception as e:
            logger.error(f"get_klines error: {e}"); return None

    def get_ticker_price(self, symbol) -> Optional[float]:
        if not self.is_connected(): return None
        try: return float(self.client.futures_symbol_ticker(symbol=symbol)["price"])
        except Exception as e: logger.error(f"get_price error: {e}"); return None

    def get_account_balance(self) -> Optional[float]:
        if not self.is_connected(): return None
        try:
            for b in self.client.futures_account_balance():
                if b["asset"] == "USDT": return float(b["availableBalance"])
        except Exception as e: logger.error(f"get_balance error: {e}")
        return None

    def set_leverage(self, symbol, leverage) -> bool:
        if not self.is_connected(): return False
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            logger.info(f"Leverage {symbol}: {leverage}x"); return True
        except Exception as e: logger.error(f"set_leverage error: {e}"); return False

    def set_margin_type(self, symbol, margin_type="ISOLATED") -> bool:
        if not self.is_connected(): return False
        try:
            self.clien.futures_change_margin_type(symbol=symbol, marginType=margin_type)
            return True
        except BinanceAPIException as e:
            return True if e.code == -4046 else False
        except Exception: return False

    def place_market_order(self, symbol, side, quantity) -> Optional[dict]:
        if not self.is_connected(): return None
        try:
            o = self.client.futures_create_order(
                symbol=symbol, side=side, type="MARKET", quantity=round(quantity,3))
            logger.info(f"📥 {side} {quantity:.4f} {symbol} | ID:{o['orderId']}"); return o
        except Exception as e: logger.error(f"market_order error: {e}"); return None

    def place_stop_loss_order(self, symbol, side, quantity, stop_price) -> Optional[dict]:
        if not self.is_connected(): return None
        try:
            o = self.client.futures_create_order(
                symbol=symbol, side=side, type="STOP_MARKET",
                quantity=round(quantity,3), stopPrice=round(stop_price,2),
                reduceOnly=True)
            logger.info(f"🛑 SL {side} @ ${stop_price:.2f} | ID:{o['orderId']}"); return o
        except Exception as e: logger.error(f"sl_order error: {e}"); return None

    def place_take_profit_order(self, symbol, side, quantity, tp_price) -> Optional[dict]:
        if not self.is_connected(): return None
        try:
            o = self.client.futures_create_order(
                symbol=symbol, side=side, type="TAKE_PROFIT_MARKET",
                quantity=round(quantity,3), stopPrice=round(tp_price,2),
                reduceOnly=True)
            logger.info(f"🎯 TP {side} @ ${tp_price:.2f} | ID:{o['orderId']}"); return o
        except Exception as e: logger.error(f"tp_order error: {e}"); return None

    def cancel_all_orders(self, symbol) -> bool:
        if not self.is_connected(): return False
        try:
            self.client.futures_cancel_all_open_orders(symbol=symbol)
            logger.info(f"Semua order {symbol} dibatalkan"); return True
        except Exception as e: logger.error(f"cancel_orders error: {e}"); return False

    def close_position(self, symbol, side, quantity) -> Optional[dict]:
        close_side = "SELL" if side == "LONG" else "BUY"
        try:
            o = self.client.futures_create_order(
                symbol=symbol, side=close_side, type="MARKET",
                quantity=round(quantity,3), reduceOnly=True)
            logger.info(f"🔒 Close {symbol} {close_side} {quantity:.4f}"); return o
        except Exception as e: logger.error(f"close_position error: {e}"); return None
""")

# ============================================================
# STRATEGIES
# ============================================================
write("strategies/base.py", """\
from dataclasses import dataclass
from core.indicators import IndicatorResult

@dataclass
class Signal:
    action: str; strength: float; reason: str; strategy_name: str

class BaseStrategy:
    name: str = "base"
    def generate_signal(self, indicators: IndicatorResult) -> Signal:
        raise NotImplementedError
    def _make_signal(self, action, strength, reason):
        return Signal(action, round(strength,2), reason, self.name)
    def _wait(self, reason="Tidak ada setup"):
        return Signal("WAIT", 0.0, reason, self.name)
""")

write("strategies/trend_following.py", """\
from core.indicators import IndicatorResult
from strategies.base import BaseStrategy, Signal

class TrendFollowingStrategy(BaseStrategy):
    name = "trend_following"
    def generate_signal(self, ind: IndicatorResult) -> Signal:
        sl, ss, r = 0, 0, []
        if ind.ema_trend == "BULLISH": sl += 3; r.append("EMA bullish stack ✅")
        elif ind.ema_trend == "BEARISH": ss += 3; r.append("EMA bearish stack ✅")
        else: return self._wait("EMA tidak dalam trend jelas")

        dist = abs(ind.close - ind.ema_21) / ind.ema_21 * 100
        if dist <= 0.8:
            if ind.ema_trend == "BULLISH": sl += 2; r.append(f"Pullback EMA21 ({dist:.2f}%) ✅")
            else: ss += 2
        elif dist > 3.0: return self._wait(f"Terlalu jauh dari EMA21 ({dist:.2f}%)")

        if ind.macd_line > 0: sl += 1
        elif ind.macd_line < 0: ss += 1
        if ind.macd_cross == "BULLISH_CROSS": sl += 2; r.append("MACD bullish cross 🔥")
        elif ind.macd_cross == "BEARISH_CROSS": ss += 2

        if 30 <= ind.rsi <= 65: sl += 1; r.append(f"RSI normal ({ind.rsi:.1f}) ✅")
        elif 35 <= ind.rsi <= 70: ss += 1
        elif ind.rsi > 75: return self._wait(f"RSI overbought ({ind.rsi:.1f})")

        if ind.volume_signal == "HIGH": sl += 1; ss += 1; r.append("Volume tinggi 💪")
        if ind.rsi_divergence == "BEAR_DIV" and sl > ss: return self._wait("Bearish divergence ⚠️")

        if sl >= 5 and sl > ss: return self._make_signal("LONG", min(sl/9, 1.0), " | ".join(r))
        if ss >= 5 and ss > sl: return self._make_signal("SHORT", min(ss/9, 1.0), "Bearish " + " | ".join(r))
        return self._wait(f"Score kurang (L:{sl} S:{ss})")
""")

write("strategies/support_bounce.py", """\
from core.indicators import IndicatorResult
from strategies.base import BaseStrategy

class SupportBounceStrategy(BaseStrategy):
    name = "support_bounce"
    def generate_signal(self, ind: IndicatorResult):
        sl, ss, r = 0, 0, []
        if ind.bb_position == "AT_LOWER": sl += 3; r.append("Harga di BB Lower ✅")
        elif ind.bb_position == "AT_UPPER": ss += 3; r.append("Harga di BB Upper ✅")
        if ind.rsi < 30: sl += 3; r.append(f"RSI oversold ({ind.rsi:.1f}) 🔥")
        elif ind.rsi < 38: sl += 2
        elif ind.rsi > 70: ss += 3; r.append(f"RSI overbought ({ind.rsi:.1f}) 🔥")
        elif ind.rsi > 62: ss += 2
        if ind.rsi_divergence == "BULL_DIV": sl += 3; r.append("Bullish divergence 🔥")
        elif ind.rsi_divergence == "BEAR_DIV": ss += 3; r.append("Bearish divergence 🔥")
        if ind.macd_cross == "BULLISH_CROSS": sl += 1
        elif ind.macd_cross == "BEARISH_CROSS": ss += 1
        if ind.volume_signal == "HIGH":
            if sl > ss: sl += 1; r.append("Volume konfirmasi 💪")
            else: ss += 1
        if sl >= 5 and sl > ss: return self._make_signal("LONG", min(sl/10, 1.0), " | ".join(r))
        if ss >= 5 and ss > sl: return self._make_signal("SHORT", min(ss/10, 1.0), " | ".join(r))
        return self._wait(f"Belum ada bounce (L:{sl} S:{ss})")
""")

write("strategies/breakout.py", """\
from core.indicators import IndicatorResult
from strategies.base import BaseStrategy

class BreakoutStrategy(BaseStrategy):
    name = "breakout"
    def generate_signal(self, ind: IndicatorResult):
        if not ind.bb_squeeze: return self._wait("Belum ada BB squeeze")
        sl, ss, r = 1, 1, ["BB Squeeze ✅"]
        if ind.close > ind.bb_upper: sl += 3; r.append("Breakout atas BB Upper 🚀")
        elif ind.close > ind.bb_middle: sl += 1
        elif ind.close < ind.bb_lower: ss += 3; r.append("Breakout bawah BB Lower 📉")
        elif ind.close < ind.bb_middle: ss += 1
        if ind.volume_signal == "HIGH": sl += 2; ss += 2; r.append(f"Volume {ind.volume_ratio:.1f}x 💪")
        elif ind.volume_signal == "LOW": return self._wait("Volume rendah — false breakout")
        if ind.macd_cross == "BULLISH_CROSS": sl += 2; r.append("MACD cross 🔥")
        elif ind.macd_cross == "BEARISH_CROSS": ss += 2
        elif ind.macd_line > 0: sl += 1
        else: ss += 1
        if ind.ema_trend == "BULLISH": sl += 1
        elif ind.ema_trend == "BEARISH": ss += 1
        if sl >= 6 and sl > ss: return self._make_signal("LONG", min(sl/9, 1.0), " | ".join(r))
        if ss >= 6 and ss > sl: return self._make_signal("SHORT", min(ss/9, 1.0), " | ".join(r))
        return self._wait(f"Breakout belum konfirmasi (L:{sl} S:{ss})")
""")

write("strategies/scalping.py", """\
from core.indicators import IndicatorResult
from strategies.base import BaseStrategy

class ScalpingStrategy(BaseStrategy):
    name = "scalping"
    def generate_signal(self, ind: IndicatorResult):
        sl, ss, r = 0, 0, []
        if ind.macd_cross == "BULLISH_CROSS": sl += 4; r.append("MACD bullish cross 🔥")
        elif ind.macd_cross == "BEARISH_CROSS": ss += 4; r.append("MACD bearish cross 🔥")
        else: return self._wait("Belum ada MACD cross")
        if ind.close > ind.ema_9: sl += 2; r.append("Di atas EMA9 ✅")
        else: ss += 2; r.append("Di bawah EMA9 ✅")
        if ind.rsi > 70: return self._wait(f"RSI overbought ({ind.rsi:.1f})")
        if ind.rsi < 30: return self._wait(f"RSI oversold ({ind.rsi:.1f})")
        if 35 <= ind.rsi <= 55: sl += 1
        elif 45 <= ind.rsi <= 65: ss += 1
        if ind.rsi_divergence == "BULL_DIV": sl += 2; r.append("Bullish divergence 🔥")
        elif ind.rsi_divergence == "BEAR_DIV": ss += 2
        if ind.volume_signal == "HIGH": sl += 1; ss += 1; r.append("Volume ok 💪")
        elif ind.volume_signal == "LOW": return self._wait("Volume terlalu rendah")
        if sl >= 5 and sl > ss: return self._make_signal("LONG", min(sl/8, 1.0), " | ".join(r))
        if ss >= 5 and ss > sl: return self._make_signal("SHORT", min(ss/8, 1.0), " | ".join(r))
        return self._wait(f"Scalp belum valid (L:{sl} S:{ss})")
""")

# ============================================================
# CORE — bot_engine (move existing file if present)
# ============================================================
bot_engine_src = os.path.join(BASE, "bot_engine.py")
bot_engine_dst = os.path.join(BASE, "core", "bot_engine.py")
if os.path.exists(bot_engine_src) and not os.path.exists(bot_engine_dst):
    import shutil
    shutil.copy(bot_engine_src, bot_engine_dst)
    print("  ✅ core/bot_engine.py (dipindah dari root)")

# Move other existing files to correct folders
moves = [
    ("indicators.py",       "core/indicators.py"),
    ("manager.py",          "risk/manager.py"),
    ("binance_client.py",   "exchange/binance_client.py"),
    ("trend_following.py",  "strategies/trend_following.py"),
]
import shutil
for src_name, dst_path in moves:
    src = os.path.join(BASE, src_name)
    dst = os.path.join(BASE, dst_path)
    if os.path.exists(src) and not os.path.exists(dst):
        shutil.copy(src, dst)
        print(f"  📦 {src_name} → {dst_path}")

# ============================================================
# .env jika belum ada
# ============================================================
env_path = os.path.join(BASE, ".env")
if not os.path.exists(env_path):
    write(".env", """\
BINANCE_API_KEY=your_api_key_here
BINANCE_SECRET_KEY=your_secret_key_here
TRADE_MODE=testnet
SYMBOL=BTCUSDT
TIMEFRAME=1h
LEVERAGE=5
RISK_PER_TRADE=1.0
SL_ATR_MULTIPLIER=1.5
RR_RATIO=2.0
MAX_DAILY_DRAWDOWN=5.0
MAX_TRADES_PER_DAY=5
STRATEGY=trend_following
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
""")

print("\n✅ Setup selesai!\n")
print("Langkah selanjutnya:")
print("  1. Edit file .env dan isi API Key Binance")
print("  2. python main.py --backtest --candles 1000")
print("  3. python main.py")

