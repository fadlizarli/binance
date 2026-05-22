# CryptoBot — Binance Futures Auto Trader

Bot trading otomatis untuk Binance Futures berbasis Python. Dilengkapi manajemen risiko ketat, 4 strategi teknikal, filter Claude AI, notifikasi Telegram, dan dashboard web.

---

## Fitur

- **4 Strategi** — Trend Following, Support Bounce, Breakout, Scalping
- **Indikator** — EMA, RSI, MACD, Bollinger Bands, ATR, Volume, Candlestick Pattern
- **Manajemen Risiko** — ATR-based SL/TP, Trailing Stop dinamis, Move to Breakeven, Max Drawdown Guard
- **HTF Filter** — Cek trend 4h sebelum entry di timeframe lebih kecil
- **Fear & Greed Filter** — Skip entry saat Extreme Fear (<20) atau Extreme Greed (>80)
- **Claude AI Filter** — Validasi sinyal menggunakan Claude Haiku sebelum buka posisi
- **Notifikasi Telegram** — Alert entry, exit, dan ringkasan harian
- **Backtest** — Test semua strategi dengan data historis real dari Binance
- **Dashboard Web** — Monitor posisi dan performa via browser
- **Multi-pair** — Support trading beberapa pair sekaligus (opsional)

---

## Struktur Proyek

```
binance/
├── main.py                  # Entry point utama
├── backtest.py              # Engine backtesting
├── dashboard.py             # Dashboard web (Flask)
├── config/
│   └── settings.py          # Konfigurasi dari .env
├── core/
│   ├── bot_engine.py        # Orkestrator loop trading
│   ├── indicators.py        # Perhitungan indikator teknikal
│   └── position.py          # Model posisi & trade record
├── exchange/
│   └── binance_client.py    # Wrapper Binance Futures API
├── risk/
│   └── manager.py           # Engine manajemen risiko
├── strategies/
│   ├── trend_following.py
│   ├── support_bounce.py
│   ├── breakout.py
│   └── scalping.py
├── utils/
│   ├── claude_filter.py     # Validasi sinyal via Claude API
│   ├── notifier.py          # Notifikasi Telegram
│   ├── logger.py            # Setup logging
│   └── pair_scanner.py      # Scanner pair potensial
└── multipair/               # Modul multi-pair (opsional)
```

---

## Instalasi

**1. Clone & buat virtual environment**
```bash
git clone https://github.com/fadlizarli/binance.git
cd binance
python3 -m venv venv
source venv/bin/activate
```

**2. Install dependencies**
```bash
pip install python-binance pandas numpy ta python-dotenv requests \
            colorlog flask anthropic pytz
```

**3. Buat file `.env`**
```bash
cp .env.example .env   # atau buat manual
nano .env
```

---

## Konfigurasi `.env`

```env
# Binance API
BINANCE_API_KEY=your_api_key
BINANCE_SECRET_KEY=your_secret_key
TRADE_MODE=testnet          # testnet | live

# Trading
SYMBOL=SOLUSDT
TIMEFRAME=15m               # 1m 5m 15m 1h 4h
LEVERAGE=2
STRATEGY=trend_following    # trend_following | support_bounce | breakout | scalping

# Manajemen Risiko
RISK_PER_TRADE=1.0          # % dari balance per trade
SL_ATR_MULTIPLIER=1.5       # Jarak SL = ATR × multiplier
RR_RATIO=2.0                # Risk:Reward ratio
MAX_DAILY_DRAWDOWN=5.0      # % max drawdown per hari
MAX_TRADES_PER_DAY=3        # Max posisi per hari

# Telegram (opsional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Claude AI Filter (opsional)
ANTHROPIC_API_KEY=
CLAUDE_FILTER_ENABLED=false

# Multi-pair (opsional, ganti SYMBOL)
# SYMBOLS=SOLUSDT,DOGEUSDT
```

---

## Cara Pakai

### Mode Live
```bash
python main.py
python main.py --strategy breakout
python main.py --symbol ETHUSDT --leverage 3
```

### Mode Backtest
```bash
python main.py --backtest                        # test semua strategi
python main.py --backtest --strategy scalping    # test satu strategi
python main.py --backtest --candles 1000         # lebih banyak data
```

### Dashboard Web
```bash
python dashboard.py
# Buka http://localhost:5000
```

---

## Strategi

| Strategi | Sinyal Utama | Cocok Untuk |
|---|---|---|
| `trend_following` | EMA stack + MACD + pullback | Trending market |
| `support_bounce` | BB Lower/Upper + RSI divergence | Ranging market |
| `breakout` | BB Squeeze + volume konfirmasi | Breakout momen |
| `scalping` | MACD cross + EMA9 | Timeframe kecil (1m-15m) |

---

## Manajemen Risiko

- **SL** — dihitung dari `ATR × SL_ATR_MULTIPLIER`, maksimal 5% dari entry
- **TP** — `SL distance × RR_RATIO`
- **Move to Breakeven** — SL dipindah ke entry saat harga mencapai 50% jarak ke TP
- **Trailing Stop** — Aktif setelah 50% ke TP, semakin ketat mendekati target
- **Max Drawdown** — Bot berhenti buka posisi baru jika drawdown harian ≥ limit
- **Max Trade/Hari** — Batasi frekuensi untuk hindari overtrading

---

## Filter Tambahan

- **HTF Filter** — Hanya entry searah trend 4h (LONG saat 4h bullish, sebaliknya skip)
- **Fear & Greed** — Skip entry jika nilai < 20 (Extreme Fear) atau > 80 (Extreme Greed)
- **Jam Trading** — Hanya entry antara jam 14:00–23:00 WIB
- **Volume Filter** — Skip entry jika volume ratio < 0.3x rata-rata
- **Consecutive Loss** — Hentikan entry jika 3 loss berturut-turut

---

## Multi-pair (Opsional)

Aktifkan setelah trading single-pair stabil minimal 1 bulan. Lihat panduan lengkap di [`multipair/cara_aktivasi.txt`](multipair/cara_aktivasi.txt).

---

## Catatan Keamanan

- Jangan commit file `.env` atau `.envy` ke git
- Selalu test di **TESTNET** sebelum switch ke live
- Gunakan API key dengan permission **Futures only**, tanpa permission withdraw
- Simpan API key di `.env`, tidak pernah hardcode di kode
