"""
core/bot_engine.py
Orkestrator utama bot.
Menghubungkan semua modul: exchange, indikator, strategi, risk management.
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
from utils.notifier import TelegramNotifier


class BotEngine:
    """
    Engine utama yang mengatur seluruh siklus bot:
    1. Ambil data market
    2. Hitung indikator
    3. Generate sinyal
    4. Validasi risiko
    5. Eksekusi order
    6. Manage posisi (SL/TP/trailing)
    7. Logging & notifikasi
    """

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

    # ----------------------------------------------------------
    # MAIN LOOP
    # ----------------------------------------------------------
    def start(self):
        """Mulai bot dan jalankan loop utama."""
        if not self.exchange.is_connected():
            logger.error("Bot tidak bisa start: koneksi exchange gagal!")
            return

        # Inisialisasi
        self._init_exchange()
        self.balance = self.exchange.get_account_balance() or 1000.0
        self.risk_manager.session_high_balance = self.balance

        logger.info(f"💰 Balance: ${self.balance:,.2f} USDT")
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
                time.sleep(30)  # Tunggu 30 detik sebelum retry

    def stop(self):
        """Hentikan bot dengan aman."""
        self.is_running = False
        self._print_summary()

        if self.open_position:
            logger.warning(
                f"⚠️  Masih ada posisi terbuka: {self.open_position}"
                "\nTutup manual di Binance jika diperlukan!"
            )

    def _tick(self):
        """Satu siklus pengecekan bot."""
        symbol    = self.cfg.trading.symbol
        timeframe = self.cfg.trading.timeframe

        # 1. Ambil data candle
        df = self.exchange.get_klines(symbol, timeframe, self.cfg.candle_limit)
        if df is None:
            logger.warning("Gagal ambil data candle, skip tick ini")
            return

        # 2. Hitung indikator
        ind = self.indicators.calculate(df)
        if ind is None:
            logger.warning("Indikator belum bisa dihitung (data kurang)")
            return

        # 3. Update balance
        current_balance = self.exchange.get_account_balance()
        if current_balance is not None:
            self.balance = current_balance

        # 4. Manage posisi yang sudah terbuka
        if self.open_position:
            self._manage_position(ind)
            return  # Satu posisi saja dalam satu waktu

        # 5. Cek apakah bisa buka posisi baru
        can_trade, reason = self.risk_manager.can_trade(self.balance)
        if not can_trade:
            logger.warning(f"⛔ Tidak bisa trade: {reason}")
            return

        # 6. Generate sinyal
        signal = self.strategy.generate_signal(ind)
        logger.debug(
            f"📡 Sinyal: {signal.action} "
            f"(strength: {signal.strength:.2f}) | {signal.reason}"
        )

        if signal.action == "WAIT":
            logger.info(f"⏳ WAIT | {signal.reason}")
            return

        # Tampilkan indikator ringkas
        self.indicators.print_summary(ind)

        # 7. Hitung risiko & validasi
        risk_calc = self.risk_manager.calculate_position(
            side=signal.action,
            entry_price=ind.close,
            atr=ind.atr,
            balance=self.balance,
        )

        if not risk_calc.valid:
            logger.warning(f"⛔ Risk tidak valid: {risk_calc.reason}")
            return

        # 8. Eksekusi order
        self._open_position(signal, risk_calc, ind.atr)

    # ----------------------------------------------------------
    # ORDER EXECUTION
    # ----------------------------------------------------------
    def _open_position(self, signal: Signal, risk_calc, atr: float):
        """Buka posisi baru dengan market order + pasang SL/TP."""
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

        # Market order entry
        entry_order = self.exchange.place_market_order(
            symbol, buy_sell, risk_calc.quantity
        )

        if not entry_order:
            logger.error("Gagal membuka posisi!")
            return

        # Actual entry price (dari fill)
        actual_entry = float(entry_order.get("avgPrice", risk_calc.entry_price))
        if actual_entry == 0:
            actual_entry = risk_calc.entry_price

        # Buat objek Position
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

        # Pasang SL order
        close_side = "SELL" if side == "LONG" else "BUY"
        sl_order = self.exchange.place_stop_loss_order(
            symbol, close_side, risk_calc.quantity, risk_calc.stop_loss
        )
        if sl_order:
            pos.sl_order_id = str(sl_order.get("orderId", ""))

        # Pasang TP order
        tp_order = self.exchange.place_take_profit_order(
            symbol, close_side, risk_calc.quantity, risk_calc.take_profit
        )
        if tp_order:
            pos.tp_order_id = str(tp_order.get("orderId", ""))

        self.open_position = pos
        self.risk_manager.register_trade_open()

        # Log & notifikasi
        trade_logger.info(
            f"OPEN | {side} | {symbol} | "
            f"Entry:{actual_entry:.2f} | SL:{risk_calc.stop_loss:.2f} | "
            f"TP:{risk_calc.take_profit:.2f} | Qty:{risk_calc.quantity:.4f} | "
            f"Risk:${risk_calc.risk_amount:.2f} | Strategy:{self.strategy.name}"
        )
        self.notifier.notify_entry(
            side, symbol, actual_entry,
            risk_calc.stop_loss, risk_calc.take_profit,
            risk_calc.risk_amount, self.strategy.name,
        )

    def _close_position(self, reason: str):
        """Tutup posisi aktif."""
        if not self.open_position:
            return

        pos = self.open_position
        current_price = self.exchange.get_ticker_price(pos.symbol) or pos.entry_price

        # Cancel pending SL/TP orders
        self.exchange.cancel_all_orders(pos.symbol)

        # Close dengan market order
        self.exchange.close_position(pos.symbol, pos.side, pos.quantity)

        # Hitung PnL final
        pnl = pos.calculate_pnl(current_price)
        pos.status = "CLOSED"

        # Update statistik
        self.risk_manager.register_trade_close(pnl)
        self.balance += pnl

        # Catat ke history
        record = TradeRecord(
            position=pos,
            exit_price=current_price,
            exit_reason=reason,
            final_pnl=pnl,
        )
        self.trade_history.append(record)

        pnl_str = f"{'+'if pnl >= 0 else ''}{pnl:.2f}"
        logger.info(f"🔒 POSISI DITUTUP | {reason}")
        logger.info(f"   {pos.side} {pos.symbol} | "
                    f"Entry: ${pos.entry_price:.2f} → Exit: ${current_price:.2f} | "
                    f"PnL: ${pnl_str} USDT")

        # Log & notifikasi
        trade_logger.info(
            f"CLOSE | {pos.side} | {pos.symbol} | "
            f"Entry:{pos.entry_price:.2f} | Exit:{current_price:.2f} | "
            f"PnL:{pnl:.4f} | Reason:{reason}"
        )
        self.notifier.notify_exit(
            pos.side, pos.symbol, pos.entry_price,
            current_price, pnl, reason
        )

        self.open_position = None

    # ----------------------------------------------------------
    # POSITION MANAGEMENT
    # ----------------------------------------------------------
    def _manage_position(self, ind):
        """Kelola posisi terbuka: cek SL/TP, trailing, breakeven."""
        pos = self.open_position
        price = ind.close
        current_pnl = pos.calculate_pnl(price)

        logger.info(
            f"📌 Posisi {pos.side} {pos.symbol} | "
            f"Entry: ${pos.entry_price:.2f} | "
            f"Harga: ${price:.2f} | "
            f"PnL: ${'+'if current_pnl >= 0 else ''}{current_pnl:.2f}"
        )

        # ---- Cek SL hit ----
        if pos.side == "LONG" and price <= pos.stop_loss:
            self._close_position("STOP_LOSS")
            return
        if pos.side == "SHORT" and price >= pos.stop_loss:
            self._close_position("STOP_LOSS")
            return

        # ---- Cek TP hit ----
        if pos.side == "LONG" and price >= pos.take_profit:
            self._close_position("TAKE_PROFIT")
            return
        if pos.side == "SHORT" and price <= pos.take_profit:
            self._close_position("TAKE_PROFIT")
            return

        # ---- Move SL to Breakeven ----
        if (not pos.sl_moved_to_be and
            self.risk_manager.should_move_to_breakeven(
                pos.side, price, pos.entry_price, pos.take_profit
            )):
            pos.stop_loss = pos.entry_price
            pos.sl_moved_to_be = True
            logger.info(f"🔐 SL dipindah ke breakeven: ${pos.entry_price:.2f}")

            # Update SL order di exchange
            if pos.sl_order_id:
                self.exchange.cancel_order(pos.symbol, int(pos.sl_order_id))
            close_side = pos.close_side
            sl_order = self.exchange.place_stop_loss_order(
                pos.symbol, close_side, pos.quantity, pos.entry_price
            )
            if sl_order:
                pos.sl_order_id = str(sl_order.get("orderId", ""))

        # ---- Trailing Stop ----
        new_sl = self.risk_manager.calculate_trailing_stop(
            pos.side, price, pos.stop_loss, pos.entry_price, ind.atr
        )
        if new_sl:
            old_sl = pos.stop_loss
            pos.stop_loss = new_sl
            logger.info(
                f"🎯 Trailing Stop digeser: ${old_sl:.2f} → ${new_sl:.2f}"
            )
            # Update SL order di exchange
            if pos.sl_order_id:
                self.exchange.cancel_order(pos.symbol, int(pos.sl_order_id))
            sl_order = self.exchange.place_stop_loss_order(
                pos.symbol, pos.close_side, pos.quantity, new_sl
            )
            if sl_order:
                pos.sl_order_id = str(sl_order.get("orderId", ""))

    # ----------------------------------------------------------
    # HELPERS
    # ----------------------------------------------------------
    def _init_exchange(self):
        """Setup leverage dan margin type di awal."""
        symbol   = self.cfg.trading.symbol
        leverage = self.cfg.trading.leverage

        self.exchange.set_margin_type(symbol, "ISOLATED")
        self.exchange.set_leverage(symbol, leverage)

    def _daily_reset_check(self):
        """Reset counter harian jika tanggal berubah."""
        today = date.today()
        if today != self._last_reset_date:
            self._last_reset_date = today
            self.risk_manager.reset_daily()

            # Kirim ringkasan harian
            wins  = sum(1 for t in self.trade_history if t.final_pnl > 0)
            total = len(self.trade_history)
            daily_pnl = sum(t.final_pnl for t in self.trade_history)
            self.notifier.notify_daily_summary(total, wins, daily_pnl, self.balance)

    def _print_summary(self):
        """Print ringkasan performa saat bot dihentikan."""
        total  = len(self.trade_history)
        wins   = sum(1 for t in self.trade_history if t.final_pnl > 0)
        losses = total - wins
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

