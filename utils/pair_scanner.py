"""
utils/pair_scanner.py
Scan banyak pair, return pair dengan sinyal terkuat.
"""
from dataclasses import dataclass
from typing import Optional, List
from utils.logger import logger


@dataclass
class PairOpportunity:
    symbol: str
    signal: object
    ind:    object
    score:  float


def scan_pairs(exchange, indicators_engine, strategy,
               symbols: List[str], timeframe: str,
               candle_limit: int = 200) -> Optional[PairOpportunity]:
    """
    Scan daftar pair, return pair dengan signal.strength tertinggi.
    Return None jika tidak ada sinyal valid di semua pair.
    """
    best: Optional[PairOpportunity] = None

    for symbol in symbols:
        try:
            df = exchange.get_klines(symbol, timeframe, candle_limit)
            if df is None or len(df) < 60:
                continue

            df  = df.iloc[:-1]
            ind = indicators_engine.calculate(df)
            if ind is None:
                continue

            signal = strategy.generate_signal(ind)
            if signal.action == "WAIT":
                continue

            logger.debug(f"🔍 {symbol}: {signal.action} score={signal.strength:.2f} | {signal.reason}")

            if best is None or signal.strength > best.score:
                best = PairOpportunity(
                    symbol=symbol,
                    signal=signal,
                    ind=ind,
                    score=signal.strength,
                )
        except Exception as e:
            logger.debug(f"Scanner skip {symbol}: {e}")
            continue

    return best


def get_symbol_precision(client, symbol: str) -> dict:
    """
    Ambil presisi quantity dan price dari Binance.
    Return: {"qty_precision": int, "price_precision": int, "min_qty": float}
    """
    try:
        info = client.futures_exchange_info()
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                qty_precision   = 0
                price_precision = s.get("pricePrecision", 2)
                min_qty         = 0.0
                for f in s["filters"]:
                    if f["filterType"] == "LOT_SIZE":
                        step    = f["stepSize"]
                        min_qty = float(f["minQty"])
                        if "." in step:
                            qty_precision = len(step.rstrip("0").split(".")[1])
                        else:
                            qty_precision = 0
                return {
                    "qty_precision"  : qty_precision,
                    "price_precision": price_precision,
                    "min_qty"        : min_qty,
                }
    except:
        pass
    return {"qty_precision": 1, "price_precision": 2, "min_qty": 0.1}
