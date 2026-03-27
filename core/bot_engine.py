"""
core/bot_engine.py
Orkestrator utama bot.
"""
import time
import uuid
from datetime import datetime, date
from typing import Optional

from config import config
from core.indicators import IndicatorEngine
from core.position import Position, TradeRecord
from exchange.binance_client import BinanceClient
from risk.manager import RiskManager
from strategies import get_strategy, Signal
from utils.logger import logger, trade_logger
from utils.claude_filter import claude_validate
from utils.notifier import TelegramNotifier


class BotEngine:
    def __init__(self):
        self.cfg           = config
        self.exchange      = BinanceClient()
        self.indicators    = IndicatorEngine()
        self.risk_manager  = RiskManager()
        self.strategy      = get_strategy(config.trading.strategy)
        self.notifier      = TelegramNotifier(
            config.notification.telegram_token,
            config.notification.telegram_chat_id,
        )
        self.open_position: Optional[Position] = None
        self.trade_history: list[TradeRecord]  = []
        self.balance: float = 0.0
        self.is_running: bool = False
        self._last_reset_date: date = date.today()

        logger.info(f"🤖 BotEngine inisialisasi")
        logger.info(f"   Mode      : {'TESTNET' if config.api.is_testnet else '🔴 LIVE'}")
        logger.info(f"   Symbol    : {config.trading.symbol}")
        logger.info(f"   Timeframe : {config.trading.timeframe}")
        logger.info(f"   Strategi  : {self.strategy.name.upper()}")
        logger.info(f"   Leverage  : {config.trading.leverage}x")

    def start(self):
        if not self.exchange.is_connected():
            logger.error("Bot tidak bisa start: koneksi exchange gagal!")
            return

        self._init_exchange()

        # Balance
        fetched = self.exchange.get_account_balance()
        self.balance = fetched if fetched and fetched > 0 else 1000.0
        self.risk_manager.set_initial_balance(self.balance)

        logger.info(f"💰 Balance: ${self.balance:,.2f} USDT")

        # ── RECOVERY: cek posisi terbuka saat bot restart ──
        try:
            existing = self.exchange.get_open_positions(config.trading.symbol)
            if existing:
                p   = existing[0]
                amt = float(p["positionAmt"])
                if amt != 0:
                    side  = "LONG" if amt > 0 else "SHORT"
                    entry = float(p["entryPrice"])
                    # Estimasi SL/TP dari entry ±1.5% / ±3%
                    sl = round(entry * (0.985 if side == "LONG" else 1.015), 4)
                    tp = round(entry * (1.030 if side == "LONG" else 0.970), 4)
                    self.open_position = Position(
                        id=str(uuid.uuid4())[:8],
                        symbol=config.trading.symbol,
                        side=side,
                        entry_price=entry,
                        quantity=abs(amt),
                        stop_loss=sl,
                        take_profit=tp,
                        risk_amount=self.balance * (config.risk.risk_per_trade / 100),
                        strategy=config.trading.strategy,
                        leverage=config.trading.leverage,
                    )
                    logger.info(
                        f"♻️  Recovery posisi: {side} {config.trading.symbol} "
                        f"@ ${entry:.2f} | Qty:{abs(amt):.1f} | "
                        f"SL:${sl:.2f} TP:${tp:.2f}"
                    )
        except Exception as e:
            logger.warning(f"Gagal recovery posisi: {e}")

        logger.info("=" * 55)
        logger.info("🚀 BOT DIMULAI — Tekan Ctrl+C untuk berhenti")
        logger.info("=" * 55)

        self.is_running = True
        while self.is_running:
            try:
                self._daily_reset_check()
                self._tick()
                time.sleep(config.check_interval)
            except KeyboardInterrupt:
                logger.info("⏹  Bot dihentikan oleh user")
                self.stop()
                break
            except Exception as e:
                logger.error(f"Error di loop utama: {e}", exc_info=True)
                time.sleep(30)

    def stop(self):
        self.is_running = False
        self._print_summary()
        if self.open_position:
            logger.warning(f"⚠️  Masih ada posisi terbuka: {self.open_position}")

    def _tick(self):
        symbol    = self.cfg.trading.symbol
        timeframe = self.cfg.trading.timeframe

        df = self.exchange.get_klines(symbol, timeframe, self.cfg.candle_limit)
        if df is None:
            logger.warning("Gagal ambil data candle")
            return

        ind = self.indicators.calculate(df)
        if ind is None:
            logger.warning("Indikator belum bisa dihitung")
            return

        # Update balance (hanya jika valid)
        current_balance = self.exchange.get_account_balance()
        if current_balance and current_balance > 0:
            self.balance = current_balance

        # Manage posisi terbuka
        if self.open_position:
            self._manage_position(ind)
            return

        # Filter jam trading — hanya entry jam 14:00-23:00 WIB
        from datetime import datetime
        import pytz
        wib  = pytz.timezone("Asia/Jakarta")
        hour = datetime.now(wib).hour
        if not (14 <= hour <= 23):
            logger.debug(f"⏰ Di luar jam trading ({hour}:00 WIB) — skip entry")
            return

        # HTF Filter — cek trend 4h sebelum entry di 1h
        try:
            df_4h = self.exchange.get_klines(symbol, "4h", limit=100)
            if df_4h is not None:
                ind_4h = self.indicators.calculate(df_4h)
                if ind_4h is not None:
                    htf_trend = ind_4h.ema_trend  # BULLISH/BEARISH/NEUTRAL
                    logger.debug(f"📊 HTF 4h Trend: {htf_trend}")
        except Exception as e:
            logger.warning(f"HTF check gagal: {e}")
            htf_trend = "NEUTRAL"

        # Cek boleh trade
        can_trade, reason = self.risk_manager.can_trade(self.balance)
        if not can_trade:
            logger.warning(f"⛔ Tidak bisa trade: {reason}")
            return

        # Generate sinyal
        signal = self.strategy.generate_signal(ind)
        logger.debug(f"📡 Sinyal: {signal.action} (strength: {signal.strength:.2f}) | {signal.reason}")

        if signal.action == "WAIT":
            logger.info(f"⏳ WAIT | {signal.reason}")
            return

        self.indicators.print_summary(ind)

        risk_calc = self.risk_manager.calculate_position(
            side=signal.action,
            entry_price=ind.close,
            atr=ind.atr,
            balance=self.balance,
        )
        if not risk_calc.valid:
            logger.warning(f"⛔ Risk tidak valid: {risk_calc.reason}")
            return

        # Validasi HTF — hanya entry searah trend 4h
        try:
            if htf_trend == "BULLISH" and signal.action == "SHORT":
                logger.info(f"⛔ HTF Filter: Trend 4h BULLISH — skip SHORT")
                return
            if htf_trend == "BEARISH" and signal.action == "LONG":
                logger.info(f"⛔ HTF Filter: Trend 4h BEARISH — skip LONG")
                return
            if htf_trend == "NEUTRAL":
                logger.debug(f"⚠️ HTF Neutral — lanjut dengan hati-hati")
        except:
            pass

        # Claude API Filter
        if self.cfg.notification.claude_filter_enabled and self.cfg.notification.anthropic_api_key:
            approved = claude_validate(
                signal.action, ind,
                self.cfg.notification.anthropic_api_key,
                min_confidence=6
            )
            if not approved:
                return

        self._open_position(signal, risk_calc, ind.atr)

    def _open_position(self, signal: Signal, risk_calc, atr: float):
        symbol   = self.cfg.trading.symbol
        side     = signal.action
        buy_sell = "BUY" if side == "LONG" else "SELL"

        logger.info(f"📥 Membuka posisi {side} | {symbol}")
        logger.info(
            f"   Entry: ${risk_calc.entry_price:,.2f} | "
            f"SL: ${risk_calc.stop_loss:,.2f} | "
            f"TP: ${risk_calc.take_profit:,.2f}"
        )
        logger.info(
            f"   Qty: {risk_calc.quantity:.4f} | "
            f"Risk: ${risk_calc.risk_amount:.2f} | "
            f"R:R {risk_calc.rr_actual:.2f}"
        )

        entry_order = self.exchange.place_market_order(symbol, buy_sell, risk_calc.quantity)
        if not entry_order:
            logger.error("Gagal membuka posisi!")
            return

        actual_entry = float(entry_order.get("avgPrice", risk_calc.entry_price))
        if actual_entry == 0:
            actual_entry = risk_calc.entry_price

        pos = Position(
            id=str(uuid.uuid4())[:8],
            symbol=symbol,
            side=side,
            entry_price=actual_entry,
            quantity=risk_calc.quantity,
            stop_loss=risk_calc.stop_loss,
            take_profit=risk_calc.take_profit,
            risk_amount=risk_calc.risk_amount,
            strategy=self.strategy.name,
            leverage=self.cfg.trading.leverage,
            entry_order_id=str(entry_order.get("orderId", "")),
        )

        close_side = "SELL" if side == "LONG" else "BUY"
        sl_order = self.exchange.place_stop_loss_order(symbol, close_side, risk_calc.quantity, risk_calc.stop_loss)
        if sl_order:
            pos.sl_order_id = str(sl_order.get("orderId", ""))

        tp_order = self.exchange.place_take_profit_order(symbol, close_side, risk_calc.quantity, risk_calc.take_profit)
        if tp_order:
            pos.tp_order_id = str(tp_order.get("orderId", ""))

        self.open_position = pos
        self.risk_manager.register_trade_open()

        trade_logger.info(
            f"OPEN | {side} | {symbol} | Entry:{actual_entry:.2f} | "
            f"SL:{risk_calc.stop_loss:.2f} | TP:{risk_calc.take_profit:.2f} | "
            f"Qty:{risk_calc.quantity:.4f} | Risk:${risk_calc.risk_amount:.2f} | "
            f"Strategy:{self.strategy.name}"
        )
        self.notifier.notify_entry(
            side, symbol, actual_entry,
            risk_calc.stop_loss, risk_calc.take_profit,
            risk_calc.risk_amount, self.strategy.name,
        )

    def _close_position(self, reason: str):
        if not self.open_position:
            return

        pos = self.open_position
        current_price = self.exchange.get_ticker_price(pos.symbol) or pos.entry_price

        self.exchange.cancel_all_orders(pos.symbol)
        self.exchange.close_position(pos.symbol, pos.side, pos.quantity)

        pnl = pos.calculate_pnl(current_price)
        pos.status = "CLOSED"

        self.risk_manager.register_trade_close(pnl)
        self.balance += pnl

        record = TradeRecord(position=pos, exit_price=current_price, exit_reason=reason, final_pnl=pnl)
        self.trade_history.append(record)

        pnl_str = f"{'+'if pnl >= 0 else ''}{pnl:.2f}"
        logger.info(f"🔒 POSISI DITUTUP | {reason}")
        logger.info(f"   {pos.side} {pos.symbol} | Entry: ${pos.entry_price:.2f} → Exit: ${current_price:.2f} | PnL: ${pnl_str} USDT")

        trade_logger.info(
            f"CLOSE | {pos.side} | {pos.symbol} | "
            f"Entry:{pos.entry_price:.2f} | Exit:{current_price:.2f} | "
            f"PnL:{pnl:.4f} | Reason:{reason}"
        )
        self.notifier.notify_exit(pos.side, pos.symbol, pos.entry_price, current_price, pnl, reason)
        self.open_position = None

    def _manage_position(self, ind):
        pos   = self.open_position
        price = ind.close
        current_pnl = pos.calculate_pnl(price)

        logger.info(
            f"📌 Posisi {pos.side} {pos.symbol} | "
            f"Entry: ${pos.entry_price:.2f} | "
            f"Harga: ${price:.2f} | "
            f"PnL: ${'+'if current_pnl >= 0 else ''}{current_pnl:.2f}"
        )

        # Cek SL
        if pos.side == "LONG" and price <= pos.stop_loss:
            self._close_position("STOP_LOSS"); return
        if pos.side == "SHORT" and price >= pos.stop_loss:
            self._close_position("STOP_LOSS"); return

        # Cek TP
        if pos.side == "LONG" and price >= pos.take_profit:
            self._close_position("TAKE_PROFIT"); return
        if pos.side == "SHORT" and price <= pos.take_profit:
            self._close_position("TAKE_PROFIT"); return

        # Move to Breakeven
        if (not pos.sl_moved_to_be and
            self.risk_manager.should_move_to_breakeven(pos.side, price, pos.entry_price, pos.take_profit)):
            pos.stop_loss = pos.entry_price
            pos.sl_moved_to_be = True
            logger.info(f"🔐 SL dipindah ke breakeven: ${pos.entry_price:.2f}")
            if pos.sl_order_id:
                self.exchange.cancel_order(pos.symbol, int(pos.sl_order_id))
            sl_order = self.exchange.place_stop_loss_order(pos.symbol, pos.close_side, pos.quantity, pos.entry_price)
            if sl_order:
                pos.sl_order_id = str(sl_order.get("orderId", ""))

        # Trailing Stop
        new_sl = self.risk_manager.calculate_trailing_stop(pos.side, price, pos.stop_loss, pos.entry_price, ind.atr)
        if new_sl:
            old_sl = pos.stop_loss
            pos.stop_loss = new_sl
            logger.info(f"🎯 Trailing Stop: ${old_sl:.2f} → ${new_sl:.2f}")
            if pos.sl_order_id:
                self.exchange.cancel_order(pos.symbol, int(pos.sl_order_id))
            sl_order = self.exchange.place_stop_loss_order(pos.symbol, pos.close_side, pos.quantity, new_sl)
            if sl_order:
                pos.sl_order_id = str(sl_order.get("orderId", ""))

    def _init_exchange(self):
        symbol   = self.cfg.trading.symbol
        leverage = self.cfg.trading.leverage
        self.exchange.set_margin_type(symbol, "ISOLATED")
        self.exchange.set_leverage(symbol, leverage)

    def _daily_reset_check(self):
        today = date.today()
        if today != self._last_reset_date:
            self._last_reset_date = today
            self.risk_manager.reset_daily()
            wins      = sum(1 for t in self.trade_history if t.final_pnl > 0)
            total     = len(self.trade_history)
            daily_pnl = sum(t.final_pnl for t in self.trade_history)
            self.notifier.notify_daily_summary(total, wins, daily_pnl, self.balance)

    def _print_summary(self):
        total     = len(self.trade_history)
        wins      = sum(1 for t in self.trade_history if t.final_pnl > 0)
        losses    = total - wins
        total_pnl = sum(t.final_pnl for t in self.trade_history)
        win_rate  = (wins / total * 100) if total > 0 else 0
        logger.info("=" * 55)
        logger.info("📊 RINGKASAN PERFORMA BOT")
        logger.info(f"   Total Trade : {total}")
        logger.info(f"   Win / Loss  : {wins} / {losses}")
        logger.info(f"   Win Rate    : {win_rate:.1f}%")
        logger.info(f"   Total PnL   : ${'+'if total_pnl >= 0 else ''}{total_pnl:.2f} USDT")
        logger.info(f"   Balance     : ${self.balance:,.2f} USDT")
        logger.info("=" * 55)
