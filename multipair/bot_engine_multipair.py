"""
core/bot_engine_multipair.py
Bot engine versi multi-pair.
Cara pakai: Ganti isi core/bot_engine.py dengan file ini
"""
import uuid
import time
from datetime import date, datetime
from typing import Dict, Optional

from config import config
from core.indicators import IndicatorEngine
from core.position import Position, TradeRecord
from exchange.binance_client import BinanceClient
from risk.manager import RiskManager
from strategies.trend_following import TrendFollowingStrategy
from utils.logger import logger, trade_logger
from utils.notifier import TelegramNotifier
from utils.claude_filter import claude_validate


STRATEGY_MAP = {
    "trend_following": TrendFollowingStrategy,
}


class MultipairBotEngine:
    """
    Bot engine yang support trading multiple pair sekaligus.
    Setiap pair punya posisi, risk manager, dan state sendiri.
    """

    def __init__(self):
        self.cfg        = config
        self.exchange   = BinanceClient()
        self.indicators = IndicatorEngine()
        self.notifier   = TelegramNotifier(
            self.cfg.notification.telegram_token,
            self.cfg.notification.telegram_chat_id,
        )

        # Strategy per pair
        strategy_cls = STRATEGY_MAP.get(self.cfg.strategy, TrendFollowingStrategy)
        self.strategies: Dict[str, object] = {
            symbol: strategy_cls() for symbol in self.cfg.trading.symbols
        }

        # Posisi aktif per pair
        self.open_positions: Dict[str, Optional[Position]] = {
            symbol: None for symbol in self.cfg.trading.symbols
        }

        # Risk manager per pair
        self.risk_managers: Dict[str, RiskManager] = {
            symbol: RiskManager() for symbol in self.cfg.trading.symbols
        }

        # Trade history per pair
        self.trade_histories: Dict[str, list] = {
            symbol: [] for symbol in self.cfg.trading.symbols
        }

        # Balance
        self.balance: float = 0.0
        self._last_reset_date = date.today()

    # ─── Start ───────────────────────────────────────────────────────
    def start(self):
        logger.info("=" * 55)
        logger.info(f"🚀 MULTI-PAIR BOT DIMULAI")
        logger.info(f"   Pairs     : {', '.join(self.cfg.trading.symbols)}")
        logger.info(f"   Strategi  : {self.cfg.strategy.upper()}")
        logger.info(f"   Leverage  : {self.cfg.trading.leverage}x")
        logger.info(f"   Mode      : {self.cfg.trading.mode.upper()}")
        logger.info("=" * 55)

        # Init exchange & balance
        self._init_balance()
        for symbol in self.cfg.trading.symbols:
            self.exchange.set_leverage(symbol, self.cfg.trading.leverage)
            self._recover_position(symbol)

        while True:
            try:
                self._daily_reset_check()
                for symbol in self.cfg.trading.symbols:
                    self._tick(symbol)
                time.sleep(self.cfg.check_interval)
            except KeyboardInterrupt:
                logger.info("Bot dihentikan.")
                self._print_summary()
                break
            except Exception as e:
                logger.error(f"Error di loop utama [{symbol}]: {e}", exc_info=True)
                time.sleep(10)

    # ─── Init ────────────────────────────────────────────────────────
    def _init_balance(self):
        fetched = self.exchange.get_account_balance()
        self.balance = fetched if fetched and fetched > 0 else 1000.0
        for symbol in self.cfg.trading.symbols:
            # Bagi balance rata per pair
            pair_balance = self.balance / len(self.cfg.trading.symbols)
            self.risk_managers[symbol].set_initial_balance(pair_balance)
        logger.info(f"💰 Balance: ${self.balance:,.2f} USDT")
        logger.info(f"   Per pair: ${self.balance/len(self.cfg.trading.symbols):,.2f} USDT")

    def _recover_position(self, symbol: str):
        positions = self.exchange.get_open_positions(symbol)
        if not positions:
            return
        for p in positions:
            amt = float(p.get("positionAmt", 0))
            if amt == 0:
                continue
            side  = "LONG" if amt > 0 else "SHORT"
            entry = float(p.get("entryPrice", 0))
            liq   = float(p.get("liquidationPrice", 0))
            atr   = 0.5  # default
            sl    = entry - atr * self.cfg.risk.sl_atr_multiplier if side == "LONG" else entry + atr * self.cfg.risk.sl_atr_multiplier
            tp    = entry + atr * self.cfg.risk.sl_atr_multiplier * self.cfg.risk.rr_ratio if side == "LONG" else entry - atr * self.cfg.risk.sl_atr_multiplier * self.cfg.risk.rr_ratio
            self.open_positions[symbol] = Position(
                id=str(uuid.uuid4())[:8], symbol=symbol, side=side,
                entry_price=entry, quantity=abs(amt),
                stop_loss=sl, take_profit=tp,
                risk_amount=self.balance * self.cfg.risk.risk_per_trade / 100,
                strategy=self.cfg.strategy, leverage=self.cfg.trading.leverage,
            )
            logger.info(f"♻️  Recovery [{symbol}]: {side} @ ${entry:.2f} | Qty:{abs(amt)}")

    # ─── Tick per pair ────────────────────────────────────────────────
    def _tick(self, symbol: str):
        pos          = self.open_positions.get(symbol)
        risk_manager = self.risk_managers[symbol]
        strategy     = self.strategies[symbol]

        # Update balance
        current_balance = self.exchange.get_account_balance()
        if current_balance and current_balance > 0:
            self.balance = current_balance
            pair_balance = self.balance / len(self.cfg.trading.symbols)
            risk_manager.set_initial_balance(pair_balance)

        # Manage posisi terbuka
        if pos:
            self._manage_position(symbol, pos)
            return

        # Cek apakah boleh trade
        can_trade, reason = risk_manager.can_trade(self.balance / len(self.cfg.trading.symbols))
        if not can_trade:
            logger.debug(f"[{symbol}] Skip: {reason}")
            return

        # Ambil data & hitung indikator
        df = self.exchange.get_klines(symbol, self.cfg.trading.timeframe, limit=200)
        if df is None or len(df) < 50:
            return

        ind = self.indicators.calculate(df)
        if ind is None:
            return

        # Generate sinyal
        signal = strategy.generate_signal(ind)
        if signal.action == "WAIT":
            logger.info(f"[{symbol}] ⏳ WAIT | {signal.reason}")
            return

        # Filter jam trading
        from datetime import datetime
        import pytz
        wib  = pytz.timezone("Asia/Jakarta")
        hour = datetime.now(wib).hour
        if not (14 <= hour <= 23):
            logger.debug(f"[{symbol}] ⏰ Di luar jam trading ({hour}:00 WIB)")
            return

        # HTF Filter
        htf_trend = "NEUTRAL"
        try:
            df_4h = self.exchange.get_klines(symbol, "4h", limit=100)
            if df_4h is not None:
                ind_4h    = self.indicators.calculate(df_4h)
                htf_trend = ind_4h.ema_trend if ind_4h else "NEUTRAL"
                logger.debug(f"[{symbol}] HTF 4h: {htf_trend}")
        except:
            pass

        if htf_trend == "BULLISH" and signal.action == "SHORT":
            logger.info(f"[{symbol}] ⛔ HTF BULLISH — skip SHORT")
            return
        if htf_trend == "BEARISH" and signal.action == "LONG":
            logger.info(f"[{symbol}] ⛔ HTF BEARISH — skip LONG")
            return

        # Hitung risk
        pair_balance = self.balance / len(self.cfg.trading.symbols)
        risk_calc = risk_manager.calculate(
            side=signal.action, entry_price=ind.close,
            atr=ind.atr, balance=pair_balance,
        )
        if not risk_calc.valid:
            return

        # Claude filter
        try:
            ind.htf_trend = htf_trend
        except:
            pass

        if self.cfg.notification.claude_filter_enabled and self.cfg.notification.anthropic_api_key:
            approved = claude_validate(
                signal.action, ind,
                self.cfg.notification.anthropic_api_key,
                min_confidence=6
            )
            if not approved:
                return

        self._open_position(symbol, signal, risk_calc, ind.atr)

    # ─── Open Position ────────────────────────────────────────────────
    def _open_position(self, symbol: str, signal, risk_calc, atr: float):
        side     = signal.action
        buy_sell = "BUY" if side == "LONG" else "SELL"

        entry_order = self.exchange.place_market_order(symbol, buy_sell, risk_calc.quantity)
        if not entry_order:
            logger.error(f"[{symbol}] Gagal membuka posisi!")
            return

        actual_entry = float(entry_order.get("avgPrice", risk_calc.entry_price))
        if actual_entry == 0:
            actual_entry = risk_calc.entry_price

        pos = Position(
            id=str(uuid.uuid4())[:8], symbol=symbol, side=side,
            entry_price=actual_entry, quantity=risk_calc.quantity,
            stop_loss=risk_calc.stop_loss, take_profit=risk_calc.take_profit,
            risk_amount=risk_calc.risk_amount,
            strategy=self.strategies[symbol].name,
            leverage=self.cfg.trading.leverage,
        )

        self.open_positions[symbol] = pos
        self.risk_managers[symbol].register_trade_open()

        trade_logger.info(
            f"OPEN | {side} | {symbol} | Entry:{actual_entry:.2f} | "
            f"SL:{risk_calc.stop_loss:.2f} | TP:{risk_calc.take_profit:.2f} | "
            f"Qty:{risk_calc.quantity:.4f} | Risk:${risk_calc.risk_amount:.2f}"
        )
        self.notifier.notify_entry(
            side, symbol, actual_entry,
            risk_calc.stop_loss, risk_calc.take_profit,
            risk_calc.risk_amount, self.strategies[symbol].name,
            mode=self.cfg.trading.mode,
        )

    # ─── Manage Position ──────────────────────────────────────────────
    def _manage_position(self, symbol: str, pos: Position):
        price = self.exchange.get_ticker_price(symbol)
        if not price:
            return

        pnl = pos.calculate_pnl(price)
        logger.info(f"📌 [{symbol}] {pos.side} | Entry:${pos.entry_price:.2f} | Harga:${price:.2f} | PnL:${pnl:.2f}")

        # Cek SL/TP
        if pos.side == "LONG":
            if price <= pos.stop_loss:
                self._close_position(symbol, "STOP_LOSS")
                return
            if price >= pos.take_profit:
                self._close_position(symbol, "TAKE_PROFIT")
                return
        else:
            if price >= pos.stop_loss:
                self._close_position(symbol, "STOP_LOSS")
                return
            if price <= pos.take_profit:
                self._close_position(symbol, "TAKE_PROFIT")
                return

        # Trailing stop
        self._update_trailing_stop(symbol, pos, price)

    def _update_trailing_stop(self, symbol: str, pos: Position, price: float):
        atr      = 0.5  # simplified
        trail    = atr * self.cfg.risk.sl_atr_multiplier
        new_sl   = None

        if pos.side == "LONG" and price - trail > pos.stop_loss:
            new_sl = round(price - trail, 2)
        elif pos.side == "SHORT" and price + trail < pos.stop_loss:
            new_sl = round(price + trail, 2)

        if new_sl:
            logger.info(f"🎯 [{symbol}] Trailing Stop: ${pos.stop_loss:.2f} → ${new_sl:.2f}")
            pos.stop_loss = new_sl

    # ─── Close Position ───────────────────────────────────────────────
    def _close_position(self, symbol: str, reason: str):
        pos = self.open_positions.get(symbol)
        if not pos:
            return

        price = self.exchange.get_ticker_price(symbol) or pos.entry_price
        self.exchange.cancel_all_orders(symbol)
        self.exchange.close_position(symbol, pos.side, pos.quantity)

        pnl = pos.calculate_pnl(price)
        pos.status = "CLOSED"

        self.risk_managers[symbol].register_trade_close(pnl)
        self.balance += pnl

        record = TradeRecord(
            id=pos.id, symbol=symbol, side=pos.side,
            entry_price=pos.entry_price, exit_price=price,
            quantity=pos.quantity, final_pnl=pnl,
            exit_reason=reason, strategy=pos.strategy,
        )
        self.trade_histories[symbol].append(record)
        self.open_positions[symbol] = None

        trade_logger.info(
            f"CLOSE | {pos.side} | {symbol} | "
            f"Entry:{pos.entry_price:.2f} | Exit:{price:.2f} | "
            f"PnL:{pnl:.4f} | Reason:{reason}"
        )
        logger.info(
            f"🔒 POSISI DITUTUP | {reason}\n"
            f"   {pos.side} {symbol} | Entry: ${pos.entry_price:.2f} → Exit: ${price:.2f} | PnL: ${pnl:+.2f} USDT"
        )
        self.notifier.notify_exit(pos.side, symbol, pos.entry_price, price, pnl, reason)

    # ─── Daily Reset ──────────────────────────────────────────────────
    def _daily_reset_check(self):
        today = date.today()
        if today != self._last_reset_date:
            self._last_reset_date = today
            for symbol in self.cfg.trading.symbols:
                self.risk_managers[symbol].reset_daily()

            # Summary semua pair
            total = sum(len(h) for h in self.trade_histories.values())
            wins  = sum(1 for h in self.trade_histories.values() for t in h if t.final_pnl > 0)
            pnl   = sum(t.final_pnl for h in self.trade_histories.values() for t in h)

            try:
                fresh_balance = self.exchange.get_account_balance() or self.balance
            except:
                fresh_balance = self.balance

            self.notifier.notify_daily_summary(total, wins, pnl, fresh_balance)

            # Reset histories
            for symbol in self.cfg.trading.symbols:
                self.trade_histories[symbol] = []

    # ─── Summary ──────────────────────────────────────────────────────
    def _print_summary(self):
        logger.info("=" * 55)
        logger.info("📊 RINGKASAN MULTI-PAIR")
        for symbol in self.cfg.trading.symbols:
            history = self.trade_histories[symbol]
            total   = len(history)
            wins    = sum(1 for t in history if t.final_pnl > 0)
            pnl     = sum(t.final_pnl for t in history)
            wr      = round(wins/total*100, 1) if total else 0
            logger.info(f"   {symbol}: {total} trade | WR {wr}% | PnL ${pnl:+.2f}")
        logger.info(f"   Balance: ${self.balance:,.2f} USDT")
        logger.info("=" * 55)

