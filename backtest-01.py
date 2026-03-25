"""
backtest.py
Backtesting sederhana — uji strategi pada data historis sebelum live.
Jalankan: python backtest.py
"""
import sys
import os
import random
from datetime import datetime, timedelta
from typing import List

import pandas as pd
import numpy as np

# Tambah root ke path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.indicators import IndicatorEngine
from core.position import Position, TradeRecord
from risk.manager import RiskManager
from strategies import get_strategy
from config import config
from utils.logger import logger


def generate_mock_data(n: int = 500, base_price: float = 67000) -> pd.DataFrame:
    """
    Generate data OHLCV simulasi untuk backtesting.
    (Ganti dengan data real dari CSV atau Binance API)
    """
    dates = [datetime.now() - timedelta(hours=n - i) for i in range(n)]
    closes = [base_price]

    for _ in range(n - 1):
        change = random.gauss(0, 0.008)
        closes.append(closes[-1] * (1 + change))

    opens  = [c * random.uniform(0.997, 1.003) for c in closes]
    highs  = [max(o, c) * random.uniform(1.001, 1.015) for o, c in zip(opens, closes)]
    lows   = [min(o, c) * random.uniform(0.985, 0.999) for o, c in zip(opens, closes)]
    vols   = [random.uniform(800, 3000) for _ in closes]

    df = pd.DataFrame({
        "open":   opens,
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "volume": vols,
    }, index=pd.DatetimeIndex(dates))

    return df


