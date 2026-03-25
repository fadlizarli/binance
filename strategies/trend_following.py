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
