"""
backtest.py
Backtesting CEPAT dengan data historis real dari Binance Futures.
- Pre-kalkulasi semua indikator sekaligus (bukan per-candle) → 100x lebih cepat
- Tidak ada limit trade harian (khusus backtest)
- Cache data lokal otomatis

Cara pakai:
  python backtest.py --real --all                          # semua strategi, data real
  python backtest.py --real --symbol BTCUSDT --tf 1h --days 365
  python backtest.py --real --strategy breakout --verbose
  python backtest.py --list-cache
  python backtest.py --list-symbols
"""
import sys, os, uuid, random, argparse
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategies import get_strategy, STRATEGY_MAP
from config import config
from utils.logger import logger


# ============================================================
# FAST INDICATOR ENGINE (vectorized, tidak loop per-candle)
# ============================================================

def calc_ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()

def calc_rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta).clip(lower=0).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calc_macd(s: pd.Series, fast=12, slow=26, sig=9):
    ema_f  = calc_ema(s, fast)
    ema_s  = calc_ema(s, slow)
    macd   = ema_f - ema_s
    signal = calc_ema(macd, sig)
    hist   = macd - signal
    return macd, signal, hist

def calc_bb(s: pd.Series, period=20, std_mult=2.0):
    mid   = s.rolling(period).mean()
    sigma = s.rolling(period).std()
    return mid + std_mult * sigma, mid, mid - std_mult * sigma

