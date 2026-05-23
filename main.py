"""
main.py
Entry point utama CryptoBot.

Cara pakai:
  python main.py                    # Jalankan bot live
  python main.py --backtest         # Jalankan backtest dulu
  python main.py --strategy scalping
  python main.py --symbol ETHUSDT --leverage 3
"""
import sys
import os
import argparse

# Pastikan root project ada di Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import logger


def parse_args():
    parser = argparse.ArgumentParser(
        description="CryptoBot — Binance Futures Auto Trader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh penggunaan:
  python main.py                                      # Bot live (pakai config .env)
  python main.py --backtest                           # Backtest semua strategi (mock data)
  python main.py --backtest --real-data               # Backtest dengan data real Binance
  python main.py --backtest --real-data --days 180    # 180 hari data real
  python main.py --backtest --real-data --tf 1h       # Override timeframe
  python main.py --strategy breakout                  # Override strategi
  python main.py --symbol ETHUSDT                     # Override symbol
  python main.py --leverage 3                         # Override leverage
        """
    )
    parser.add_argument(
        "--backtest", action="store_true",
        help="Jalankan mode backtest (tidak buka order nyata)"
    )
    parser.add_argument(
        "--strategy",
        choices=["trend_following", "support_bounce", "breakout", "scalping"],
        default=None,
        help="Override strategi dari .env"
    )
    parser.add_argument("--symbol", type=str, default=None, help="Override symbol")
    parser.add_argument("--leverage", type=int, default=None, help="Override leverage")
    parser.add_argument("--balance", type=float, default=1000.0, help="Modal backtest")
    parser.add_argument("--candles", type=int, default=500, help="Candle untuk backtest (mock data)")
    parser.add_argument("--real-data", action="store_true", help="Fetch data real dari Binance Futures")
    parser.add_argument("--days", type=int, default=90, help="Jumlah hari data historis (--real-data)")
    parser.add_argument("--tf", type=str, default=None, help="Override timeframe untuk backtest")
    return parser.parse_args()


def print_banner():
    banner = """
╔══════════════════════════════════════════════════╗
║          CRYPTOBOT — Binance Futures             ║
║    Auto Trading dengan Manajemen Risiko Ketat    ║
╚══════════════════════════════════════════════════╝
  Strategi   : Trend Following / Support Bounce /
               Breakout / Scalping
  Indikator  : EMA, RSI, MACD, Bollinger, ATR, Volume
  Risk Mgmt  : ATR-based SL/TP, Trailing Stop,
               Partial TP, Max Drawdown Guard
"""
    print(banner)


def main():
    print_banner()
    args = parse_args()

    # Override config dari argumen CLI
    from config import config
    if args.strategy:
        config.trading.strategy = args.strategy
    if args.symbol:
        config.trading.symbol = args.symbol
    if args.leverage:
        config.trading.leverage = args.leverage

    # --- Mode Backtest ---
    if args.backtest:
        from backtest import run_backtest, generate_mock_data, precompute_indicators, BinanceDataDownloader

        symbol = args.symbol or config.trading.symbol
        tf     = args.tf     or config.trading.timeframe

        # Ambil data
        if args.real_data:
            logger.info(f"🔬 MODE BACKTEST — Data Real Binance Futures")
            dl  = BinanceDataDownloader()
            raw = dl.download(symbol, tf, args.days)
            if raw is None:
                logger.error("❌ Gagal download data. Cek koneksi internet.")
                return
            src = f"{symbol} {tf} {args.days}d (real)"
        else:
            logger.info(f"🔬 MODE BACKTEST — Data Simulasi")
            raw = generate_mock_data(n=args.candles)
            src = f"simulasi {args.candles} candle"

        logger.info(f"⚙️  Menghitung indikator...")
        ind = precompute_indicators(raw)
        logger.info(f"   ✅ {len(ind):,} baris siap")

        # Constraint live trading dari config
        max_trades_day = config.risk.max_trades_per_day
        max_dd_day     = config.risk.max_daily_drawdown
        cons_str = f"LONG ONLY | Max {max_trades_day}tx/hari | MaxDD {max_dd_day}%/hari"
        logger.info(f"⚙️  Constraint live: {cons_str}")

        strategies = [args.strategy] if args.strategy else ["trend_following", "support_bounce", "breakout", "scalping"]
        results = []
        for s in strategies:
            r = run_backtest(
                s, args.balance, ind.copy(), raw, symbol,
                long_only=True,
                max_trades_per_day=max_trades_day,
                max_daily_drawdown=max_dd_day,
            )
            results.append(r)

        if len(results) == 1:
            from backtest import print_result
            print_result(results[0])
        else:
            logger.info("\n" + "=" * 78)
            logger.info(f"📊 PERBANDINGAN SEMUA STRATEGI | {src} | Modal: ${args.balance:,.0f}")
            logger.info(f"   Constraint: {cons_str}")
            logger.info("=" * 78)
            logger.info(f"{'Strategi':<20} {'Trades':>7} {'WinRate':>8} {'ROI':>9} {'PF':>6} {'MaxDD':>7}")
            logger.info("-" * 78)
            for r in sorted(results, key=lambda x: x["roi_pct"], reverse=True):
                roi_s = f"{'+'if r['roi_pct']>=0 else ''}{r['roi_pct']:.2f}%"
                logger.info(
                    f"{r['strategy']:<20} {r['total_trades']:>7} "
                    f"{r['win_rate']:>7.1f}% {roi_s:>9} "
                    f"{r['profit_factor']:>6.2f} {r['max_drawdown']:>6.1f}%"
                )
            logger.info("=" * 78)
            best = max(results, key=lambda x: x["roi_pct"])
            logger.info(f"🏆 Terbaik: {best['strategy'].upper()} | ROI:{'+' if best['roi_pct']>=0 else ''}{best['roi_pct']:.2f}% | WR:{best['win_rate']:.0f}% | Trades:{best['total_trades']}")
        return

    # --- Mode Live Bot ---
    logger.info("🚀 MODE LIVE TRADING")
    logger.warning("⚠️  Pastikan sudah test di TESTNET sebelum live!")
    logger.info(
        f"Config: {config.trading.symbol} | "
        f"{config.trading.timeframe} | "
        f"{config.trading.strategy} | "
        f"Leverage {config.trading.leverage}x | "
        f"Mode: {'TESTNET' if config.api.is_testnet else 'LIVE'}"
    )

    from core.bot_engine import BotEngine
    bot = BotEngine()
    bot.start()


if __name__ == "__main__":
    main()

