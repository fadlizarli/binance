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
