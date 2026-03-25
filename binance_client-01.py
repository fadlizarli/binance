"""
exchange/binance_client.py
Wrapper Binance Futures API — semua komunikasi exchange ada di sini.
Mendukung Testnet dan Live.
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
    logger.warning("python-binance belum diinstall. Jalankan: pip install python-binance")


class BinanceClient:
    """
    Wrapper untuk Binance Futures API.
    Semua order dan data market diakses lewat class ini.
    """

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
                self.client = Client(
                    self.api_key,
                    self.secret_key,
                    testnet=True
                )
                logger.info("✅ Terhubung ke Binance TESTNET")
            else:
                self.client = Client(self.api_key, self.secret_key)
                logger.info("✅ Terhubung ke Binance LIVE")

        except Exception as e:
            logger.error(f"Gagal connect ke Binance: {e}")
            self.client = None

    def is_connected(self) -> bool:
        return self.client is not None

    # ----------------------------------------------------------
    # MARKET DATA
    # ----------------------------------------------------------
    def get_klines(self, symbol: str, interval: str,
                   limit: int = 200) -> Optional[pd.DataFrame]:
        """
        Ambil data OHLCV dari Binance Futures.
        Return: DataFrame dengan kolom [open, high, low, close, volume]
        """
        if not self.is_connected():
            return None

        try:
            raw = self.client.futures_klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            df = pd.DataFrame(raw, columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades",
                "taker_buy_base", "taker_buy_quote", "ignore"
            ])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)

            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)

            return df[["open", "high", "low", "close", "volume"]]

        except Exception as e:
            logger.error(f"Gagal ambil klines {symbol}: {e}")
            return None

    def get_ticker_price(self, symbol: str) -> Optional[float]:
        """Ambil harga terkini."""
        if not self.is_connected():
            return None
        try:
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            return float(ticker["price"])
        except Exception as e:
            logger.error(f"Gagal ambil harga {symbol}: {e}")
            return None

    def get_account_balance(self) -> Optional[float]:
        """Ambil saldo USDT di akun futures."""
        if not self.is_connected():
            return None
        try:
            balances = self.client.futures_account_balance()
            for b in balances:
                if b["asset"] == "USDT":
                    return float(b["availableBalance"])
            return 0.0
        except Exception as e:
            logger.error(f"Gagal ambil balance: {e}")
            return None

    def get_open_positions(self, symbol: str) -> list:
        """Ambil posisi terbuka untuk symbol tertentu."""
        if not self.is_connected():
            return []
        try:
            positions = self.client.futures_position_information(symbol=symbol)
            return [p for p in positions if float(p["positionAmt"]) != 0]
        except Exception as e:
            logger.error(f"Gagal ambil posisi: {e}")
            return []

    def get_funding_rate(self, symbol: str) -> Optional[float]:
        """Ambil funding rate saat ini."""
        if not self.is_connected():
            return None
        try:
            info = self.client.futures_mark_price(symbol=symbol)
            return float(info.get("lastFundingRate", 0))
        except Exception as e:
            logger.error(f"Gagal ambil funding rate: {e}")
            return None

    # ----------------------------------------------------------
    # LEVERAGE SETTING
    # ----------------------------------------------------------
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage untuk symbol."""
        if not self.is_connected():
            return False
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            logger.info(f"Leverage {symbol} di-set ke {leverage}x")
            return True
        except Exception as e:
            logger.error(f"Gagal set leverage: {e}")
            return False

    def set_margin_type(self, symbol: str, margin_type: str = "ISOLATED") -> bool:
        """Set margin type: ISOLATED atau CROSSED."""
        if not self.is_connected():
            return False
        try:
            self.client.futures_change_margin_type(
                symbol=symbol, marginType=margin_type
            )
            logger.info(f"Margin type {symbol}: {margin_type}")
            return True
        except BinanceAPIException as e:
            # Error -4046 = sudah dalam mode yang sama (bukan error sebenarnya)
            if e.code == -4046:
                return True
            logger.error(f"Gagal set margin type: {e}")
            return False
        except Exception as e:
            logger.error(f"Gagal set margin type: {e}")
            return False

    # ----------------------------------------------------------
    # ORDER MANAGEMENT
    # ----------------------------------------------------------
    def place_market_order(self, symbol: str, side: str,
                           quantity: float) -> Optional[dict]:
        """
        Buka posisi dengan market order.
        side: 'BUY' (long) atau 'SELL' (short)
        """
        if not self.is_connected():
            return None
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type="MARKET",
                quantity=round(quantity, 3),
            )
            logger.info(
                f"📥 Market Order | {side} {quantity:.4f} {symbol} "
                f"| OrderID: {order['orderId']}"
            )
            return order
        except BinanceOrderException as e:
            logger.error(f"Order gagal: {e}")
            return None
        except Exception as e:
            logger.error(f"Order error: {e}")
            return None

    def place_stop_loss_order(self, symbol: str, side: str,
                              quantity: float, stop_price: float) -> Optional[dict]:
        """
        Pasang Stop Loss order.
        side: sisi PENUTUP posisi (kebalikan dari posisi)
        """
        if not self.is_connected():
            return None
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type="STOP_MARKET",
                quantity=round(quantity, 3),
                stopPrice=round(stop_price, 2),
                closePosition=False,
                reduceOnly=True,
            )
            logger.info(
                f"🛑 Stop Loss | {side} @ ${stop_price:,.2f} "
                f"| OrderID: {order['orderId']}"
            )
            return order
        except Exception as e:
            logger.error(f"Gagal pasang SL: {e}")
            return None

    def place_take_profit_order(self, symbol: str, side: str,
                                quantity: float, tp_price: float) -> Optional[dict]:
        """Pasang Take Profit order."""
        if not self.is_connected():
            return None
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type="TAKE_PROFIT_MARKET",
                quantity=round(quantity, 3),
                stopPrice=round(tp_price, 2),
                closePosition=False,
                reduceOnly=True,
            )
            logger.info(
                f"🎯 Take Profit | {side} @ ${tp_price:,.2f} "
                f"| OrderID: {order['orderId']}"
            )
            return order
        except Exception as e:
            logger.error(f"Gagal pasang TP: {e}")
            return None

    def cancel_order(self, symbol: str, order_id: int) -> bool:
        """Batalkan order tertentu."""
        if not self.is_connected():
            return False
        try:
            self.client.futures_cancel_order(symbol=symbol, orderId=order_id)
            logger.info(f"Order {order_id} dibatalkan")
            return True
        except Exception as e:
            logger.error(f"Gagal cancel order {order_id}: {e}")
            return False

    def cancel_all_orders(self, symbol: str) -> bool:
        """Batalkan semua order terbuka untuk symbol."""
        if not self.is_connected():
            return False
        try:
            self.client.futures_cancel_all_open_orders(symbol=symbol)
            logger.info(f"Semua order {symbol} dibatalkan")
            return True
        except Exception as e:
            logger.error(f"Gagal cancel semua order: {e}")
            return False

    def close_position(self, symbol: str, side: str, quantity: float) -> Optional[dict]:
        """
        Tutup posisi dengan market order.
        side posisi LONG -> close dengan SELL
        side posisi SHORT -> close dengan BUY
        """
        close_side = "SELL" if side == "LONG" else "BUY"
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=close_side,
                type="MARKET",
                quantity=round(quantity, 3),
                reduceOnly=True,
            )
            logger.info(f"🔒 Posisi ditutup | {symbol} {close_side} {quantity:.4f}")
            return order
        except Exception as e:
            logger.error(f"Gagal close posisi: {e}")
            return None

    def get_symbol_info(self, symbol: str) -> Optional[dict]:
        """Ambil info symbol (lot size, tick size, dll)."""
        if not self.is_connected():
            return None
        try:
            info = self.client.futures_exchange_info()
            for s in info["symbols"]:
                if s["symbol"] == symbol:
                    return s
            return None
        except Exception as e:
            logger.error(f"Gagal ambil symbol info: {e}")
            return None

