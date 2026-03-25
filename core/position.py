from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class Position:
    id: str; symbol: str; side: str
    entry_price: float; quantity: float
    stop_loss: float; take_profit: float
    risk_amount: float; strategy: str; leverage: int
    open_time: datetime = field(default_factory=datetime.now)
    entry_order_id: Optional[str] = None
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    partial_tp_done: bool = False
    sl_moved_to_be: bool = False
    pnl: float = 0.0; status: str = "OPEN"

    @property
    def close_side(self): return "SELL" if self.side == "LONG" else "BUY"

    def calculate_pnl(self, price: float) -> float:
        if self.side == "LONG":
            self.pnl = round((price - self.entry_price) * self.quantity, 4)
        else:
            self.pnl = round((self.entry_price - price) * self.quantity, 4)
        return self.pnl

    def __str__(self):
        return f"[{self.side}] {self.symbol} Entry:${self.entry_price:.2f} SL:${self.stop_loss:.2f} TP:${self.take_profit:.2f} PnL:${self.pnl:+.2f}"

@dataclass
class TradeRecord:
    position: Position; exit_price: float
    exit_time: datetime = field(default_factory=datetime.now)
    exit_reason: str = ""; final_pnl: float = 0.0
