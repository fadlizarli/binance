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