def run_backtest(
    strategy_name: str = "trend_following",
    initial_balance: float = 1000.0,
    data: pd.DataFrame = None,
) -> dict:
    """
    Jalankan backtest pada DataFrame OHLCV.
    """
    if data is None:
        logger.info("Menggunakan data simulasi...")
        data = generate_mock_data()

    logger.info(f"🔬 BACKTEST DIMULAI")
    logger.info(f"   Strategi  : {strategy_name}")
    logger.info(f"   Balance   : ${initial_balance:,.2f}")
    logger.info(f"   Candles   : {len(data)}")
    logger.info("=" * 55)

    strategy     = get_strategy(strategy_name)
    indicator_eng = IndicatorEngine()
    risk_mgr     = RiskManager()
    risk_mgr.session_high_balance = initial_balance

    balance       = initial_balance
    trades: List[TradeRecord] = []
    open_pos      = None
    warmup        = 60  # candle awal untuk warmup indikator

    for i in range(warmup, len(data)):
        df_slice = data.iloc[:i + 1]
        ind      = indicator_eng.calculate(df_slice)
        if ind is None:
            continue

        current_price = data["close"].iloc[i]
        ind.close     = current_price

        # --- Manage open position ---
        if open_pos:
            pnl = open_pos.calculate_pnl(current_price)
            closed = False
            reason = ""

            if open_pos.side == "LONG":
                if current_price <= open_pos.stop_loss:
                    pnl = -open_pos.risk_amount
                    closed, reason = True, "STOP_LOSS"
                elif current_price >= open_pos.take_profit:
                    pnl = open_pos.risk_amount * config.risk.rr_ratio
                    closed, reason = True, "TAKE_PROFIT"
            else:
                if current_price >= open_pos.stop_loss:
                    pnl = -open_pos.risk_amount
                    closed, reason = True, "STOP_LOSS"
                elif current_price <= open_pos.take_profit:
                    pnl = open_pos.risk_amount * config.risk.rr_ratio
                    closed, reason = True, "TAKE_PROFIT"

            if closed:
                balance += pnl
                risk_mgr.register_trade_close(pnl)
                trades.append(TradeRecord(
                    position=open_pos,
                    exit_price=current_price,
                    exit_reason=reason,
                    final_pnl=pnl,
                ))
                open_pos = None
            continue

        # --- Cek sinyal baru ---
        can_trade, _ = risk_mgr.can_trade(balance)
        if not can_trade:
            continue

        signal = strategy.generate_signal(ind)
        if signal.action == "WAIT":
            continue

        risk_calc = risk_mgr.calculate_position(
            side=signal.action,
            entry_price=current_price,
            atr=ind.atr,
            balance=balance,
        )
        if not risk_calc.valid:
            continue

        import uuid
        open_pos = Position(
            id=str(uuid.uuid4())[:8],
            symbol="BTCUSDT",
            side=signal.action,
            entry_price=current_price,
            quantity=risk_calc.quantity,
            stop_loss=risk_calc.stop_loss,
            take_profit=risk_calc.take_profit,
            risk_amount=risk_calc.risk_amount,
            strategy=strategy_name,
            leverage=config.trading.leverage,
        )
        risk_mgr.register_trade_open()

    # --- Hitung statistik ---
    total      = len(trades)
    wins       = [t for t in trades if t.final_pnl > 0]
    losses     = [t for t in trades if t.final_pnl <= 0]
    total_pnl  = sum(t.final_pnl for t in trades)
    win_rate   = (len(wins) / total * 100) if total > 0 else 0
    avg_win    = (sum(t.final_pnl for t in wins) / len(wins)) if wins else 0
    avg_loss   = (sum(t.final_pnl for t in losses) / len(losses)) if losses else 0
    profit_factor = (
        abs(sum(t.final_pnl for t in wins)) /
        abs(sum(t.final_pnl for t in losses))
        if losses and sum(t.final_pnl for t in losses) != 0 else 0
    )
    roi = ((balance - initial_balance) / initial_balance) * 100

    # Hitung max drawdown
    equity_curve = [initial_balance]
    running_bal  = initial_balance
    for t in trades:
        running_bal += t.final_pnl
        equity_curve.append(running_bal)

    peak = initial_balance
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    results = {
        "strategy":       strategy_name,
        "total_trades":   total,
        "win_count":      len(wins),
        "loss_count":     len(losses),
        "win_rate":       round(win_rate, 2),
        "total_pnl":      round(total_pnl, 2),
        "roi_pct":        round(roi, 2),
        "avg_win":        round(avg_win, 2),
        "avg_loss":       round(avg_loss, 2),
        "profit_factor":  round(profit_factor, 2),
        "max_drawdown":   round(max_dd, 2),
        "final_balance":  round(balance, 2),
    }

    # Print hasil
    logger.info("=" * 55)
    logger.info(f"📊 HASIL BACKTEST — {strategy_name.upper()}")
    logger.info(f"   Total Trade    : {total}")
    logger.info(f"   Win / Loss     : {len(wins)} / {len(losses)}")
    logger.info(f"   Win Rate       : {win_rate:.1f}%")
    logger.info(f"   Total PnL      : ${'+'if total_pnl >= 0 else ''}{total_pnl:.2f}")
    logger.info(f"   ROI            : {'+'if roi >= 0 else ''}{roi:.2f}%")
    logger.info(f"   Avg Win        : ${avg_win:.2f}")
    logger.info(f"   Avg Loss       : ${avg_loss:.2f}")
    logger.info(f"   Profit Factor  : {profit_factor:.2f}")
    logger.info(f"   Max Drawdown   : {max_dd:.2f}%")
    logger.info(f"   Final Balance  : ${balance:,.2f}")
    logger.info("=" * 55)

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CryptoBot Backtester")
    parser.add_argument(
        "--strategy",
        choices=["trend_following", "support_bounce", "breakout", "scalping"],
        default="trend_following",
        help="Strategi yang ingin ditest"
    )
    parser.add_argument("--balance", type=float, default=1000.0, help="Modal awal USDT")
    parser.add_argument("--candles", type=int, default=500, help="Jumlah candle simulasi")
    args = parser.parse_args()

    data = generate_mock_data(n=args.candles)
    run_backtest(args.strategy, args.balance, data)

