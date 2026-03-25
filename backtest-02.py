"""
backtest.py
Backtesting dengan data historis real dari Binance Futures.
Mendukung download otomatis, cache lokal, dan perbandingan semua strategi.

Cara pakai:
  python backtest.py                                        # simulasi
  python backtest.py --real                                 # data real Binance
  python backtest.py --real --symbol BTCUSDT --tf 1h --days 90
  python backtest.py --real --strategy support_bounce
  python backtest.py --real --all                           # bandingkan semua strategi
"""
import sys
import os
import uuid
import random
import argparse
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.indicators import IndicatorEngine
from core.position import Position, TradeRecord
from risk.manager import RiskManager
from strategies import get_strategy, STRATEGY_MAP
from config import config
from utils.logger import logger


# ============================================================
# DATA DOWNLOADER
# ============================================================

class BinanceDataDownloader:
    """
    Download data OHLCV historis dari Binance Futures API.
    Tidak butuh API Key — menggunakan endpoint publik.
    Menyimpan cache lokal di folder data/ agar tidak download ulang.
    """

    BASE_URL   = "https://fapi.binance.com"
    CACHE_DIR  = "data"

    # Batas candle per request Binance
    LIMIT_PER_REQUEST = 1500

    # Mapping timeframe ke milidetik
    TF_MS = {
        "1m":  60_000,
        "3m":  180_000,
        "5m":  300_000,
        "15m": 900_000,
        "30m": 1_800_000,
        "1h":  3_600_000,
        "2h":  7_200_000,
        "4h":  14_400_000,
        "6h":  21_600_000,
        "8h":  28_800_000,
        "12h": 43_200_000,
        "1d":  86_400_000,
        "3d":  259_200_000,
        "1w":  604_800_000,
    }

    def __init__(self):
        os.makedirs(self.CACHE_DIR, exist_ok=True)

    def _cache_path(self, symbol: str, tf: str, days: int) -> str:
        return os.path.join(
            self.CACHE_DIR,
            f"{symbol}_{tf}_{days}d.csv"
        )

    def _is_cache_valid(self, path: str, max_age_hours: int = 4) -> bool:
        """Cache valid jika file ada dan tidak terlalu lama."""
        if not os.path.exists(path):
            return False
        age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(path))
        return age.total_seconds() < max_age_hours * 3600

    def load_from_cache(self, symbol: str, tf: str, days: int) -> Optional[pd.DataFrame]:
        path = self._cache_path(symbol, tf, days)
        if self._is_cache_valid(path):
            logger.info(f"📂 Memuat dari cache: {path}")
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            logger.info(f"   {len(df)} candle dimuat dari cache")
            return df
        return None

    def save_to_cache(self, df: pd.DataFrame, symbol: str, tf: str, days: int):
        path = self._cache_path(symbol, tf, days)
        df.to_csv(path)
        logger.info(f"💾 Data disimpan ke cache: {path}")

    def download(
        self,
        symbol:  str = "BTCUSDT",
        tf:      str = "1h",
        days:    int = 90,
        use_cache: bool = True,
    ) -> Optional[pd.DataFrame]:
        """
        Download data OHLCV dari Binance Futures.

        Args:
            symbol    : Trading pair (BTCUSDT, ETHUSDT, dll)
            tf        : Timeframe (1m, 5m, 15m, 1h, 4h, 1d)
            days      : Berapa hari ke belakang
            use_cache : Pakai cache lokal jika ada

        Returns:
            DataFrame OHLCV atau None jika gagal
        """
        # Cek cache dulu
        if use_cache:
            cached = self.load_from_cache(symbol, tf, days)
            if cached is not None:
                return cached

        try:
            import requests
        except ImportError:
            logger.error("Library 'requests' tidak tersedia. pip install requests")
            return None

        tf_ms = self.TF_MS.get(tf)
        if not tf_ms:
            logger.error(f"Timeframe '{tf}' tidak valid. Pilihan: {list(self.TF_MS.keys())}")
            return None

        end_ms   = int(datetime.now().timestamp() * 1000)
        start_ms = end_ms - (days * 24 * 60 * 60 * 1000)

        all_candles = []
        current_start = start_ms
        total_expected = (end_ms - start_ms) // tf_ms

        logger.info(f"⬇️  Download data historis Binance Futures")
        logger.info(f"   Symbol   : {symbol}")
        logger.info(f"   Timeframe: {tf}")
        logger.info(f"   Periode  : {days} hari (~{total_expected} candle)")
        logger.info(f"   Sumber   : {self.BASE_URL} (tanpa API Key)")

        request_count = 0
        while current_start < end_ms:
            url = f"{self.BASE_URL}/fapi/v1/klines"
            params = {
                "symbol":    symbol,
                "interval":  tf,
                "startTime": current_start,
                "endTime":   end_ms,
                "limit":     self.LIMIT_PER_REQUEST,
            }

            try:
                resp = requests.get(url, params=params, timeout=15)
                resp.raise_for_status()
                batch = resp.json()
            except requests.exceptions.ConnectionError:
                logger.error("❌ Tidak bisa terhubung ke Binance. Cek koneksi internet.")
                return None
            except requests.exceptions.Timeout:
                logger.error("❌ Request timeout. Coba lagi.")
                return None
            except Exception as e:
                logger.error(f"❌ Error download: {e}")
                return None

            if not batch:
                break

            all_candles.extend(batch)
            request_count += 1

            last_ts = batch[-1][0]
            current_start = last_ts + tf_ms

            downloaded = len(all_candles)
            pct = min(downloaded / total_expected * 100, 100)
            logger.info(f"   Progress : {downloaded}/{total_expected} candle ({pct:.0f}%) — request #{request_count}")

            if len(batch) < self.LIMIT_PER_REQUEST:
                break

        if not all_candles:
            logger.error("Tidak ada data yang berhasil didownload")
            return None

        # Konversi ke DataFrame
        df = pd.DataFrame(all_candles, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_buy_base", "taker_buy_quote", "ignore"
        ])

        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        df = df[["open", "high", "low", "close", "volume"]]
        df = df[~df.index.duplicated(keep="first")]
        df.sort_index(inplace=True)

        logger.info(f"✅ Download selesai: {len(df)} candle")
        logger.info(f"   Dari  : {df.index[0].strftime('%Y-%m-%d %H:%M')}")
        logger.info(f"   Sampai: {df.index[-1].strftime('%Y-%m-%d %H:%M')}")
        logger.info(f"   Harga awal : ${df['close'].iloc[0]:,.2f}")
        logger.info(f"   Harga akhir: ${df['close'].iloc[-1]:,.2f}")

        pct_change = ((df["close"].iloc[-1] - df["close"].iloc[0]) / df["close"].iloc[0]) * 100
        logger.info(f"   Perubahan  : {'+'if pct_change >= 0 else ''}{pct_change:.2f}%")

        # Simpan cache
        if use_cache:
            self.save_to_cache(df, symbol, tf, days)

        return df

    def list_available_symbols(self) -> List[str]:
        """Ambil daftar symbol futures yang tersedia di Binance."""
        try:
            import requests
            resp = requests.get(f"{self.BASE_URL}/fapi/v1/exchangeInfo", timeout=10)
            info = resp.json()
            symbols = [s["symbol"] for s in info["symbols"] if s["status"] == "TRADING"]
            return sorted(symbols)
        except Exception as e:
            logger.error(f"Gagal ambil daftar symbol: {e}")
            return []

    def list_cached_files(self) -> List[str]:
        """Tampilkan file cache yang tersedia."""
        files = [f for f in os.listdir(self.CACHE_DIR) if f.endswith(".csv")]
        return sorted(files)


