"""
strategies/trend_following.py
Strategi Trend Following:
- EMA stack (9 > 21 > 55) untuk konfirmasi tren
- Entry saat pullback ke EMA 21
- MACD cross sebagai konfirmasi tambahan
- Volume tinggi untuk validasi
"""
from core.indicators import IndicatorResult
from strategies.base import BaseStrategy, Signal


class TrendFollowingStrategy(BaseStrategy):
    """
    Trend Following menggunakan EMA stack + MACD + Volume.

    Setup LONG:
    - EMA 9 > EMA 21 > EMA 55 (bullish stack)
    - Harga pullback mendekati EMA 21 (dalam 0.5%)
    - MACD di atas 0 atau baru bullish cross
    - Volume normal atau tinggi

    Setup SHORT:
    - EMA 9 < EMA 21 < EMA 55 (bearish stack)
    - Harga pullback mendekati EMA 21
    - MACD di bawah 0 atau baru bearish cross
    """

    name = "trend_following"

    def generate_signal(self, ind: IndicatorResult) -> Signal:
        score_long  = 0
        score_short = 0
        reasons     = []

        # ---- EMA Trend ----
        if ind.ema_trend == "BULLISH":
            score_long += 3
            reasons.append("EMA bullish stack ✅")
        elif ind.ema_trend == "BEARISH":
            score_short += 3
            reasons.append("EMA bearish stack ✅")
        else:
            return self._wait("EMA tidak dalam trend jelas")

        # ---- Pullback ke EMA 21 ----
        ema21_dist = abs(ind.close - ind.ema_21) / ind.ema_21 * 100
        if ema21_dist <= 0.8:
            if ind.ema_trend == "BULLISH":
                score_long += 2
                reasons.append(f"Pullback ke EMA21 ({ema21_dist:.2f}%) ✅")
            else:
                score_short += 2
                reasons.append(f"Pullback ke EMA21 ({ema21_dist:.2f}%) ✅")
        elif ema21_dist > 3.0:
            return self._wait(f"Harga terlalu jauh dari EMA21 ({ema21_dist:.2f}%)")

        # ---- MACD ----
        if ind.macd_line > 0:
            score_long += 1
            reasons.append("MACD positif ✅")
        elif ind.macd_line < 0:
            score_short += 1

        if ind.macd_cross == "BULLISH_CROSS":
            score_long += 2
            reasons.append("MACD bullish cross 🔥")
        elif ind.macd_cross == "BEARISH_CROSS":
            score_short += 2

        # ---- RSI (hindari ekstrem) ----
        if 30 <= ind.rsi <= 65:
            score_long += 1
            reasons.append(f"RSI normal ({ind.rsi:.1f}) ✅")
        elif 35 <= ind.rsi <= 70:
            score_short += 1
        elif ind.rsi > 75:
            # Overbought, jangan long
            score_long = 0
            return self._wait(f"RSI overbought ({ind.rsi:.1f}), tunggu koreksi")

        # ---- Volume ----
        if ind.volume_signal == "HIGH":
            score_long  += 1
            score_short += 1
            reasons.append("Volume tinggi 💪")

        # ---- RSI Divergence (override bearish) ----
        if ind.rsi_divergence == "BEAR_DIV" and score_long > score_short:
            return self._wait(f"Bearish RSI divergence terdeteksi ⚠️")
        if ind.rsi_divergence == "BULL_DIV" and score_short > score_long:
            return self._wait(f"Bullish RSI divergence terdeteksi ⚠️")

        # ---- Final Decision ----
        min_score = 5
        if score_long >= min_score and score_long > score_short:
            strength = min(score_long / 9, 1.0)
            return self._make_signal("LONG", strength, " | ".join(reasons))

        if score_short >= min_score and score_short > score_long:
            strength = min(score_short / 9, 1.0)
            return self._make_signal("SHORT", strength, "Trend bearish " + " | ".join(reasons))

        return self._wait(
            f"Score tidak cukup (Long:{score_long} Short:{score_short}, min:{min_score})"
        )

