"""
risk/manager.py
Engine manajemen risiko.
Kalkulasi position size, SL, TP, dan validasi kondisi trading.
"""
from typing import Optional, Tuple
from dataclasses import dataclass

from config import config
from utils.logger import logger


@dataclass
class RiskCalculation:
    """Hasil kalkulasi risiko untuk satu trade."""
    valid: bool
    side: str
    entry_price: float
    stop_loss: float
    take_profit: float
    quantity: float         # Jumlah kontrak
    risk_amount: float      # USDT yang dirisiko
    reward_amount: float    # Potensi profit USDT
    rr_actual: float        # R:R aktual
    sl_distance_pct: float  # Jarak SL dalam %
    tp_distance_pct: float  # Jarak TP dalam %
    reason: str = ""        # Alasan jika invalid


class RiskManager:
    """
    Manajemen risiko lengkap.
    Kalkulasi position size, validasi trade, dan monitor drawdown.
    """

    def __init__(self):
        self.risk_cfg = config.risk
        self.daily_pnl: float = 0.0
        self.daily_trades: int = 0
        self.session_high_balance: float = 0.0

    def calculate_position(
        self,
        side: str,
        entry_price: float,
        atr: float,
        balance: float,
    ) -> RiskCalculation:
        """
        Hitung position size, SL, dan TP berdasarkan ATR dan risk %.
        
        Args:
            side        : 'LONG' atau 'SHORT'
            entry_price : Harga masuk
            atr         : Average True Range saat ini
            balance     : Saldo akun USDT
        """
        risk_amount  = balance * (self.risk_cfg.risk_per_trade / 100)
        sl_distance  = atr * self.risk_cfg.sl_atr_multiplier
        tp_distance  = sl_distance * self.risk_cfg.rr_ratio

        if side == "LONG":
            stop_loss   = entry_price - sl_distance
            take_profit = entry_price + tp_distance
        else:
            stop_loss   = entry_price + sl_distance
            take_profit = entry_price - tp_distance

        # Position size = risiko / jarak SL (tanpa leverage karena futures)
        quantity = risk_amount / sl_distance

        sl_pct = (sl_distance / entry_price) * 100
        tp_pct = (tp_distance / entry_price) * 100
        rr_actual = tp_distance / sl_distance

        # Validasi minimum R:R
        if rr_actual < self.risk_cfg.min_rr_ratio:
            return RiskCalculation(
                valid=False, side=side, entry_price=entry_price,
                stop_loss=stop_loss, take_profit=take_profit,
                quantity=quantity, risk_amount=risk_amount,
                reward_amount=risk_amount * rr_actual,
                rr_actual=rr_actual,
                sl_distance_pct=sl_pct, tp_distance_pct=tp_pct,
                reason=f"R:R terlalu rendah: {rr_actual:.2f} (min {self.risk_cfg.min_rr_ratio})"
            )

        # Validasi SL tidak terlalu jauh (maks 5%)
        if sl_pct > 5.0:
            return RiskCalculation(
                valid=False, side=side, entry_price=entry_price,
                stop_loss=stop_loss, take_profit=take_profit,
                quantity=quantity, risk_amount=risk_amount,
                reward_amount=risk_amount * rr_actual,
                rr_actual=rr_actual,
                sl_distance_pct=sl_pct, tp_distance_pct=tp_pct,
                reason=f"SL terlalu jauh: {sl_pct:.2f}% (max 5%)"
            )

        logger.debug(
            f"✅ Risk Calc | {side} | Entry: {entry_price:.2f} | "
            f"SL: {stop_loss:.2f} ({sl_pct:.2f}%) | "
            f"TP: {take_profit:.2f} ({tp_pct:.2f}%) | "
            f"Qty: {quantity:.4f} | Risk: ${risk_amount:.2f} | R:R {rr_actual:.2f}"
        )

        return RiskCalculation(
            valid=True, side=side, entry_price=entry_price,
            stop_loss=stop_loss, take_profit=take_profit,
            quantity=quantity, risk_amount=risk_amount,
            reward_amount=risk_amount * rr_actual,
            rr_actual=rr_actual,
            sl_distance_pct=sl_pct, tp_distance_pct=tp_pct,
        )

    def can_trade(self, balance: float) -> Tuple[bool, str]:
        """
        Cek apakah kondisi memungkinkan untuk membuka trade baru.
        Return: (boleh_trade, alasan)
        """
        # Cek limit trade harian
        if self.daily_trades >= self.risk_cfg.max_trades_per_day:
            return False, f"Batas trade harian tercapai ({self.risk_cfg.max_trades_per_day})"

        # Cek max drawdown harian
        if self.session_high_balance > 0:
            dd_pct = ((self.session_high_balance - balance) /
                       self.session_high_balance) * 100
            if dd_pct >= self.risk_cfg.max_daily_drawdown:
                return False, (
                    f"Max drawdown harian {self.risk_cfg.max_daily_drawdown}% tercapai "
                    f"(drawdown saat ini: {dd_pct:.2f}%)"
                )

        # Update high watermark
        if balance > self.session_high_balance:
            self.session_high_balance = balance

        return True, "OK"

    def calculate_trailing_stop(
        self,
        side: str,
        current_price: float,
        current_sl: float,
        entry_price: float,
        atr: float,
    ) -> Optional[float]:
        """
        Hitung trailing stop baru.
        Aktif setelah profit >= 2R.
        Return: SL baru atau None jika belum perlu digeser.
        """
        if not self.risk_cfg.trailing_stop_enabled:
            return None

        if side == "LONG":
            new_sl = current_price - atr * self.risk_cfg.sl_atr_multiplier
            # Hanya geser SL naik, tidak pernah turun
            if new_sl > current_sl and current_price > entry_price * 1.005:
                return round(new_sl, 2)
        else:
            new_sl = current_price + atr * self.risk_cfg.sl_atr_multiplier
            # Hanya geser SL turun, tidak pernah naik
            if new_sl < current_sl and current_price < entry_price * 0.995:
                return round(new_sl, 2)

        return None

    def should_move_to_breakeven(
        self, side: str, current_price: float,
        entry_price: float, take_profit: float
    ) -> bool:
        """
        Cek apakah SL harus dipindah ke breakeven.
        Aktif saat profit sudah mencapai 50% jarak ke TP.
        """
        if side == "LONG":
            half_way = entry_price + (take_profit - entry_price) * 0.5
            return current_price >= half_way
        else:
            half_way = entry_price - (entry_price - take_profit) * 0.5
            return current_price <= half_way

    def register_trade_open(self):
        """Catat pembukaan trade baru."""
        self.daily_trades += 1

    def register_trade_close(self, pnl: float):
        """Catat penutupan trade dan update statistik harian."""
        self.daily_pnl += pnl

    def reset_daily(self):
        """Reset counter harian (panggil setiap awal hari)."""
        logger.info(
            f"Reset harian | Trades: {self.daily_trades} | "
            f"PnL: ${self.daily_pnl:+.2f}"
        )
        self.daily_pnl = 0.0
        self.daily_trades = 0

