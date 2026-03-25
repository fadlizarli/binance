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