def calc_atr(high, low, close, period=14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def precompute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Hitung SEMUA indikator sekaligus secara vectorized.
    Ini jauh lebih cepat daripada hitung ulang per-candle.
    """
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    out = pd.DataFrame(index=df.index)

    # EMA
    out["ema9"]  = calc_ema(c, 9)
    out["ema21"] = calc_ema(c, 21)
    out["ema55"] = calc_ema(c, 55)

    # EMA trend
    out["ema_bull"] = (out["ema9"] > out["ema21"]) & (out["ema21"] > out["ema55"])
    out["ema_bear"] = (out["ema9"] < out["ema21"]) & (out["ema21"] < out["ema55"])

    # RSI
    out["rsi"] = calc_rsi(c, 14)

    # MACD
    macd_line, macd_sig, macd_hist = calc_macd(c)
    out["macd"]      = macd_line
    out["macd_sig"]  = macd_sig
    out["macd_hist"] = macd_hist
    # Bullish cross: kemarin negatif, sekarang positif
    macd_diff        = macd_line - macd_sig
    out["macd_bull_cross"] = (macd_diff.shift(1) < 0) & (macd_diff >= 0)
    out["macd_bear_cross"] = (macd_diff.shift(1) > 0) & (macd_diff <= 0)

    # Bollinger Bands
    bb_upper, bb_mid, bb_lower = calc_bb(c)
    out["bb_upper"] = bb_upper
    out["bb_mid"]   = bb_mid
    out["bb_lower"] = bb_lower

    # BB Squeeze: bandwidth < 70% rata-rata 50 periode
    bw              = (bb_upper - bb_lower) / bb_mid
    out["bb_squeeze"] = bw < bw.rolling(50).mean() * 0.7

    # EMA200
    out["ema200"] = calc_ema(c, 200)

    # ATR
    out["atr"] = calc_atr(h, l, c, 14)

    # Volume ratio
    vol_avg          = v.rolling(20).mean()
    out["vol_ratio"] = v / vol_avg.replace(0, np.nan)

    # Harga
    out["close"] = c
    out["high"]  = h
    out["low"]   = l

    return out.dropna()


# ============================================================
# SIGNAL GENERATOR (per baris, dari indikator pre-computed)
# ============================================================

def signal_trend_following(row) -> str:
    # Filter 1: EMA200 — struktur macro harus mendukung
    if row["ema_bull"] and row["close"] < row.get("ema200", 0): return "WAIT"
    if row["ema_bear"] and row["close"] > row.get("ema200", float("inf")): return "WAIT"

    # Filter 2: Volume wajib minimal normal
    if row["vol_ratio"] < 0.8: return "WAIT"

    score_l = score_s = 0
    if row["ema_bull"]:   score_l += 3
    elif row["ema_bear"]: score_s += 3
    else: return "WAIT"

    dist = abs(row["close"] - row["ema21"]) / row["ema21"] * 100
    if dist <= 0.8:
        if row["ema_bull"]: score_l += 2
        else:               score_s += 2
    elif dist > 3.0: return "WAIT"

    if row["macd"] > 0:          score_l += 1
    else:                        score_s += 1
    if row["macd_bull_cross"]:   score_l += 2
    elif row["macd_bear_cross"]: score_s += 2

    # Filter 3: RSI lebih ketat — 35-60 untuk LONG
    if 35 <= row["rsi"] <= 60:   score_l += 1
    elif 35 <= row["rsi"] <= 70: score_s += 1
    elif row["rsi"] > 70:        return "WAIT"
    elif row["rsi"] < 30:        return "WAIT"

    if row["vol_ratio"] >= 1.5: score_l += 1; score_s += 1

    # Filter 4: Threshold lebih tinggi — butuh lebih banyak konfirmasi
    if score_l >= 7 and score_l > score_s: return "LONG"
    if score_s >= 7 and score_s > score_l: return "SHORT"
    return "WAIT"


def signal_support_bounce(row) -> str:
    score_l = score_s = 0
    if row["close"] <= row["bb_lower"]:   score_l += 3
    elif row["close"] >= row["bb_upper"]: score_s += 3

    if row["rsi"] < 30:    score_l += 3
    elif row["rsi"] < 38:  score_l += 2
    elif row["rsi"] > 70:  score_s += 3
    elif row["rsi"] > 62:  score_s += 2

    if row["macd_bull_cross"]: score_l += 1
    elif row["macd_bear_cross"]: score_s += 1

    if row["vol_ratio"] >= 1.5:
        if score_l > score_s: score_l += 1
        else:                 score_s += 1

    if score_l >= 5 and score_l > score_s: return "LONG"
    if score_s >= 5 and score_s > score_l: return "SHORT"
    return "WAIT"


def signal_breakout(row) -> str:
    if not row["bb_squeeze"]: return "WAIT"
    score_l = score_s = 1

    if row["close"] > row["bb_upper"]:    score_l += 3
    elif row["close"] > row["bb_mid"]:    score_l += 1
    elif row["close"] < row["bb_lower"]:  score_s += 3
    elif row["close"] < row["bb_mid"]:    score_s += 1

    if row["vol_ratio"] >= 1.5:   score_l += 2; score_s += 2
    elif row["vol_ratio"] <= 0.6: return "WAIT"

    if row["macd_bull_cross"]:   score_l += 2
    elif row["macd_bear_cross"]: score_s += 2
    elif row["macd"] > 0:        score_l += 1
    else:                        score_s += 1

    if row["ema_bull"]: score_l += 1
    elif row["ema_bear"]: score_s += 1

    if row["rsi"] > 80: score_l = max(0, score_l - 2)

    if score_l >= 6 and score_l > score_s: return "LONG"
    if score_s >= 6 and score_s > score_l: return "SHORT"
    return "WAIT"


def signal_scalping(row) -> str:
    score_l = score_s = 0
    if row["macd_bull_cross"]:   score_l += 4
    elif row["macd_bear_cross"]: score_s += 4
    else: return "WAIT"

    if row["close"] > row["ema9"]: score_l += 2
    else:                          score_s += 2

    if row["rsi"] > 70 or row["rsi"] < 30: return "WAIT"
    if 35 <= row["rsi"] <= 55: score_l += 1
    elif 45 <= row["rsi"] <= 65: score_s += 1

    if row["vol_ratio"] >= 1.5:   score_l += 1; score_s += 1
    elif row["vol_ratio"] <= 0.6: return "WAIT"

    if score_l >= 5 and score_l > score_s: return "LONG"
    if score_s >= 5 and score_s > score_l: return "SHORT"
    return "WAIT"


SIGNAL_FNS = {
    "trend_following": signal_trend_following,
    "support_bounce":  signal_support_bounce,
    "breakout":        signal_breakout,
    "scalping":        signal_scalping,
}


# ============================================================
# BACKTEST ENGINE (vectorized + fast loop)
# ============================================================

def run_backtest(
    strategy_name:   str,
    initial_balance: float,
    ind_df:          pd.DataFrame,   # pre-computed indicators
    raw_df:          pd.DataFrame,   # raw OHLCV
    symbol:          str  = "BTCUSDT",
    verbose:         bool = False,
) -> dict:
    signal_fn   = SIGNAL_FNS[strategy_name]
    rr_ratio    = config.risk.rr_ratio
    sl_mult     = config.risk.sl_atr_multiplier
    risk_pct    = config.risk.risk_per_trade / 100

    balance     = initial_balance
    trades      = []
    open_pos    = None

    # Generate sinyal untuk semua baris sekaligus
    signals = ind_df.apply(signal_fn, axis=1)

    rows    = ind_df.values
    cols    = {c: i for i, c in enumerate(ind_df.columns)}

    for i, (ts, row) in enumerate(ind_df.iterrows()):
        price  = row["close"]
        atr    = row["atr"]
        sig    = signals.iloc[i]

        # Manage posisi
        if open_pos:
            closed, reason, pnl = False, "", 0.0
            if open_pos["side"] == "LONG":
                if price <= open_pos["sl"]:
                    closed, reason, pnl = True, "STOP_LOSS",   -open_pos["risk"]
                elif price >= open_pos["tp"]:
                    closed, reason, pnl = True, "TAKE_PROFIT",  open_pos["risk"] * rr_ratio
            else:
                if price >= open_pos["sl"]:
                    closed, reason, pnl = True, "STOP_LOSS",   -open_pos["risk"]
                elif price <= open_pos["tp"]:
                    closed, reason, pnl = True, "TAKE_PROFIT",  open_pos["risk"] * rr_ratio

            if closed:
                balance += pnl
                trades.append({
                    "side":    open_pos["side"],
                    "entry":   open_pos["entry"],
                    "exit":    price,
                    "sl":      open_pos["sl"],
                    "tp":      open_pos["tp"],
                    "pnl":     round(pnl, 4),
                    "reason":  reason,
                    "open_ts": open_pos["ts"],
                    "close_ts": ts,
                })
                if verbose:
                    em = "✅" if pnl > 0 else "❌"
                    logger.info(f"  {em} {reason} | {open_pos['side']} | ${open_pos['entry']:.2f}→${price:.2f} | PnL:${pnl:+.2f} | Balance:${balance:.2f}")
                open_pos = None
            continue

        # Entry baru
        if sig == "WAIT":
            continue

        sl_dist = atr * sl_mult
        if sl_dist <= 0:
            continue

        sl_pct = sl_dist / price * 100
        if sl_pct > 5.0:   # SL terlalu jauh, skip
            continue

        risk_amt = balance * risk_pct
        if sig == "LONG":
            sl = price - sl_dist
            tp = price + sl_dist * rr_ratio
        else:
            sl = price + sl_dist
            tp = price - sl_dist * rr_ratio

        open_pos = {"side": sig, "entry": price, "sl": sl, "tp": tp, "risk": risk_amt, "ts": ts}

        if verbose:
            logger.info(f"  📥 ENTRY {sig} @ ${price:.2f} | SL:${sl:.2f} TP:${tp:.2f} | Risk:${risk_amt:.2f}")

    # Statistik
    total   = len(trades)
    wins    = [t for t in trades if t["pnl"] > 0]
    losses  = [t for t in trades if t["pnl"] <= 0]
    pnl_tot = sum(t["pnl"] for t in trades)
    wr      = len(wins) / total * 100 if total else 0
    avg_w   = sum(t["pnl"] for t in wins)   / len(wins)   if wins   else 0
    avg_l   = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
    pf_num  = abs(sum(t["pnl"] for t in wins))
    pf_den  = abs(sum(t["pnl"] for t in losses))
    pf      = round(pf_num / pf_den, 2) if pf_den > 0 else 0.0
    roi     = (balance - initial_balance) / initial_balance * 100

    eq = peak = initial_balance
    max_dd = 0.0
    for t in trades:
        eq += t["pnl"]
        peak   = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak * 100)

    mcw = mcl = cw = cl = 0
    for t in trades:
        if t["pnl"] > 0: cw += 1; cl = 0
        else:            cl += 1; cw = 0
        mcw = max(mcw, cw); mcl = max(mcl, cl)

    return {
        "strategy":        strategy_name,
        "symbol":          symbol,
        "total_trades":    total,
        "win_count":       len(wins),
        "loss_count":      len(losses),
        "win_rate":        round(wr, 2),
        "total_pnl":       round(pnl_tot, 2),
        "roi_pct":         round(roi, 2),
        "avg_win":         round(avg_w, 2),
        "avg_loss":        round(avg_l, 2),
        "profit_factor":   pf,
        "max_drawdown":    round(max_dd, 2),
        "max_consec_win":  mcw,
        "max_consec_loss": mcl,
        "final_balance":   round(balance, 2),
        "trades":          trades,
    }


def print_result(r: dict):
    roi_s = f"{'+'if r['roi_pct']>=0 else ''}{r['roi_pct']:.2f}%"
    logger.info("=" * 60)
    logger.info(f"📊 {r['strategy'].upper()} | {r['symbol']}")
    logger.info(f"   Trades     : {r['total_trades']}  (Win:{r['win_count']} Loss:{r['loss_count']})")
    logger.info(f"   Win Rate   : {r['win_rate']:.1f}%")
    logger.info(f"   ROI        : {roi_s}")
    logger.info(f"   Total PnL  : ${r['total_pnl']:+.2f}")
    logger.info(f"   Avg Win    : ${r['avg_win']:.2f}  |  Avg Loss: ${r['avg_loss']:.2f}")
    logger.info(f"   Profit Factor : {r['profit_factor']:.2f}")
    logger.info(f"   Max Drawdown  : {r['max_drawdown']:.2f}%")
    logger.info(f"   Konsekutif Win/Loss : {r['max_consec_win']} / {r['max_consec_loss']}")
    logger.info(f"   Final Balance : ${r['final_balance']:,.2f}")
    logger.info("=" * 60)


# ============================================================
# BINANCE DOWNLOADER
# ============================================================

class BinanceDataDownloader:
    BASE_URL  = "https://fapi.binance.com"
    CACHE_DIR = "data"
    LIMIT     = 1500

    TF_MS = {
        "1m":60000,"3m":180000,"5m":300000,"15m":900000,"30m":1800000,
        "1h":3600000,"2h":7200000,"4h":14400000,"6h":21600000,
        "8h":28800000,"12h":43200000,"1d":86400000,"1w":604800000,
    }

    def __init__(self):
        os.makedirs(self.CACHE_DIR, exist_ok=True)

    def _cache_path(self, symbol, tf, days):
        return os.path.join(self.CACHE_DIR, f"{symbol}_{tf}_{days}d.csv")

    def _cache_valid(self, path, max_hours=4):
        if not os.path.exists(path): return False
        age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(path))
        return age.total_seconds() < max_hours * 3600

    def load_cache(self, symbol, tf, days):
        p = self._cache_path(symbol, tf, days)
        if self._cache_valid(p):
            logger.info(f"📂 Cache: {os.path.basename(p)}")
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            logger.info(f"   {len(df)} candle dimuat dari cache")
            return df
        return None

    def download(self, symbol="BTCUSDT", tf="1h", days=90, use_cache=True):
        if use_cache:
            cached = self.load_cache(symbol, tf, days)
            if cached is not None: return cached

        try:
            import requests
        except ImportError:
            logger.error("pip install requests"); return None

        tf_ms   = self.TF_MS.get(tf)
        if not tf_ms:
            logger.error(f"TF tidak valid: {tf}"); return None

        end_ms   = int(datetime.now().timestamp() * 1000)
        start_ms = end_ms - days * 86400000
        total    = (end_ms - start_ms) // tf_ms

        logger.info(f"⬇️  Binance Futures | {symbol} {tf} {days}d (~{total:,} candle)")

        all_rows, cur, req = [], start_ms, 0
        while cur < end_ms:
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/fapi/v1/klines",
                    params={"symbol":symbol,"interval":tf,"startTime":cur,"endTime":end_ms,"limit":self.LIMIT},
                    timeout=20,
                )
                resp.raise_for_status()
                batch = resp.json()
            except Exception as e:
                logger.error(f"Download error: {e}"); return None

            if not batch: break
            all_rows.extend(batch)
            req += 1
            pct = min(len(all_rows)/total*100, 100)
            logger.info(f"   [{pct:5.1f}%] {len(all_rows):,}/{total:,} candle — request #{req}")
            cur = batch[-1][0] + tf_ms
            if len(batch) < self.LIMIT: break

        if not all_rows:
            logger.error("Tidak ada data"); return None

        df = pd.DataFrame(all_rows, columns=[
            "timestamp","open","high","low","close","volume",
            "ct","qv","trades","tbb","tbq","ignore"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        for c in ["open","high","low","close","volume"]:
            df[c] = df[c].astype(float)
        df = df[["open","high","low","close","volume"]]
        df = df[~df.index.duplicated()].sort_index()

        chg = (df["close"].iloc[-1] - df["close"].iloc[0]) / df["close"].iloc[0] * 100
        logger.info(f"✅ {len(df):,} candle | {df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')}")
        logger.info(f"   ${df['close'].iloc[0]:,.2f} → ${df['close'].iloc[-1]:,.2f}  ({'+'if chg>=0 else ''}{chg:.2f}%)")

        df.to_csv(self._cache_path(symbol, tf, days))
        logger.info(f"💾 Cache disimpan")
        return df

    def list_symbols(self):
        try:
            import requests
            resp = requests.get(f"{self.BASE_URL}/fapi/v1/exchangeInfo", timeout=10)
            return sorted(s["symbol"] for s in resp.json()["symbols"] if s["status"]=="TRADING")
        except Exception as e:
            logger.error(f"Error: {e}"); return []

    def list_cache(self):
        return sorted(f for f in os.listdir(self.CACHE_DIR) if f.endswith(".csv"))


# ============================================================
# MOCK DATA
# ============================================================

def generate_mock_data(n=500, base=67000):
    dates  = [datetime.now() - timedelta(hours=n-i) for i in range(n)]
    closes = [base]
    for _ in range(n-1):
        closes.append(closes[-1] * (1 + random.gauss(0, 0.008)))
    opens = [c * random.uniform(0.997, 1.003) for c in closes]
    highs = [max(o,c) * random.uniform(1.001, 1.015) for o,c in zip(opens,closes)]
    lows  = [min(o,c) * random.uniform(0.985, 0.999) for o,c in zip(opens,closes)]
    vols  = [random.uniform(800, 3000) for _ in closes]
    return pd.DataFrame({"open":opens,"high":highs,"low":lows,"close":closes,"volume":vols},
                        index=pd.DatetimeIndex(dates))


# ============================================================
# MAIN CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="CryptoBot Backtester — Fast Vectorized",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
  python backtest.py --real --all                      # semua strategi data real
  python backtest.py --real --days 365 --tf 1h         # 1 tahun timeframe 1h
  python backtest.py --real --symbol ETHUSDT --tf 4h   # ETH 4h
  python backtest.py --real --strategy breakout --verbose
  python backtest.py --real --all --save               # simpan hasil CSV
  python backtest.py --list-cache                      # lihat cache lokal
  python backtest.py --list-symbols                    # semua symbol Binance
        """
    )
    parser.add_argument("--real",         action="store_true")
    parser.add_argument("--all",          action="store_true")
    parser.add_argument("--strategy",     choices=list(STRATEGY_MAP.keys()), default=None)
    parser.add_argument("--symbol",       default="BTCUSDT")
    parser.add_argument("--tf",           default="1h")
    parser.add_argument("--days",         type=int,   default=90)
    parser.add_argument("--balance",      type=float, default=1000.0)
    parser.add_argument("--candles",      type=int,   default=1000)
    parser.add_argument("--no-cache",     action="store_true")
    parser.add_argument("--save",         action="store_true")
    parser.add_argument("--verbose",      action="store_true")
    parser.add_argument("--list-cache",   action="store_true")
    parser.add_argument("--list-symbols", action="store_true")
    args = parser.parse_args()

    dl = BinanceDataDownloader()

    if args.list_cache:
        files = dl.list_cache()
        if files:
            logger.info(f"📂 Cache ({len(files)} file):")
            for f in files:
                p  = os.path.join("data", f)
                sz = os.path.getsize(p)/1024
                mt = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")
                logger.info(f"   {f:<45} {sz:>7.1f}KB  {mt}")
        else:
            logger.info("Belum ada cache.")
        return

    if args.list_symbols:
        syms = dl.list_symbols()
        logger.info(f"✅ {len(syms)} symbol Binance Futures:")
        for i in range(0, len(syms), 6):
            logger.info("   " + "  ".join(f"{s:<12}" for s in syms[i:i+6]))
        return

    # Ambil data
    if args.real:
        raw = dl.download(args.symbol, args.tf, args.days, not args.no_cache)
        if raw is None:
            logger.warning("Download gagal, pakai simulasi"); raw = generate_mock_data(args.candles)
    else:
        logger.info(f"🎲 Data simulasi ({args.candles} candle)")
        raw = generate_mock_data(args.candles)

    # Pre-kalkulasi indikator SEKALI untuk semua strategi
    logger.info("⚙️  Menghitung indikator...")
    ind_df = precompute_indicators(raw)
    logger.info(f"   ✅ {len(ind_df):,} baris indikator siap")

    strategies = list(STRATEGY_MAP.keys()) if (args.all or not args.strategy) else [args.strategy]

    logger.info("=" * 60)
    logger.info(f"🚀 Menjalankan {len(strategies)} strategi...")
    logger.info("=" * 60)

    all_results = []
    for strat in strategies:
        logger.info(f"   ▶ {strat}...")
        r = run_backtest(strat, args.balance, ind_df.copy(), raw, args.symbol, args.verbose)
        all_results.append(r)
        if len(strategies) == 1:
            print_result(r)
        else:
            roi_s = f"{'+'if r['roi_pct']>=0 else ''}{r['roi_pct']:.2f}%"
            logger.info(f"     Trades:{r['total_trades']} WR:{r['win_rate']:.0f}% ROI:{roi_s} PF:{r['profit_factor']:.2f} MaxDD:{r['max_drawdown']:.1f}%")

    # Tabel perbandingan
    if len(all_results) > 1:
        logger.info("\n" + "=" * 78)
        src = f"{args.symbol} {args.tf} {args.days}d (real)" if args.real else f"simulasi {args.candles}c"
        logger.info(f"📊 PERBANDINGAN STRATEGI | {src} | Modal: ${args.balance:,.0f}")
        logger.info("=" * 78)
        logger.info(f"{'Strategi':<20} {'Trades':>7} {'WinRate':>8} {'ROI':>9} {'PF':>6} {'MaxDD':>7} {'C.Win':>6} {'C.Loss':>7}")
        logger.info("-" * 78)
        for r in sorted(all_results, key=lambda x: x["roi_pct"], reverse=True):
            roi_s = f"{'+'if r['roi_pct']>=0 else ''}{r['roi_pct']:.2f}%"
            logger.info(
                f"{r['strategy']:<20} {r['total_trades']:>7} {r['win_rate']:>7.1f}% "
                f"{roi_s:>9} {r['profit_factor']:>6.2f} {r['max_drawdown']:>6.1f}% "
                f"{r['max_consec_win']:>6} {r['max_consec_loss']:>7}"
            )
        logger.info("=" * 78)
        best = max(all_results, key=lambda x: x["roi_pct"])
        logger.info(f"🏆 Terbaik: {best['strategy'].upper()} | ROI:{'+' if best['roi_pct']>=0 else ''}{best['roi_pct']:.2f}% | WR:{best['win_rate']:.0f}% | Trades:{best['total_trades']}")
        logger.info(f"   Jalankan: python main.py --strategy {best['strategy']}")
        logger.info("=" * 78)

    if args.save:
        os.makedirs("data", exist_ok=True)
        tag  = f"{args.symbol}_{args.tf}_real" if args.real else "sim"
        path = f"data/backtest_{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        rows = [{k:v for k,v in r.items() if k != "trades"} for r in all_results]
        pd.DataFrame(rows).to_csv(path, index=False)
        logger.info(f"💾 Hasil disimpan: {path}")


if __name__ == "__main__":
    main()

