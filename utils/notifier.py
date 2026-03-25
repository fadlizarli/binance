import requests
from utils.logger import logger

class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token   = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)

    def send(self, message: str) -> bool:
        if not self.enabled:
            return False
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.warning(f"Telegram error: {e}")
            return False

    def notify_entry(self, side, symbol, entry, sl, tp, risk, strategy):
        emoji = "🟢" if side == "LONG" else "🔴"
        self.send(
            f"{emoji} <b>ENTRY {side}</b>\n"
            f"📊 <b>{symbol}</b>\n"
            f"📍 Entry : <code>${entry:,.2f}</code>\n"
            f"🛑 SL    : <code>${sl:,.2f}</code>\n"
            f"🎯 TP    : <code>${tp:,.2f}</code>\n"
            f"💰 Risk  : <code>${risk:.2f}</code>\n"
            f"🧠 Strat : <code>{strategy}</code>"
        )

    def notify_exit(self, side, symbol, entry, exit_price, pnl, reason):
        emoji = "✅" if pnl > 0 else "❌"
        self.send(
            f"{emoji} <b>EXIT {side}</b>\n"
            f"📊 <b>{symbol}</b>\n"
            f"📍 Entry : <code>${entry:,.2f}</code>\n"
            f"📤 Exit  : <code>${exit_price:,.2f}</code>\n"
            f"💵 PnL   : <code>{'+'if pnl>=0 else ''}{pnl:.2f} USDT</code>\n"
            f"📋 Alasan: <code>{reason}</code>"
        )

    def notify_daily_summary(self, trades, wins, pnl, balance):
        wr = (wins/trades*100) if trades > 0 else 0
        self.send(
            f"📊 <b>Ringkasan Harian</b>\n"
            f"🔢 Total  : <code>{trades}</code>\n"
            f"🎯 WinRate: <code>{wr:.1f}%</code>\n"
            f"💵 PnL    : <code>{'+'if pnl>=0 else ''}{pnl:.2f}</code>\n"
            f"💰 Balance: <code>${balance:,.2f}</code>"
        )
