"""
risk/manager.py
Engine manajemen risiko.
"""
from typing import Optional, Tuple
from dataclasses import dataclass
from config import config
from utils.logger import logger


@dataclass
class RiskCalculation:
    valid: bool; side: str; entry_price: float
    stop_loss: float; take_profit: float
    quantity: float; risk_amount: float; reward_amount: float
    rr_actual: float; sl_distance_pct: float; tp_distance_pct: float
    reason: str = ""


class RiskManager:
    def __init__(self):
        self.risk_cfg = config.risk
        self.daily_pnl: float = 0.0
        self.daily_trades: int = 0
        self.session_high_balance: float = 0.0
        self._initialized: bool = False

    def calculate_position(self, side, entry_price, atr, balance,
                           risk_pct_override: float = None) -> RiskCalculation:
        _invalid = lambda reason: RiskCalculation(False, side, entry_price, 0, 0, 0, 0, 0, 0, 0, 0, reason)

        if not entry_price or entry_price <= 0:
            return _invalid("Entry price tidak valid")
        if not atr or atr <= 0:
            return _invalid("ATR tidak valid")
        if not balance or balance <= 0:
            return _invalid("Balance tidak valid")

        risk_pct    = risk_pct_override if risk_pct_override is not None else self.risk_cfg.risk_per_trade
        risk_amount = balance * (risk_pct / 100)
        sl_distance = atr * self.risk_cfg.sl_atr_multiplier
        tp_distance = sl_distance * self.risk_cfg.rr_ratio

        if side == "LONG":
            stop_loss   = entry_price - sl_distance
            take_profit = entry_price + tp_distance
        else:
            stop_loss   = entry_price + sl_distance
            take_profit = entry_price - tp_distance

        # Hitung quantity dasar dari risk
        quantity = risk_amount / sl_distance if sl_distance > 0 else 0

        # Batasi quantity agar margin tidak melebihi 20% balance
        max_notional = balance * 0.20 * config.trading.leverage
        max_qty      = max_notional / entry_price
        if quantity > max_qty:
            quantity = max_qty
            logger.debug(f"Qty dibatasi ke {quantity:.4f} (max 20% margin)")

        # Sesuaikan presisi quantity berdasarkan harga aset
        if entry_price >= 10000: quantity = round(quantity, 3)   # BTC
        elif entry_price >= 10:  quantity = round(quantity, 1)   # SOL, ETH
        elif entry_price >= 1:   quantity = round(quantity, 1)   # DOGE dll
        else:                    quantity = round(quantity, 0)

        if quantity <= 0:
            return _invalid("Quantity terlalu kecil setelah pembulatan")

        sl_pct    = (sl_distance / entry_price) * 100
        tp_pct    = (tp_distance / entry_price) * 100
        rr_actual = tp_distance / sl_distance if sl_distance > 0 else 0

        if rr_actual < self.risk_cfg.min_rr_ratio:
            return RiskCalculation(False, side, entry_price, stop_loss, take_profit,
                quantity, risk_amount, risk_amount*rr_actual, rr_actual, sl_pct, tp_pct,
                f"R:R terlalu rendah: {rr_actual:.2f}")

        if sl_pct > 5.0:
            return RiskCalculation(False, side, entry_price, stop_loss, take_profit,
                quantity, risk_amount, risk_amount*rr_actual, rr_actual, sl_pct, tp_pct,
                f"SL terlalu jauh: {sl_pct:.2f}%")

        logger.debug(f"Risk OK | {side} Entry:{entry_price} SL:{stop_loss:.2f}({sl_pct:.2f}%) TP:{take_profit:.2f} Qty:{quantity:.4f} Risk:${risk_amount:.2f}")
        return RiskCalculation(True, side, entry_price, stop_loss, take_profit,
            quantity, risk_amount, risk_amount*rr_actual, rr_actual, sl_pct, tp_pct)

    def set_initial_balance(self, balance: float):
        self.session_high_balance = balance
        self._initialized = True
        logger.info(f"💰 High watermark: ${balance:,.2f}")

    def can_trade(self, balance: float) -> Tuple[bool, str]:
        if not self._initialized:
            self.set_initial_balance(balance)

        if balance < self.risk_cfg.min_balance:
            return False, f"Balance ${balance:.2f} di bawah minimum ${self.risk_cfg.min_balance:.0f} — bot berhenti untuk lindungi modal"

        if self.daily_trades >= self.risk_cfg.max_trades_per_day:
            return False, f"Batas trade harian ({self.risk_cfg.max_trades_per_day}) tercapai"

        if self.session_high_balance > 0 and balance < self.session_high_balance:
            dd_pct = ((self.session_high_balance - balance) / self.session_high_balance) * 100
            if dd_pct >= self.risk_cfg.max_daily_drawdown:
                return False, f"Max drawdown {self.risk_cfg.max_daily_drawdown}% tercapai (saat ini: {dd_pct:.2f}%)"

        if balance > self.session_high_balance:
            self.session_high_balance = balance

        return True, "OK"

    def calculate_trailing_stop(self, side, price, current_sl, entry_price, atr, take_profit=None) -> Optional[float]:
        if not self.risk_cfg.trailing_stop_enabled:
            return None

        # Hitung progress ke TP (0.0 - 1.0)
        if take_profit:
            if side == "LONG":
                total    = take_profit - entry_price
                progress = (price - entry_price) / total if total > 0 else 0
            else:
                total    = entry_price - take_profit
                progress = (entry_price - price) / total if total > 0 else 0
        else:
            progress = 0

        # Belum 50% ke TP → jangan aktifkan trailing
        if progress < 0.5:
            return None

        # Dynamic multiplier berdasarkan progress ke TP
        # Semakin dekat ke TP → trailing semakin ketat
        if progress >= 0.90:
            multiplier = 0.5   # sangat dekat TP → sangat ketat
        elif progress >= 0.75:
            multiplier = 0.8   # dekat TP → ketat
        elif progress >= 0.60:
            multiplier = 1.2   # lewat 60% → agak ketat
        else:
            multiplier = 2.0   # baru 50% → longgar

        if side == "LONG":
            new_sl = price - atr * multiplier
            if new_sl > current_sl:
                return round(new_sl, 2)
        else:
            new_sl = price + atr * multiplier
            if new_sl < current_sl:
                return round(new_sl, 2)
        return None

    def should_move_to_breakeven(self, side, price, entry_price, take_profit) -> bool:
        if side == "LONG":
            return price >= entry_price + (take_profit - entry_price) * 0.5
        return price <= entry_price - (entry_price - take_profit) * 0.5

    def register_trade_open(self):
        self.daily_trades += 1

    def register_trade_close(self, pnl: float):
        self.daily_pnl += pnl

    def reset_daily(self):
        logger.info(f"Reset harian | Trades:{self.daily_trades} PnL:${self.daily_pnl:+.2f}")
        self.daily_pnl    = 0.0
        self.daily_trades = 0
