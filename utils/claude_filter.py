"""
utils/claude_filter.py — Claude AI filter v3
- Cache key pakai signal + harga
- Volume status lebih deskriptif
- Claude modifier bukan veto absolute
"""
import time
from utils.logger import logger

_shared_cache = {"time": 0, "key": None, "result": None}

def ask_claude(signal: str, indicators: dict, api_key: str) -> dict:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        prompt = f"""SOL/USDT futures signal:
Signal:{signal} Price:${indicators.get('price',0):.2f}
EMA:{indicators.get('ema_trend','?')} RSI:{indicators.get('rsi',50):.0f}
Vol:{indicators.get('volume_ratio',1):.1f}x ({indicators.get('vol_status','NORMAL')})
HTF:{indicators.get('htf_trend','?')} MACD:{indicators.get('macd','0')}
Pattern:{indicators.get('pattern','NONE')}
BB_Squeeze:{indicators.get('bb_squeeze','False')}
MACD_hist:{indicators.get('macd_hist','0')}

Panduan BB Squeeze:
- Squeeze True + volume rendah: WAIT, tunggu arah breakout
- Squeeze True + volume tinggi: ikuti arah breakout
- Squeeze False: lebih aman untuk entry

Panduan Volume:
- Volume > 1.5x : Tinggi, konfirmasi kuat
- Volume 0.7-1.5x: Normal, OK untuk entry
- Volume 0.3-0.7x: Rendah, hati-hati
- Volume < 0.3x : Sangat rendah, hindari entry

Panduan RSI:
- RSI 30-50: zona ideal LONG (oversold recovery) ✅
- RSI 50-65: momentum naik, bagus untuk LONG ✅
- RSI 65-75: hati-hati mendekati overbought ⚠️
- RSI >75  : overbought, hindari LONG ❌

Jawab HANYA:
ACTION: LONG atau SHORT atau WAIT
CONFIDENCE: 1-10
REASON: 1 kalimat"""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            messages=[{"role": "user", "content": prompt}]
        )

        text   = response.content[0].text.strip()
        result = {"action": "WAIT", "confidence": 5, "reason": "Parse error"}
        for line in text.split('\n'):
            if line.startswith("ACTION:"):
                result["action"] = line.split(":", 1)[1].strip()
            elif line.startswith("CONFIDENCE:"):
                try: result["confidence"] = int(line.split(":", 1)[1].strip())
                except: pass
            elif line.startswith("REASON:"):
                result["reason"] = line.split(":", 1)[1].strip()

        logger.info(f"🤖 Claude API: {result['action']} ({result['confidence']}/10) | {result['reason']}")
        return result

    except ImportError:
        logger.warning("Library anthropic tidak tersedia")
        return {"action": signal, "confidence": 5, "reason": "Claude tidak tersedia"}
    except Exception as e:
        logger.warning(f"Claude filter error: {e} — lanjut tanpa filter")
        return {"action": signal, "confidence": 5, "reason": f"Error: {e}"}


def _get_last_confidence() -> int:
    if _shared_cache["result"]:
        return _shared_cache["result"].get("confidence", 7)
    return 7


def _make_decision(signal: str, result: dict,
                   min_confidence: int, signal_strength: float) -> bool:
    action     = result["action"]
    confidence = result["confidence"]

    # Claude setuju + confidence cukup → entry
    if action == signal and confidence >= min_confidence:
        logger.info(f"✅ Claude setuju: {signal} | Confidence: {confidence}/10")
        return True

    # Claude setuju tapi confidence rendah → block
    if action == signal and confidence < min_confidence:
        logger.info(f"⏭️ Claude setuju tapi confidence rendah: {confidence}/10 < {min_confidence}")
        return False

    # Claude WAIT tapi signal teknikal sangat kuat → tetap entry
    if action == "WAIT" and signal_strength >= 0.88:
        logger.info(f"⚠️ Claude WAIT tapi signal sangat kuat ({signal_strength:.2f}) → tetap entry")
        return True

    # Claude berlawanan arah → block total
    if action != signal and action != "WAIT":
        logger.info(f"❌ Claude berlawanan: Bot={signal} Claude={action} → block")
        return False

    # Default: Claude WAIT + signal tidak cukup kuat → block
    logger.info(f"⏭️ Claude tidak setuju: Bot={signal} Claude={action} Confidence={confidence}/10")
    return False


def claude_validate(signal: str, ind, api_key: str,
                    min_confidence: int = 7) -> bool:
    if not api_key:
        return True

    now = time.time()

    # Cache key pakai signal + harga (bukan signal saja)
    cache_key       = f"{signal}_{round(getattr(ind, 'close', 0), 1)}"
    sisa            = int(300 - (now - _shared_cache["time"]))
    signal_strength = getattr(ind, '_signal_strength', 0.5)

    # Pakai cache kalau < 5 menit dan key sama
    if sisa > 0 and _shared_cache["key"] == cache_key and _shared_cache["result"]:
        logger.debug(f"🤖 Claude cache ({sisa}s tersisa): {_shared_cache['result']['action']}")
        return _make_decision(signal, _shared_cache["result"],
                              min_confidence, signal_strength)

    # Volume status
    vol_ratio  = getattr(ind, 'volume_ratio', 1.0)
    if vol_ratio >= 1.5:   vol_status = "HIGH"
    elif vol_ratio >= 0.7: vol_status = "NORMAL"
    else:                  vol_status = "LOW"

    # Pattern
    pattern = "NONE"
    if getattr(ind, 'hammer', False):
        pattern = "HAMMER"
    if getattr(ind, 'engulfing', 'NONE') != 'NONE':
        pattern = getattr(ind, 'engulfing')

    indicators = {
        "price"       : getattr(ind, 'close', 0),
        "ema_trend"   : getattr(ind, 'ema_trend', 'UNKNOWN'),
        "rsi"         : getattr(ind, 'rsi', 50),
        "volume_ratio": vol_ratio,
        "vol_status"  : vol_status,
        "htf_trend"   : getattr(ind, 'htf_trend', 'UNKNOWN'),
        "macd"        : f"{getattr(ind, 'macd_line', 0):.2f}",
        "pattern"     : pattern,
        "bb_squeeze"  : str(getattr(ind, "bb_squeeze", False)),
        "macd_hist"   : f"{getattr(ind, 'macd_hist', 0):.3f}",
    }

    result = ask_claude(signal, indicators, api_key)

    # Update shared cache
    _shared_cache["time"]   = now
    _shared_cache["key"]    = cache_key
    _shared_cache["result"] = result

    return _make_decision(signal, result, min_confidence, signal_strength)
