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
