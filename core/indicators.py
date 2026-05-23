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
    hammer: bool = False
    engulfing: str = "NONE"  # BULLISH, BEARISH, NONE

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
            r.atr_percent = (r.atr / c.iloc[-1]) * 100 if c.iloc[-1] > 0 else 0
            _vol_mean = v.rolling(20).mean().iloc[-1]
            r.volume_ratio = round(v.iloc[-1] / _vol_mean, 2) if (_vol_mean and _vol_mean > 0) else 1.0
            r.volume_signal = "HIGH" if r.volume_ratio >= 1.5 else "LOW" if r.volume_ratio <= 0.6 else "NORMAL"
            r.close, r.high, r.low = c.iloc[-1], h.iloc[-1], l.iloc[-1]
            r.hammer    = self._detect_hammer(df)
            r.engulfing = self._detect_engulfing(df)
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

    @staticmethod
    def _detect_hammer(df) -> bool:
        """Hammer: body kecil di atas, shadow bawah panjang = bullish reversal"""
        if len(df) < 2: return False
        c = df.iloc[-1]
        body   = abs(c.close - c.open)
        shadow = c.high - c.low
        lower  = min(c.open, c.close) - c.low
        if shadow == 0 or body == 0: return False
        # Shadow bawah >= 2x body, body <= 30% total shadow
        return (lower >= body * 2.0 and
                body / shadow <= 0.35 and
                c.close > c.open)  # candle hijau lebih valid

    @staticmethod
    def _detect_engulfing(df) -> str:
        """Engulfing: candle besar menutupi candle sebelumnya = reversal kuat"""
        if len(df) < 2: return "NONE"
        c1 = df.iloc[-2]  # candle sebelumnya
        c2 = df.iloc[-1]  # candle sekarang

        # Bullish engulfing: c1 merah, c2 hijau besar menutupi c1
        if (c1.close < c1.open and
            c2.close > c2.open and
            c2.open  <= c1.close and
            c2.close >= c1.open):
            return "BULLISH"

        # Bearish engulfing: c1 hijau, c2 merah besar menutupi c1
        if (c1.close > c1.open and
            c2.close < c2.open and
            c2.open  >= c1.close and
            c2.close <= c1.open):
            return "BEARISH"

        return "NONE"

    def print_summary(self, r: IndicatorResult):
        from utils.logger import logger
        logger.info("="*55)
        logger.info(f"📊 Close: ${r.close:,.2f} | ATR: {r.atr:.2f} ({r.atr_percent:.2f}%)")
        logger.info(f"   EMA  : {r.ema_9:.2f}/{r.ema_21:.2f}/{r.ema_55:.2f} [{r.ema_trend}]")
        logger.info(f"   RSI  : {r.rsi:.1f} [{r.rsi_signal}] Div:{r.rsi_divergence}")
        logger.info(f"   MACD : {r.macd_line:.4f} hist:{r.macd_hist:.4f} [{r.macd_cross}]")
        logger.info(f"   BB   : {r.bb_lower:.2f}/{r.bb_middle:.2f}/{r.bb_upper:.2f} [{r.bb_position}] Squeeze:{r.bb_squeeze}")
        logger.info(f"   Vol  : {r.volume_ratio:.2f}x [{r.volume_signal}]")
        if r.hammer or r.engulfing != "NONE":
            logger.info(f"   Pattern: Hammer={r.hammer} Engulfing={r.engulfing}")
        logger.info("="*55)
