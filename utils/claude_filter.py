"""
utils/claude_filter.py
Claude AI sebagai second opinion sebelum eksekusi trade.
"""
import os
from utils.logger import logger


def ask_claude(signal: str, indicators: dict, api_key: str) -> dict:
    """
    Tanya Claude apakah sinyal ini layak dieksekusi.
    
    Returns:
        {"action": "LONG/SHORT/WAIT", "confidence": 1-10, "reason": "..."}
    """
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        prompt = f"""Kamu adalah analis trading crypto profesional.
Analisis kondisi market SOL/USDT berikut dan berikan rekomendasi:

Sinyal Bot  : {signal}
Harga       : ${indicators.get('price', 0):.2f}
EMA Trend   : {indicators.get('ema_trend', 'UNKNOWN')}
RSI         : {indicators.get('rsi', 0):.1f}
MACD        : {indicators.get('macd', 0):.4f}
BB Position : {indicators.get('bb_position', 'UNKNOWN')}
BB Squeeze  : {indicators.get('bb_squeeze', False)}
Volume      : {indicators.get('volume_ratio', 0):.2f}x rata-rata
ATR         : {indicators.get('atr', 0):.2f}
HTF 4h      : {indicators.get('htf_trend', 'UNKNOWN')}

Jawab HANYA dalam format ini (tanpa penjelasan tambahan):
ACTION: LONG atau SHORT atau WAIT
CONFIDENCE: angka 1-10
REASON: alasan singkat 1 kalimat"""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )

        text = response.content[0].text.strip()
        lines = text.split('\n')

        result = {"action": "WAIT", "confidence": 5, "reason": "Tidak bisa parse respons Claude"}
        for line in lines:
            if line.startswith("ACTION:"):
                result["action"] = line.split(":", 1)[1].strip()
            elif line.startswith("CONFIDENCE:"):
                try:
                    result["confidence"] = int(line.split(":", 1)[1].strip())
                except:
                    pass
            elif line.startswith("REASON:"):
                result["reason"] = line.split(":", 1)[1].strip()

        logger.info(
            f"🤖 Claude: {result['action']} "
            f"(confidence: {result['confidence']}/10) | {result['reason']}"
        )
        return result

    except ImportError:
        logger.warning("Library anthropic tidak tersedia. pip install anthropic")
        return {"action": signal, "confidence": 5, "reason": "Claude tidak tersedia"}
    except Exception as e:
        logger.warning(f"Claude filter error: {e} — lanjut tanpa filter")
        return {"action": signal, "confidence": 5, "reason": f"Error: {e}"}


def claude_validate(signal: str, ind, api_key: str, min_confidence: int = 6) -> bool:
    """
    Validasi sinyal dengan Claude.
    Return True jika Claude setuju dan confidence >= min_confidence.
    """
    if not api_key:
        return True  # Skip jika tidak ada API key

    indicators = {
        "price":        ind.close,
        "ema_trend":    ind.ema_trend,
        "rsi":          ind.rsi,
        "macd":         ind.macd,
        "bb_position":  ind.bb_position,
        "bb_squeeze":   ind.bb_squeeze,
        "volume_ratio": ind.volume_ratio,
        "atr":          ind.atr,
        "htf_trend":    getattr(ind, 'htf_trend', 'UNKNOWN'),
    }

    result = ask_claude(signal, indicators, api_key)

    # Claude harus setuju dengan sinyal DAN confidence cukup
    if result["action"] == signal and result["confidence"] >= min_confidence:
        logger.info(f"✅ Claude setuju: {signal} | Confidence: {result['confidence']}/10")
        return True
    else:
        logger.info(
            f"⏭️ Claude tidak setuju: Bot={signal} Claude={result['action']} "
            f"Confidence={result['confidence']}/10 | {result['reason']}"
        )
        return False
