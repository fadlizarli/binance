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
  python main.py                            # Bot live (pakai config .env)
  python main.py --backtest                 # Backtest semua strategi
  python main.py --strategy breakout        # Override strategi
  python main.py --symbol ETHUSDT           # Override symbol
  python main.py --leverage 3               # Override leverage
  python main.py --backtest --candles 1000  # Backtest lebih banyak data
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
    parser.add_argument("--candles", type=int, default=500, help="Candle untuk backtest")
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
        logger.info("🔬 MODE BACKTEST")
        from backtest import run_backtest, generate_mock_data

        if args.strategy:
            data = generate_mock_data(n=args.candles)
            run_backtest(args.strategy, args.balance, data)
        else:
            # Test semua strategi
            strategies = ["trend_following", "support_bounce", "breakout", "scalping"]
            data = generate_mock_data(n=args.candles)
            results = []
            for s in strategies:
                r = run_backtest(s, args.balance, data)
                results.append(r)

            # Tabel perbandingan
            logger.info("\n" + "=" * 65)
            logger.info("📊 PERBANDINGAN SEMUA STRATEGI")
            logger.info(f"{'Strategi':<20} {'Trades':>7} {'WinRate':>8} {'ROI':>8} {'PF':>6} {'MaxDD':>7}")
            logger.info("-" * 65)
            for r in results:
                logger.info(
                    f"{r['strategy']:<20} "
                    f"{r['total_trades']:>7} "
                    f"{r['win_rate']:>7.1f}% "
                    f"{r['roi_pct']:>+7.2f}% "
                    f"{r['profit_factor']:>6.2f} "
                    f"{r['max_drawdown']:>6.1f}%"
                )
            logger.info("=" * 65)
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