# ============================================================
# MOCK DATA (fallback jika tidak ada koneksi)
# ============================================================

def generate_mock_data(n: int = 500, base_price: float = 67000) -> pd.DataFrame:
    """Generate data OHLCV simulasi sebagai fallback."""
    dates  = [datetime.now() - timedelta(hours=n - i) for i in range(n)]
    closes = [base_price]
    for _ in range(n - 1):
        closes.append(closes[-1] * (1 + random.gauss(0, 0.008)))

    opens = [c * random.uniform(0.997, 1.003) for c in closes]
    highs = [max(o, c) * random.uniform(1.001, 1.015) for o, c in zip(opens, closes)]
    lows  = [min(o, c) * random.uniform(0.985, 0.999) for o, c in zip(opens, closes)]
    vols  = [random.uniform(800, 3000) for _ in closes]

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=pd.DatetimeIndex(dates),
    )


# ============================================================
# BACKTEST ENGINE
# ============================================================

def run_backtest(
    strategy_name:   str   = "trend_following",
    initial_balance: float = 1000.0,
    data:            pd.DataFrame = None,
    symbol:          str   = "BTCUSDT",
    verbose:         bool  = True,
) -> dict:
    """
    Jalankan backtest pada DataFrame OHLCV.

    Args:
        strategy_name   : Nama strategi
        initial_balance : Modal awal USDT
        data            : DataFrame OHLCV (wajib ada)
        symbol          : Nama symbol untuk logging
        verbose         : Tampilkan log detail
    """
    logger.info(f"🔬 BACKTEST — {strategy_name.upper()} | {symbol}")
    logger.info(f"   Modal   : ${initial_balance:,.2f} USDT")
    logger.info(f"   Candles : {len(data)}")
    logger.info(f"   Periode : {data.index[0].strftime('%Y-%m-%d')} → {data.index[-1].strftime('%Y-%m-%d')}")
    logger.info("=" * 60)

    strategy      = get_strategy(strategy_name)
    indicator_eng = IndicatorEngine()
    risk_mgr      = RiskManager()
    risk_mgr.session_high_balance = initial_balance

    balance  = initial_balance
    trades: List[TradeRecord] = []
    open_pos = None
    warmup   = 60

    for i in range(warmup, len(data)):
        df_slice      = data.iloc[:i + 1]
        ind           = indicator_eng.calculate(df_slice)
        if ind is None:
            continue

        current_price = data["close"].iloc[i]
        ind.close     = current_price

        # Manage posisi terbuka
        if open_pos:
            pnl    = 0.0
            closed = False
            reason = ""

            if open_pos.side == "LONG":
                if current_price <= open_pos.stop_loss:
                    pnl    = -open_pos.risk_amount
                    closed, reason = True, "STOP_LOSS"
                elif current_price >= open_pos.take_profit:
                    pnl    = open_pos.risk_amount * config.risk.rr_ratio
                    closed, reason = True, "TAKE_PROFIT"
            else:
                if current_price >= open_pos.stop_loss:
                    pnl    = -open_pos.risk_amount
                    closed, reason = True, "STOP_LOSS"
                elif current_price <= open_pos.take_profit:
                    pnl    = open_pos.risk_amount * config.risk.rr_ratio
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
                if verbose:
                    emoji = "✅" if pnl > 0 else "❌"
                    logger.debug(
                        f"{emoji} {reason} | {open_pos.side} | "
                        f"Entry:${open_pos.entry_price:.2f} Exit:${current_price:.2f} | "
                        f"PnL:${pnl:+.2f} | Balance:${balance:.2f}"
                    )
                open_pos = None
            continue

        # Cek apakah bisa buka posisi baru
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

        open_pos = Position(
            id=str(uuid.uuid4())[:8],
            symbol=symbol,
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

        if verbose:
            logger.debug(
                f"📥 ENTRY {signal.action} @ ${current_price:.2f} | "
                f"SL:${risk_calc.stop_loss:.2f} TP:${risk_calc.take_profit:.2f} | "
                f"{signal.reason}"
            )

    # ---- Statistik ----
    total     = len(trades)
    wins      = [t for t in trades if t.final_pnl > 0]
    losses    = [t for t in trades if t.final_pnl <= 0]
    total_pnl = sum(t.final_pnl for t in trades)
    win_rate  = (len(wins) / total * 100) if total > 0 else 0
    avg_win   = (sum(t.final_pnl for t in wins) / len(wins)) if wins else 0
    avg_loss  = (sum(t.final_pnl for t in losses) / len(losses)) if losses else 0
    pf_num    = abs(sum(t.final_pnl for t in wins))
    pf_den    = abs(sum(t.final_pnl for t in losses))
    profit_factor = round(pf_num / pf_den, 2) if pf_den > 0 else 0.0
    roi       = ((balance - initial_balance) / initial_balance) * 100

    # Max Drawdown
    eq = initial_balance
    peak, max_dd = initial_balance, 0.0
    for t in trades:
        eq += t.final_pnl
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # Consecutive wins/losses
    max_consec_win = max_consec_loss = cur_w = cur_l = 0
    for t in trades:
        if t.final_pnl > 0:
            cur_w += 1; cur_l = 0
        else:
            cur_l += 1; cur_w = 0
        max_consec_win  = max(max_consec_win, cur_w)
        max_consec_loss = max(max_consec_loss, cur_l)

    results = {
        "strategy":          strategy_name,
        "symbol":            symbol,
        "total_trades":      total,
        "win_count":         len(wins),
        "loss_count":        len(losses),
        "win_rate":          round(win_rate, 2),
        "total_pnl":         round(total_pnl, 2),
        "roi_pct":           round(roi, 2),
        "avg_win":           round(avg_win, 2),
        "avg_loss":          round(avg_loss, 2),
        "profit_factor":     profit_factor,
        "max_drawdown":      round(max_dd, 2),
        "max_consec_win":    max_consec_win,
        "max_consec_loss":   max_consec_loss,
        "final_balance":     round(balance, 2),
    }

    logger.info(f"📊 HASIL BACKTEST — {strategy_name.upper()} | {symbol}")
    logger.info(f"   Total Trade      : {total}")
    logger.info(f"   Win / Loss       : {len(wins)} / {len(losses)}")
    logger.info(f"   Win Rate         : {win_rate:.1f}%")
    logger.info(f"   Total PnL        : ${'+'if total_pnl >= 0 else ''}{total_pnl:.2f}")
    logger.info(f"   ROI              : {'+'if roi >= 0 else ''}{roi:.2f}%")
    logger.info(f"   Avg Win          : ${avg_win:.2f}")
    logger.info(f"   Avg Loss         : ${avg_loss:.2f}")
    logger.info(f"   Profit Factor    : {profit_factor:.2f}")
    logger.info(f"   Max Drawdown     : {max_dd:.2f}%")
    logger.info(f"   Konsekutif Win   : {max_consec_win}")
    logger.info(f"   Konsekutif Loss  : {max_consec_loss}")
    logger.info(f"   Final Balance    : ${balance:,.2f}")
    logger.info("=" * 60)

    return results


def save_results_csv(results_list: list, filename: str = None):
    """Simpan hasil backtest ke CSV."""
    if not results_list:
        return
    os.makedirs("data", exist_ok=True)
    if filename is None:
        filename = f"data/backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    df = pd.DataFrame(results_list)
    df.to_csv(filename, index=False)
    logger.info(f"💾 Hasil disimpan: {filename}")


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="CryptoBot Backtester — Data Real Binance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
  python backtest.py                                   # data simulasi semua strategi
  python backtest.py --real                            # data real Binance (90 hari, 1h)
  python backtest.py --real --days 180 --tf 4h         # 180 hari timeframe 4h
  python backtest.py --real --symbol ETHUSDT           # ETH bukan BTC
  python backtest.py --real --strategy support_bounce  # satu strategi saja
  python backtest.py --real --all                      # bandingkan semua strategi
  python backtest.py --list-cache                      # lihat file cache lokal
  python backtest.py --list-symbols                    # lihat semua symbol Binance
        """
    )

    parser.add_argument("--real",     action="store_true", help="Gunakan data real Binance")
    parser.add_argument("--all",      action="store_true", help="Bandingkan semua strategi")
    parser.add_argument("--strategy", choices=list(STRATEGY_MAP.keys()), default=None)
    parser.add_argument("--symbol",   type=str,   default="BTCUSDT",  help="Trading pair")
    parser.add_argument("--tf",       type=str,   default="1h",       help="Timeframe")
    parser.add_argument("--days",     type=int,   default=90,         help="Berapa hari ke belakang")
    parser.add_argument("--balance",  type=float, default=1000.0,     help="Modal awal USDT")
    parser.add_argument("--candles",  type=int,   default=500,        help="Candle simulasi (jika tidak --real)")
    parser.add_argument("--no-cache", action="store_true",            help="Paksa download ulang")
    parser.add_argument("--save",     action="store_true",            help="Simpan hasil ke CSV")
    parser.add_argument("--list-cache",   action="store_true",        help="Lihat file cache lokal")
    parser.add_argument("--list-symbols", action="store_true",        help="Lihat symbol futures Binance")
    args = parser.parse_args()

    downloader = BinanceDataDownloader()

    # --- List cache ---
    if args.list_cache:
        files = downloader.list_cached_files()
        if files:
            logger.info(f"📂 File cache tersedia ({len(files)}):")
            for f in files:
                path = os.path.join("data", f)
                size = os.path.getsize(path) / 1024
                mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
                logger.info(f"   {f:<40} {size:>7.1f} KB  {mtime}")
        else:
            logger.info("Belum ada file cache. Jalankan dengan --real untuk download.")
        return

    # --- List symbols ---
    if args.list_symbols:
        logger.info("Mengambil daftar symbol dari Binance...")
        symbols = downloader.list_available_symbols()
        if symbols:
            logger.info(f"✅ {len(symbols)} symbol tersedia:")
            for i in range(0, len(symbols), 6):
                row = "   " + "  ".join(f"{s:<12}" for s in symbols[i:i+6])
                logger.info(row)
        return

    # --- Siapkan data ---
    data = None
    if args.real:
        logger.info("📡 Mode: Data Real Binance Futures")
        data = downloader.download(
            symbol=args.symbol,
            tf=args.tf,
            days=args.days,
            use_cache=not args.no_cache,
        )
        if data is None:
            logger.error("❌ Gagal download data. Beralih ke data simulasi...")
            data = generate_mock_data(n=args.candles)
    else:
        logger.info("🎲 Mode: Data Simulasi")
        data = generate_mock_data(n=args.candles)

    # --- Tentukan strategi yang akan ditest ---
    if args.all or (not args.strategy):
        strategies_to_test = list(STRATEGY_MAP.keys())
    else:
        strategies_to_test = [args.strategy]

    # --- Jalankan backtest ---
    all_results = []
    for strat in strategies_to_test:
        result = run_backtest(
            strategy_name=strat,
            initial_balance=args.balance,
            data=data.copy(),
            symbol=args.symbol,
        )
        all_results.append(result)

    # --- Tabel perbandingan jika lebih dari 1 strategi ---
    if len(all_results) > 1:
        logger.info("\n" + "=" * 75)
        logger.info("📊 PERBANDINGAN SEMUA STRATEGI")
        logger.info(f"   Symbol: {args.symbol} | TF: {args.tf if args.real else 'simulasi'} | Modal: ${args.balance:,.0f}")
        logger.info("=" * 75)
        logger.info(
            f"{'Strategi':<20} {'Trades':>7} {'WinRate':>8} "
            f"{'ROI':>8} {'PF':>6} {'MaxDD':>7} {'C.Win':>6} {'C.Loss':>7}"
        )
        logger.info("-" * 75)

        # Urutkan berdasarkan ROI
        sorted_results = sorted(all_results, key=lambda x: x["roi_pct"], reverse=True)
        for r in sorted_results:
            roi_str = f"{'+'if r['roi_pct'] >= 0 else ''}{r['roi_pct']:.2f}%"
            logger.info(
                f"{r['strategy']:<20} "
                f"{r['total_trades']:>7} "
                f"{r['win_rate']:>7.1f}% "
                f"{roi_str:>8} "
                f"{r['profit_factor']:>6.2f} "
                f"{r['max_drawdown']:>6.1f}% "
                f"{r['max_consec_win']:>6} "
                f"{r['max_consec_loss']:>7}"
            )

        logger.info("=" * 75)
        best = sorted_results[0]
        logger.info(
            f"🏆 Strategi terbaik: {best['strategy'].upper()} "
            f"(ROI: {'+'if best['roi_pct'] >= 0 else ''}{best['roi_pct']:.2f}%, "
            f"WinRate: {best['win_rate']:.1f}%)"
        )
        logger.info(
            f"   Gunakan: python main.py --strategy {best['strategy']}"
        )
        logger.info("=" * 75)

    # --- Simpan hasil ---
    if args.save:
        tag = "real" if args.real else "sim"
        fname = f"data/backtest_{args.symbol}_{args.tf if args.real else 'sim'}_{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        save_results_csv(all_results, fname)


if __name__ == "__main__":
    main()

