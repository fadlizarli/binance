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
