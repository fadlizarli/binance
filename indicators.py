"""
core/indicators.py
Engine kalkulasi indikator teknikal.
Semua indikator yang dipakai bot ada di sini.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

try:
    import ta
    HAS_TA = True
except ImportError:
    HAS_TA = False


@dataclass
class IndicatorResult:
    """Hasil kalkulasi semua indikator untuk 1 candle."""
    # EMA
    ema_9: float = 0.0
    ema_21: float = 0.0
    ema_55: float = 0.0
    ema_200: float = 0.0
    ema_trend: str = "NEUTRAL"   # BULLISH / BEARISH / NEUTRAL

    # RSI
    rsi: float = 50.0
    rsi_signal: str = "NEUTRAL"  # OVERSOLD / OVERBOUGHT / NEUTRAL
    rsi_divergence: str = "NONE" # BULL_DIV / BEAR_DIV / NONE

    # MACD
    macd_line: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    macd_cross: str = "NONE"     # BULLISH_CROSS / BEARISH_CROSS / NONE

    # Bollinger Bands
    bb_upper: float = 0.0
    bb_middle: float = 0.0
    bb_lower: float = 0.0
    bb_squeeze: bool = False
    bb_position: str = "MID"     # ABOVE / BELOW / AT_UPPER / AT_LOWER / MID

    # ATR (untuk kalkulasi SL)
    atr: float = 0.0
    atr_percent: float = 0.0

    # Volume
    volume_ratio: float = 1.0    # volume / rata-rata volume
    volume_signal: str = "NORMAL"  # HIGH / LOW / NORMAL

    # Harga terakhir
    close: float = 0.0
    high: float = 0.0
    low: float = 0.0


class IndicatorEngine:
    """Kalkulasi semua indikator teknikal dari DataFrame OHLCV."""

    def __init__(self):
        self.last_result: Optional[IndicatorResult] = None

    def calculate(self, df: pd.DataFrame) -> Optional[IndicatorResult]:
        """
        Hitung semua indikator dari DataFrame OHLCV.
        Butuh minimal 200 baris data untuk akurasi.
        """
        if df is None or len(df) < 55:
            return None

        result = IndicatorResult()

        try:
            close = df["close"]
            high  = df["high"]
            low   = df["low"]
            vol   = df["volume"]

            # ---- EMA ----
            result.ema_9   = self._ema(close, 9)
            result.ema_21  = self._ema(close, 21)
            result.ema_55  = self._ema(close, 55)
            result.ema_200 = self._ema(close, min(200, len(df) - 1))
            result.ema_trend = self._ema_trend(
                result.ema_9, result.ema_21, result.ema_55
            )

            # ---- RSI ----
            result.rsi = self._rsi(close, 14)
            result.rsi_signal = self._rsi_signal(result.rsi)
            result.rsi_divergence = self._rsi_divergence(close, df)

            # ---- MACD ----
            macd_line, macd_signal, macd_hist = self._macd(close)
            result.macd_line   = macd_line
            result.macd_signal = macd_signal
            result.macd_hist   = macd_hist
            result.macd_cross  = self._macd_cross(df)

            # ---- Bollinger Bands ----
            bb_upper, bb_mid, bb_lower = self._bollinger(close)
            result.bb_upper    = bb_upper
            result.bb_middle   = bb_mid
            result.bb_lower    = bb_lower
            result.bb_squeeze  = self._bb_squeeze(close)
            result.bb_position = self._bb_position(close.iloc[-1], bb_upper, bb_lower)

            # ---- ATR ----
            result.atr = self._atr(high, low, close, 14)
            result.atr_percent = (result.atr / close.iloc[-1]) * 100

            # ---- Volume ----
            result.volume_ratio  = self._volume_ratio(vol)
            result.volume_signal = self._volume_signal(result.volume_ratio)

            # ---- Harga ----
            result.close = close.iloc[-1]
            result.high  = high.iloc[-1]
            result.low   = low.iloc[-1]

            self.last_result = result
            return result

        except Exception as e:
            from utils.logger import logger
            logger.error(f"Error kalkulasi indikator: {e}")
            return None

    # ----------------------------------------------------------
    # EMA
    # ----------------------------------------------------------
    @staticmethod
    def _ema(series: pd.Series, period: int) -> float:
        k = 2 / (period + 1)
        ema = series.iloc[0]
        for price in series.iloc[1:]:
            ema = price * k + ema * (1 - k)
        return round(ema, 6)

    @staticmethod
    def _ema_trend(e9: float, e21: float, e55: float) -> str:
        if e9 > e21 > e55:
            return "BULLISH"
        elif e9 < e21 < e55:
            return "BEARISH"
        return "NEUTRAL"

    # ----------------------------------------------------------
    # RSI
    # ----------------------------------------------------------
    @staticmethod
    def _rsi(series: pd.Series, period: int = 14) -> float:
        delta = series.diff().dropna()
        gain  = delta.clip(lower=0)
        loss  = (-delta).clip(lower=0)
        avg_gain = gain.rolling(period).mean().iloc[-1]
        avg_loss = loss.rolling(period).mean().iloc[-1]
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100 - 100 / (1 + rs), 2)

    @staticmethod
    def _rsi_signal(rsi: float) -> str:
        if rsi < 30:
            return "OVERSOLD"
        elif rsi > 70:
            return "OVERBOUGHT"
        elif rsi < 40:
            return "WEAK"
        elif rsi > 60:
            return "STRONG"
        return "NEUTRAL"

    @staticmethod
    def _rsi_divergence(close: pd.Series, df: pd.DataFrame) -> str:
        """
        Deteksi RSI divergence sederhana.
        Bandingkan 2 swing terakhir.
        """
        if len(df) < 30:
            return "NONE"
        try:
            recent = close.iloc[-20:]
            rsi_recent = pd.Series([
                IndicatorEngine._rsi(close.iloc[:i+1], 14)
                for i in range(len(close) - 20, len(close))
            ])
            price_change = recent.iloc[-1] - recent.iloc[0]
            rsi_change   = rsi_recent.iloc[-1] - rsi_recent.iloc[0]

            # Bearish divergence: harga naik tapi RSI turun
            if price_change > 0 and rsi_change < -5:
                return "BEAR_DIV"
            # Bullish divergence: harga turun tapi RSI naik
            if price_change < 0 and rsi_change > 5:
                return "BULL_DIV"
        except Exception:
            pass
        return "NONE"

    # ----------------------------------------------------------
    # MACD
    # ----------------------------------------------------------
    @staticmethod
    def _macd(series: pd.Series,
              fast: int = 12, slow: int = 26, signal: int = 9):
        ema_fast   = series.ewm(span=fast, adjust=False).mean()
        ema_slow   = series.ewm(span=slow, adjust=False).mean()
        macd_line  = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram  = macd_line - signal_line
        return (
            round(macd_line.iloc[-1], 6),
            round(signal_line.iloc[-1], 6),
            round(histogram.iloc[-1], 6),
        )

    @staticmethod
    def _macd_cross(df: pd.DataFrame) -> str:
        """Deteksi golden/death cross MACD pada 2 candle terakhir."""
        if len(df) < 30:
            return "NONE"
        close = df["close"]
        ema_fast   = close.ewm(span=12, adjust=False).mean()
        ema_slow   = close.ewm(span=26, adjust=False).mean()
        macd       = ema_fast - ema_slow
        signal_    = macd.ewm(span=9, adjust=False).mean()

        prev_diff = macd.iloc[-2] - signal_.iloc[-2]
        curr_diff = macd.iloc[-1] - signal_.iloc[-1]

        if prev_diff < 0 and curr_diff >= 0:
            return "BULLISH_CROSS"
        if prev_diff > 0 and curr_diff <= 0:
            return "BEARISH_CROSS"
        return "NONE"

    # ----------------------------------------------------------
    # BOLLINGER BANDS
    # ----------------------------------------------------------
    @staticmethod
    def _bollinger(series: pd.Series, period: int = 20, std: float = 2.0):
        mid   = series.rolling(period).mean()
        sigma = series.rolling(period).std()
        upper = mid + std * sigma
        lower = mid - std * sigma
        return (
            round(upper.iloc[-1], 6),
            round(mid.iloc[-1], 6),
            round(lower.iloc[-1], 6),
        )

    @staticmethod
    def _bb_squeeze(series: pd.Series, period: int = 20) -> bool:
        """Deteksi BB squeeze: bandwidth < rata-rata bandwidth 50 periode."""
        if len(series) < 55:
            return False
        mid   = series.rolling(period).mean()
        sigma = series.rolling(period).std()
        bw    = (2 * 2 * sigma) / mid  # normalized bandwidth
        return bw.iloc[-1] < bw.rolling(50).mean().iloc[-1] * 0.7

    @staticmethod
    def _bb_position(price: float, upper: float, lower: float) -> str:
        if price >= upper:
            return "AT_UPPER"
        elif price <= lower:
            return "AT_LOWER"
        elif price > (upper + lower) / 2:
            return "ABOVE_MID"
        return "BELOW_MID"

    # ----------------------------------------------------------
    # ATR
    # ----------------------------------------------------------
    @staticmethod
    def _atr(high: pd.Series, low: pd.Series,
             close: pd.Series, period: int = 14) -> float:
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)
        return round(tr.rolling(period).mean().iloc[-1], 6)

    # ----------------------------------------------------------
    # VOLUME
    # ----------------------------------------------------------
    @staticmethod
    def _volume_ratio(vol: pd.Series, period: int = 20) -> float:
        avg = vol.rolling(period).mean().iloc[-1]
        if avg == 0:
            return 1.0
        return round(vol.iloc[-1] / avg, 2)

    @staticmethod
    def _volume_signal(ratio: float) -> str:
        if ratio >= 1.5:
            return "HIGH"
        elif ratio <= 0.6:
            return "LOW"
        return "NORMAL"

    # ----------------------------------------------------------
    # SUMMARY
    # ----------------------------------------------------------
    def print_summary(self, result: IndicatorResult):
        """Print ringkasan indikator ke console."""
        from utils.logger import logger
        logger.info("=" * 55)
        logger.info(f"📊 INDIKATOR | Close: ${result.close:,.2f}")
        logger.info(f"   EMA  9/21/55 : {result.ema_9:.2f} / {result.ema_21:.2f} / {result.ema_55:.2f}  [{result.ema_trend}]")
        logger.info(f"   RSI  14      : {result.rsi:.1f}  [{result.rsi_signal}]  Div: {result.rsi_divergence}")
        logger.info(f"   MACD         : {result.macd_line:.4f} | Hist: {result.macd_hist:.4f}  [{result.macd_cross}]")
        logger.info(f"   BB           : {result.bb_lower:.2f} / {result.bb_middle:.2f} / {result.bb_upper:.2f}  [{result.bb_position}]  Squeeze: {result.bb_squeeze}")
        logger.info(f"   ATR (14)     : {result.atr:.2f}  ({result.atr_percent:.2f}%)")
        logger.info(f"   Volume       : {result.volume_ratio:.2f}x  [{result.volume_signal}]")
        logger.info("=" * 55)

