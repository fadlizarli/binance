"""
exchange/binance_client.py
Wrapper Binance Futures API.
"""
import time
from typing import Optional
import pandas as pd

from config import config
from utils.logger import logger

try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException, BinanceOrderException
    HAS_BINANCE = True
except ImportError:
    HAS_BINANCE = False
    logger.warning("python-binance belum diinstall.")


class BinanceClient:
    TESTNET_URL = "https://testnet.binancefuture.com"
    LIVE_URL    = "https://fapi.binance.com"

    def __init__(self):
        self.api_key    = config.api.api_key
        self.secret_key = config.api.secret_key
        self.is_testnet = config.api.is_testnet
        self.client     = None
        self._connect()

    def _connect(self):
        if not HAS_BINANCE:
            logger.error("Library python-binance tidak tersedia!")
            return
        try:
            if self.is_testnet:
                self.client = Client(self.api_key, self.secret_key, testnet=True)
                try:
                    self.client.futures_account_balance()
                    logger.info("✅ Terhubung ke Binance TESTNET")
                except Exception:
                    self.client = Client(self.api_key, self.secret_key)
                    self.client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"
                    logger.info("✅ Terhubung ke Binance DEMO")
            else:
                self.client = Client(self.api_key, self.secret_key)
                logger.info("✅ Terhubung ke Binance LIVE")
        except Exception as e:
            logger.error(f"Gagal connect: {e}")
            self.client = None

    def is_connected(self): return self.client is not None

    def get_klines(self, symbol, interval, limit=200):
        if not self.is_connected(): return None
        try:
            raw = self.client.futures_klines(symbol=symbol, interval=interval, limit=limit)
            df = pd.DataFrame(raw, columns=[
                "timestamp","open","high","low","close","volume",
                "close_time","quote_volume","trades","taker_buy_base","taker_buy_quote","ignore"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            for col in ["open","high","low","close","volume"]:
                df[col] = df[col].astype(float)
            return df[["open","high","low","close","volume"]]
        except Exception as e:
            logger.error(f"Gagal ambil klines: {e}"); return None

    def get_ticker_price(self, symbol):
        if not self.is_connected(): return None
        try:
            return float(self.client.futures_symbol_ticker(symbol=symbol)["price"])
        except Exception as e:
            logger.error(f"Gagal ambil harga: {e}"); return None

    def get_account_balance(self):
        if not self.is_connected(): return None
        try:
            for b in self.client.futures_account_balance():
                if b["asset"] == "USDT":
                    # Gunakan walletBalance agar konsisten
                    # availableBalance berkurang saat ada posisi terbuka
                    val = float(b["balance"])
                    return val if val > 0 else None
            return None
        except Exception as e:
            logger.error(f"get_balance error: {e}"); return None

    def get_open_positions(self, symbol):
        if not self.is_connected(): return []
        try:
            return [p for p in self.client.futures_position_information(symbol=symbol)
                    if float(p["positionAmt"]) != 0]
        except Exception as e:
            logger.error(f"Gagal ambil posisi: {e}"); return []

    def get_open_orders(self, symbol):
        if not self.is_connected(): return []
        try:
            return self.client.futures_get_open_orders(symbol=symbol)
        except Exception as e:
            logger.error(f"Gagal ambil open orders: {e}"); return []

    def get_funding_rate(self, symbol):
        if not self.is_connected(): return None
        try:
            return float(self.client.futures_mark_price(symbol=symbol).get("lastFundingRate", 0))
        except Exception as e:
            logger.error(f"Gagal ambil funding rate: {e}"); return None

    def set_leverage(self, symbol, leverage):
        if not self.is_connected(): return False
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            logger.info(f"Leverage {symbol}: {leverage}x"); return True
        except Exception as e:
            logger.error(f"set_leverage error: {e}"); return False

    def set_margin_type(self, symbol, margin_type="ISOLATED"):
        if not self.is_connected(): return False
        try:
            self.client.futures_change_margin_type(symbol=symbol, marginType=margin_type)
            return True
        except BinanceAPIException as e:
            if e.code == -4046: return True
            logger.error(f"Gagal set margin type: {e}"); return False
        except Exception as e:
            logger.error(f"Gagal set margin type: {e}"); return False

    def place_market_order(self, symbol, side, quantity):
        if not self.is_connected(): return None
        try:
            order = self.client.futures_create_order(
                symbol=symbol, side=side, type="MARKET",
                quantity=round(quantity, 3))
            logger.info(f"📥 {side} {quantity:.4f} {symbol} | ID:{order['orderId']}")
            return order
        except Exception as e:
            logger.error(f"market_order error: {e}"); return None

    def place_stop_loss_order(self, symbol, side, quantity, stop_price):
        """SL order — coba 2 cara untuk kompatibilitas demo Binance."""
        if not self.is_connected(): return None
        attempts = [
            dict(type="STOP_MARKET", closePosition=True,
                 stopPrice=round(stop_price, 2)),
            dict(type="STOP_MARKET", closePosition=False,
                 stopPrice=round(stop_price, 2),
                 quantity=round(quantity, 3), reduceOnly=True),
        ]
        for params in attempts:
            try:
                order = self.client.futures_create_order(symbol=symbol, side=side, **params)
                logger.info(f"🛑 SL terpasang @ ${stop_price:,.2f} | ID:{order['orderId']}")
                return order
            except Exception as e:
                logger.warning(f"SL attempt gagal: {e}")
        logger.error("❌ SL gagal dipasang — dikelola software")
        return None

    def place_take_profit_order(self, symbol, side, quantity, tp_price):
        """TP order — coba 2 cara untuk kompatibilitas demo Binance."""
        if not self.is_connected(): return None
        attempts = [
            dict(type="TAKE_PROFIT_MARKET", closePosition=True,
                 stopPrice=round(tp_price, 2)),
            dict(type="TAKE_PROFIT_MARKET", closePosition=False,
                 stopPrice=round(tp_price, 2),
                 quantity=round(quantity, 3), reduceOnly=True),
        ]
        for params in attempts:
            try:
                order = self.client.futures_create_order(symbol=symbol, side=side, **params)
                logger.info(f"🎯 TP terpasang @ ${tp_price:,.2f} | ID:{order['orderId']}")
                return order
            except Exception as e:
                logger.warning(f"TP attempt gagal: {e}")
        logger.error("❌ TP gagal dipasang — dikelola software")
        return None

    def cancel_order(self, symbol, order_id):
        if not self.is_connected(): return False
        try:
            self.client.futures_cancel_order(symbol=symbol, orderId=order_id)
            logger.info(f"Order {order_id} dibatalkan"); return True
        except Exception as e:
            logger.error(f"Gagal cancel order: {e}"); return False

    def cancel_all_orders(self, symbol):
        if not self.is_connected(): return False
        try:
            self.client.futures_cancel_all_open_orders(symbol=symbol)
            logger.info(f"Semua order {symbol} dibatalkan"); return True
        except Exception as e:
            logger.error(f"Gagal cancel semua order: {e}"); return False

    def close_position(self, symbol, side, quantity):
        close_side = "SELL" if side == "LONG" else "BUY"
        try:
            order = self.client.futures_create_order(
                symbol=symbol, side=close_side, type="MARKET",
                quantity=round(quantity, 3), reduceOnly=True)
            logger.info(f"🔒 Posisi ditutup | {symbol} {close_side} {quantity:.4f}")
            return order
        except Exception as e:
            logger.error(f"Gagal close posisi: {e}"); return None

    def get_symbol_info(self, symbol):
        if not self.is_connected(): return None
        try:
            for s in self.client.futures_exchange_info()["symbols"]:
                if s["symbol"] == symbol: return s
            return None
        except Exception as e:
            logger.error(f"Gagal ambil symbol info: {e}"); return None
