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
from utils.claude_filter import claude_get_confidence
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

        # Fear & Greed Filter (cache 30 menit)
        try:
            import requests as _req, time as _time
            _fg_cache = getattr(self, '_fg_cache', {"time": 0, "value": 50, "label": "Neutral"})
            if _time.time() - _fg_cache["time"] > 1800:  # 30 menit
                _r = _req.get("https://api.alternative.me/fng/", timeout=5)
                _d = _r.json()["data"][0]
                _fg_cache = {"time": _time.time(), "value": int(_d["value"]), "label": _d["value_classification"]}
                self._fg_cache = _fg_cache
                logger.info(f"😨 Fear & Greed update: {_fg_cache['value']} ({_fg_cache['label']})")
            fg_value = _fg_cache["value"]
            fg_label = _fg_cache["label"]
            logger.debug(f"😨 Fear & Greed: {fg_value} ({fg_label})")

            if fg_value < 20:
                logger.info(f"⛔ Extreme Fear ({fg_value}) — skip entry, pasar panik!")
                return
            if fg_value > 80:
                logger.info(f"⛔ Extreme Greed ({fg_value}) — skip entry, pasar euforia!")
                return
            if fg_value < 35:
                logger.info(f"⚠️ Fear ({fg_value}) — butuh Claude ≥ 8 untuk entry")
                # Naikkan min confidence saat Fear
                self._fg_min_confidence = 8
            else:
                self._fg_min_confidence = 7
        except Exception as e:
            logger.debug(f"Fear & Greed tidak tersedia: {e}")
            self._fg_min_confidence = 7

        # Filter jam trading — hanya entry jam 14:00-23:00 WIB
        from datetime import datetime
        import pytz
        wib  = pytz.timezone("Asia/Jakarta")
        hour = datetime.now(wib).hour
        if not (14 <= hour < 23):
            logger.debug(f"⏰ Di luar jam trading ({hour}:00 WIB) — skip entry")
            return

        # HTF Filter — cek trend 4h sebelum entry di 1h
        htf_trend = "NEUTRAL"  # default aman
        try:
            df_4h = self.exchange.get_klines(symbol, "4h", limit=100)
            if df_4h is not None:
                ind_4h = self.indicators.calculate(df_4h)
                if ind_4h is not None:
                    ema_trend_4h = ind_4h.ema_trend
                    macd_4h = getattr(ind_4h, 'macd_line', 0)
                    hist_4h = getattr(ind_4h, 'macd_hist', 0)
                    # EMA aligned → pakai EMA
                    if ema_trend_4h == "BEARISH":
                        htf_trend = "BEARISH"
                    elif ema_trend_4h == "BULLISH":
                        htf_trend = "BULLISH"
                    # EMA NEUTRAL → fallback ke MACD 4H
                    elif macd_4h < -0.3 and hist_4h < -0.05:
                        htf_trend = "BEARISH"
                    elif macd_4h > 0.3 and hist_4h > 0.05:
                        htf_trend = "BULLISH"
                    else:
                        htf_trend = "NEUTRAL"
                    ind.htf_trend = htf_trend
                    logger.debug(f"📊 HTF 4h Trend: {htf_trend} (EMA:{ema_trend_4h} MACD:{macd_4h:.2f} Hist:{hist_4h:.2f})")
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

        # LONG ONLY mode — auto berdasarkan HTF
        import os
        long_only_env = os.getenv("LONG_ONLY", "false").lower() == "true"
        htf = htf_trend

        # Auto: kalau HTF BULLISH atau NEUTRAL → paksa LONG ONLY
        # Override .env kalau HTF sudah jelas BEARISH
        if htf in ("BULLISH", "NEUTRAL"):
            long_only_effective = True
        elif htf == "BEARISH":
            # SHORT hanya kalau RSI > 50 (momentum turun terkonfirmasi)
            rsi = getattr(ind, "rsi", 50)
            if not long_only_env and rsi > 50:
                long_only_effective = False
                logger.info(f"📉 HTF BEARISH + RSI {rsi:.0f} → SHORT diizinkan")
            else:
                long_only_effective = True
                logger.info(f"⚠️ HTF BEARISH tapi RSI {rsi:.0f} < 50 → tetap LONG ONLY")
        else:
            long_only_effective = long_only_env

        if long_only_effective and signal.action == "SHORT":
            logger.info(f"⛔ LONG ONLY (HTF={htf}) — skip SHORT")
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
                if signal.action == "SHORT":
                    logger.info(f"⛔  HTF NEUTRAL — skip SHORT (hindari melawan potensi bullish)")
                    return
                logger.debug(f"⚠️ HTF Neutral — hanya LONG diizinkan")
        except:
            pass

        # Simpan htf_trend ke ind agar Claude bisa akses
        try:
            ind.htf_trend = htf_trend
        except:
            pass

        # Consecutive loss protection
        try:
            import csv as _csv, os as _os, glob as _glob, re as _re
            BASE_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
            # Baca dari log langsung — lebih akurat
            _trades = []
            for _lf in sorted(_glob.glob(_os.path.join(BASE_DIR, "logs", "cryptobot_*.log"))):
                with open(_lf) as _f:
                    _lines = _f.readlines()
                _i = 0
                while _i < len(_lines):
                    _l = _lines[_i].strip()
                    if "POSISI DITUTUP" in _l:
                        _reason = "WIN" if "TAKE_PROFIT" in _l else "UNKNOWN"
                        if _i + 1 < len(_lines):
                            _d = _lines[_i+1].strip()
                            _pm = _re.search(r"PnL: \$([+-]?[\d.]+)", _d)
                            if _pm:
                                _pnl = float(_pm.group(1))
                                _trades.append("WIN" if _pnl > 0 else "LOSS")
                    _i += 1
            if _trades:
                _consecutive = 0
                for _r in reversed(_trades):
                    if _r == "LOSS": _consecutive += 1
                    else: break
                if _consecutive >= 3:
                    logger.info(f"⛔ {_consecutive} loss berturut — skip entry hari ini")
                    return
                elif _consecutive == 2:
                    logger.info(f"⚠️ {_consecutive} loss berturut — extra hati-hati")
        except Exception as _e:
            logger.debug(f"Loss protection error: {_e}")

        # Filter volume minimum
        vol_ratio = getattr(ind, 'volume_ratio', 1.0)
        if vol_ratio < 0.3:
            logger.info(f"⛔ Volume terlalu rendah ({vol_ratio:.2f}x) — skip entry")
            return

        # Claude Risk Adjuster — tidak pernah blok, hanya atur ukuran posisi
        base_risk   = self.cfg.risk.risk_per_trade
        claude_conf = 7  # default kalau Claude tidak aktif
        if self.cfg.notification.claude_filter_enabled and self.cfg.notification.anthropic_api_key:
            claude_conf = claude_get_confidence(
                signal.action, ind,
                self.cfg.notification.anthropic_api_key,
                symbol=self.cfg.trading.symbol,
            )

        if claude_conf >= 8:
            dynamic_risk = base_risk
            logger.info(f"💪 Full size: {dynamic_risk}% (Claude {claude_conf}/10 — setup kuat)")
        elif claude_conf >= 5:
            dynamic_risk = round(base_risk * 0.75, 2)
            logger.info(f"📊 Medium size: {dynamic_risk}% (Claude {claude_conf}/10 — cukup)")
        else:
            dynamic_risk = round(base_risk * 0.50, 2)
            logger.info(f"⚠️ Reduced size: {dynamic_risk}% (Claude {claude_conf}/10 — risiko tinggi)")

        risk_calc = self.risk_manager.calculate_position(
            side=signal.action,
            entry_price=ind.close,
            atr=ind.atr,
            balance=self.balance,
            risk_pct_override=dynamic_risk,
        )

        self._open_position(signal, risk_calc, ind.atr)

    def _open_position(self, signal: Signal, risk_calc, atr: float):
        symbol   = self.cfg.trading.symbol
        side     = signal.action
        buy_sell = "BUY" if side == "LONG" else "SELL"

        # Log detail untuk analisis
        _atr_pct = round(atr / risk_calc.entry_price * 100, 2) if atr and risk_calc.entry_price else 0
        _claude_conf = getattr(self, '_last_claude_conf', 0)
        _strength = getattr(signal, 'strength', 0)
        logger.info(f"📊 ENTRY DETAIL | ATR: {_atr_pct}% | Claude: {_claude_conf}/10 | Strength: {_strength:.2f}")
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
            mode=self.cfg.api.trade_mode,
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
        # Simpan ke CSV untuk analisis
        try:
            import csv, os
            csv_path = os.path.join(self.cfg.log_dir, "trade_analysis.csv")
            file_exists = os.path.exists(csv_path)
            with open(csv_path, 'a', newline='') as csvf:
                writer = csv.writer(csvf)
                if not file_exists:
                    writer.writerow([
                        "date","side","symbol","entry","exit","pnl",
                        "reason","result","balance"
                    ])
                writer.writerow([
                    datetime.now().strftime("%Y-%m-%d %H:%M"),
                    pos.side, pos.symbol,
                    pos.entry_price, current_price,
                    round(pnl, 4), reason,
                    "WIN" if pnl > 0 else "LOSS",
                    round(self.balance, 2)
                ])
        except Exception as e:
            logger.debug(f"CSV save error: {e}")
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
        new_sl = self.risk_manager.calculate_trailing_stop(pos.side, price, pos.stop_loss, pos.entry_price, ind.atr, pos.take_profit)
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
            # Ambil balance fresh dari Binance untuk summary
            try:
                fresh_balance = self.exchange.get_account_balance() or self.balance
            except:
                fresh_balance = self.balance
            self.notifier.notify_daily_summary(total, wins, daily_pnl, fresh_balance)
            # Reset trade history untuk hari baru
            self.trade_history = []

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
