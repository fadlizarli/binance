# 🤖 CryptoBot — Binance Futures Auto Trader

Bot trading otomatis untuk Binance Futures dengan manajemen risiko ketat,
dibangun secara modular menggunakan Python.

---

## 📁 Struktur Proyek

```
cryptobot/
├── main.py              ← Entry point utama
├── backtest.py          ← Modul backtesting
├── requirements.txt
├── .env.example         ← Template konfigurasi
│
├── config/
│   └── settings.py      ← Semua konfigurasi (baca dari .env)
│
├── core/
│   ├── indicators.py    ← Engine kalkulasi indikator teknikal
│   ├── position.py      ← Model data posisi & trade record
│   └── bot_engine.py    ← Orkestrator utama bot
│
├── strategies/
│   ├── base.py          ← Abstract base class strategi
│   ├── trend_following.py
│   ├── support_bounce.py
│   ├── breakout.py
│   └── scalping.py
│
├── risk/
│   └── manager.py       ← Kalkulasi SL/TP, position size, drawdown
│
├── exchange/
│   └── binance_client.py ← Wrapper Binance Futures API
│
└── utils/
    ├── logger.py         ← Logging berwarna + file
    └── notifier.py       ← Notifikasi Telegram
```

---

## ⚙️ Instalasi

```bash
# 1. Clone / copy folder ini
cd cryptobot

# 2. Install dependencies
pip install -r requirements.txt

# 3. Buat file .env
cp .env.example .env
# Edit .env dan isi API Key

# 4. Jalankan backtest dulu
python main.py --backtest

# 5. Jalankan bot (testnet dulu!)
python main.py
```

---

## 🔑 Konfigurasi API Key

1. Buka [Binance Testnet Futures](https://testnet.binancefuture.com)
2. Buat akun testnet
3. Generate API Key dengan izin **Futures Only**
4. **JANGAN** centang izin withdrawal!
5. Isi di file `.env`:

```env
BINANCE_API_KEY=xxx
BINANCE_SECRET_KEY=xxx
TRADE_MODE=testnet
```

---

## 📈 Strategi yang Tersedia

| Strategi | Timeframe | Cocok Untuk |
|---|---|---|
| `trend_following` | 1h / 4h | Trending market |
| `support_bounce` | 4h / 1d | Ranging market |
| `breakout` | 1h / 4h | Volatilitas rendah sebelum breakout |
| `scalping` | 15m / 1h | Intraday, target cepat |

---

## 🛡️ Manajemen Risiko

- **Position Size** dihitung otomatis berdasarkan % risiko dan ATR
- **Stop Loss** = ATR × 1.5 (default), otomatis diset
- **Take Profit** = SL × R:R ratio (default 2:1)
- **Trailing Stop** aktif setelah profit 1%
- **Breakeven** SL pindah ke entry setelah profit 50% menuju TP
- **Max Drawdown** harian bot auto-stop
- **Max Trade/hari** dibatasi

---

## 🚀 Cara Penggunaan

```bash
# Backtest semua strategi
python main.py --backtest

# Backtest strategi spesifik
python main.py --backtest --strategy breakout --candles 1000

# Jalankan bot dengan config default (.env)
python main.py

# Override strategi
python main.py --strategy scalping

# Override symbol dan leverage
python main.py --symbol ETHUSDT --leverage 3
```

---

## 📱 Notifikasi Telegram (Opsional)

1. Buat bot Telegram via [@BotFather](https://t.me/botfather)
2. Dapatkan token bot
3. Dapatkan Chat ID kamu
4. Isi di `.env`:

```env
TELEGRAM_BOT_TOKEN=xxx:xxx
TELEGRAM_CHAT_ID=xxx
```

---

## ⚠️ PERINGATAN RISIKO

> **Trading futures crypto mengandung risiko tinggi kehilangan seluruh modal.**
>
> - Selalu gunakan **Testnet** minimal 1-3 bulan sebelum live
> - Mulai dengan modal kecil jika live
> - Leverage **maksimal 5x** untuk pemula
> - Jangan pernah trading dengan uang yang tidak siap hilang
> - Bot ini adalah **alat bantu**, bukan jaminan profit

---

## 🔧 Menambah Strategi Baru

1. Buat file baru di `strategies/`
2. Inherit dari `BaseStrategy`
3. Implement method `generate_signal()`
4. Daftarkan di `strategies/__init__.py`

```python
# strategies/my_strategy.py
from strategies.base import BaseStrategy, Signal
from core.indicators import IndicatorResult

class MyStrategy(BaseStrategy):
    name = "my_strategy"

    def generate_signal(self, ind: IndicatorResult) -> Signal:
        if ind.rsi < 30 and ind.ema_trend == "BULLISH":
            return self._make_signal("LONG", 0.8, "RSI oversold + EMA bullish")
        return self._wait("Belum ada setup")
```

