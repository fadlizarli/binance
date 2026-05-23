from core.indicators import IndicatorResult
from strategies.base import BaseStrategy, Signal

class SupportBounceStrategy(BaseStrategy):
    name = "support_bounce"
    def generate_signal(self, ind: IndicatorResult) -> Signal:
        sl, ss, r = 0, 0, []

        # Filter 1: Volume wajib minimal normal
        if ind.volume_ratio < 0.8:
            return self._wait(f"Volume terlalu lemah ({ind.volume_ratio:.2f}x)")

        # Filter 2: RSI terlalu ekstrem — bisa terus bergerak searah
        if ind.rsi < 20:
            return self._wait(f"RSI terlalu ekstrem ({ind.rsi:.1f}) — tunggu stabilisasi")
        if ind.rsi > 80:
            return self._wait(f"RSI terlalu ekstrem ({ind.rsi:.1f}) — tunggu stabilisasi")

        # BB Position
        if ind.bb_position == "AT_LOWER":   sl += 3; r.append("Harga di BB Lower ✅")
        elif ind.bb_position == "AT_UPPER": ss += 3; r.append("Harga di BB Upper ✅")

        # RSI
        if ind.rsi < 30:   sl += 3; r.append(f"RSI oversold ({ind.rsi:.1f}) 🔥")
        elif ind.rsi < 38: sl += 2
        elif ind.rsi > 70: ss += 3; r.append(f"RSI overbought ({ind.rsi:.1f}) 🔥")
        elif ind.rsi > 62: ss += 2

        # RSI Divergence — konfirmasi reversal
        if ind.rsi_divergence == "BULL_DIV":  sl += 3; r.append("Bullish divergence 🔥")
        elif ind.rsi_divergence == "BEAR_DIV": ss += 3; r.append("Bearish divergence 🔥")

        # Filter 3: EMA200 macro — boleh counter-trend HANYA dengan divergence
        if sl > ss and ind.close < ind.ema_200 and ind.rsi_divergence != "BULL_DIV":
            return self._wait("LONG kontra EMA200 tanpa divergence — skip")
        if ss > sl and ind.close > ind.ema_200 and ind.rsi_divergence != "BEAR_DIV":
            return self._wait("SHORT kontra EMA200 tanpa divergence — skip")

        # MACD cross konfirmasi
        if ind.macd_cross == "BULLISH_CROSS": sl += 1; r.append("MACD bullish cross ✅")
        elif ind.macd_cross == "BEARISH_CROSS": ss += 1

        # Volume bonus
        if ind.volume_signal == "HIGH":
            if sl > ss: sl += 1; r.append("Volume konfirmasi 💪")
            else:       ss += 1

        # Filter 4: Threshold lebih tinggi (naik dari 5 → 6)
        if sl >= 6 and sl > ss: return self._make_signal("LONG", min(sl/10, 1.0), " | ".join(r))
        if ss >= 6 and ss > sl: return self._make_signal("SHORT", min(ss/10, 1.0), " | ".join(r))
        return self._wait(f"Score kurang (L:{sl} S:{ss})")
