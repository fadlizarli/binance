"""
utils/claude_filter.py — Claude sebagai Risk Adjuster (Opsi B)
Claude tidak memblok entry — hanya memberi confidence score
untuk mengatur ukuran posisi:
  8-10 → full size (100%)
  5-7  → medium size (75%)
  1-4  → reduced size (50%)
"""
import time
from utils.logger import logger

_shared_cache = {"time": 0, "key": None, "confidence": 7}


def _ask_claude(signal: str, indicators: dict, api_key: str) -> int:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        symbol = indicators.get('symbol', 'CRYPTO')
        prompt = f"""Futures trading risk assessment — {symbol}

Signal arah sudah dikonfirmasi secara teknikal: {signal}

Kondisi pasar saat ini:
- Harga   : ${indicators.get('price', 0):.2f}
- EMA     : {indicators.get('ema_trend', '?')} | HTF 4h: {indicators.get('htf_trend', '?')}
- RSI     : {indicators.get('rsi', 50):.0f}
- MACD    : {indicators.get('macd', '0')} (hist: {indicators.get('macd_hist', '0')})
- Volume  : {indicators.get('volume_ratio', 1):.1f}x ({indicators.get('vol_status', 'NORMAL')})
- Pattern : {indicators.get('pattern', 'NONE')}
- BB Squeeze: {indicators.get('bb_squeeze', 'False')}

Tugas kamu: nilai KUALITAS dan RISIKO setup ini — bukan memutuskan arah.
Pertimbangkan: apakah kondisi mendukung trade ini? Ada risiko tersembunyi?

Skala confidence:
8-10 = setup kuat, kondisi ideal → full size
5-7  = setup cukup, ada ketidakpastian → size normal
1-4  = setup lemah atau kondisi buruk → kurangi size

Jawab HANYA:
CONFIDENCE: 1-10
REASON: 1 kalimat"""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=60,
            messages=[{"role": "user", "content": prompt}]
        )

        text = response.content[0].text.strip()
        confidence = 5
        reason = ""
        for line in text.split('\n'):
            if line.startswith("CONFIDENCE:"):
                try:
                    confidence = int(line.split(":", 1)[1].strip())
                    confidence = max(1, min(10, confidence))
                except:
                    pass
            elif line.startswith("REASON:"):
                reason = line.split(":", 1)[1].strip()

        logger.info(f"🤖 Claude Risk: {confidence}/10 | {reason}")
        return confidence

    except ImportError:
        logger.warning("Library anthropic tidak tersedia — pakai confidence default 7")
        return 7
    except Exception as e:
        logger.warning(f"Claude error: {e} — pakai confidence default 7")
        return 7


def claude_get_confidence(signal: str, ind, api_key: str,
                          symbol: str = "") -> int:
    if not api_key:
        return 7

    now = time.time()
    cache_key = f"{signal}_{round(getattr(ind, 'close', 0), 1)}"
    sisa = int(300 - (now - _shared_cache["time"]))

    if sisa > 0 and _shared_cache["key"] == cache_key:
        conf = _shared_cache["confidence"]
        logger.debug(f"🤖 Claude cache ({sisa}s tersisa): confidence={conf}/10")
        return conf

    vol_ratio = getattr(ind, 'volume_ratio', 1.0)
    if vol_ratio >= 1.5:   vol_status = "HIGH"
    elif vol_ratio >= 0.7: vol_status = "NORMAL"
    else:                  vol_status = "LOW"

    pattern = "NONE"
    if getattr(ind, 'hammer', False):
        pattern = "HAMMER"
    if getattr(ind, 'engulfing', 'NONE') != 'NONE':
        pattern = getattr(ind, 'engulfing')

    indicators = {
        "symbol"      : symbol or getattr(ind, 'symbol', 'CRYPTO'),
        "price"       : getattr(ind, 'close', 0),
        "ema_trend"   : getattr(ind, 'ema_trend', 'UNKNOWN'),
        "rsi"         : getattr(ind, 'rsi', 50),
        "volume_ratio": vol_ratio,
        "vol_status"  : vol_status,
        "htf_trend"   : getattr(ind, 'htf_trend', 'UNKNOWN'),
        "macd"        : f"{getattr(ind, 'macd_line', 0):.2f}",
        "macd_hist"   : f"{getattr(ind, 'macd_hist', 0):.3f}",
        "pattern"     : pattern,
        "bb_squeeze"  : str(getattr(ind, "bb_squeeze", False)),
    }

    confidence = _ask_claude(signal, indicators, api_key)

    _shared_cache["time"]       = now
    _shared_cache["key"]        = cache_key
    _shared_cache["confidence"] = confidence

    return confidence
