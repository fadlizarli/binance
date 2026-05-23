# CryptoBot — Binance Futures Auto Trader

Bot trading otomatis untuk Binance Futures berbasis Python. Dilengkapi manajemen risiko ketat, 4 strategi teknikal, filter Claude AI, notifikasi Telegram, dan dashboard web.

---

## Fitur

- **4 Strategi** — Trend Following, Support Bounce, Breakout, Scalping
- **Indikator** — EMA 9/21/55/200, RSI, MACD, Bollinger Bands, ATR, Volume, Candlestick Pattern
- **Manajemen Risiko** — ATR-based SL/TP, Trailing Stop dinamis, Move to Breakeven, Max Drawdown Guard
- **HTF Filter** — Cek trend 4h sebelum entry di timeframe lebih kecil
- **Fear & Greed Filter** — Skip entry saat Extreme Fear (<20) atau Extreme Greed (>80)
- **Claude AI Risk Adjuster** — Claude Haiku menilai kualitas setup dan menyesuaikan ukuran posisi (tidak pernah memblok entry)
- **Candle Close Confirmation** — Hanya baca candle yang sudah tutup; candle terakhir (belum tutup) selalu dibuang
- **Notifikasi Telegram** — Alert entry, exit, dan ringkasan harian
- **Backtest** — Test semua strategi dengan data historis real dari Binance
- **Dashboard Web** — Monitor posisi, harga live, dan performa via browser
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
│   ├── claude_filter.py     # Risk adjuster via Claude API
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
RISK_PER_TRADE=1.0          # % dari balance per trade (100% = full size)
SL_ATR_MULTIPLIER=1.5       # Jarak SL = ATR × multiplier
RR_RATIO=2.0                # Risk:Reward ratio
MAX_DAILY_DRAWDOWN=3.0      # % max drawdown per hari
MAX_TRADES_PER_DAY=3        # Max posisi per hari

# Telegram (opsional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Claude AI Risk Adjuster (opsional)
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

### Filter Kualitas Sinyal — Trend Following

Strategi `trend_following` memiliki 4 filter wajib sebelum signal dihitung:

1. **EMA200 Macro** — Harga harus di atas EMA200 untuk LONG, di bawah untuk SHORT
2. **Volume Minimum** — `volume_ratio` wajib ≥ 0.8x rata-rata; volume lemah = sinyal tidak valid
3. **RSI Optimal** — Range ketat 35–60 untuk LONG (menghindari overbought dan momentum sudah habis)
4. **Score Threshold 7** — Butuh konfirmasi lebih banyak sebelum entry dibuka

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
- **Volume Filter** — Skip entry jika volume ratio < 0.8x rata-rata
- **Consecutive Loss** — Hentikan entry jika 3 loss berturut-turut
- **EMA200 Macro** — Skip jika harga kontra arah EMA200

---

## Claude AI — Risk Adjuster

Claude berperan sebagai **penilai risiko**, bukan penjaga gerbang. Signal arah sudah dikonfirmasi secara teknikal; Claude hanya menilai kualitas dan risiko setup tersebut.

| Confidence | Ukuran Posisi | Kondisi |
|---|---|---|
| 8–10 | 100% (`RISK_PER_TRADE`) | Setup kuat, kondisi ideal |
| 5–7 | 75% | Setup cukup, ada ketidakpastian |
| 1–4 | 50% | Setup lemah atau kondisi buruk |

Claude tidak pernah memblok entry — hanya menyesuaikan ukuran posisi. Cache 5 menit per signal untuk hemat API call.

---

## Candle Close Confirmation

Bot hanya membaca candle yang sudah **selesai (closed)**. Candle terakhir yang belum tutup selalu dibuang sebelum perhitungan indikator:

```python
df = df.iloc[:-1]   # buang candle terakhir yang belum tutup
```

Ini mencegah false signal akibat data candle yang berubah-ubah di tengah pembentukan.

---

## Dashboard Web

Dashboard membaca log file dan menampilkan status real-time:

- **Harga SOL** — Diambil langsung dari public Binance API (tidak butuh API key); diperbarui setiap request
- **Signal Score** — Menampilkan skor L/S dari hasil evaluasi strategi terakhir
- **Indikator** — EMA, RSI, MACD, BB, Volume diperbarui setiap candle (termasuk saat bot WAIT)
- **Posisi Aktif** — Entry, SL, TP, unrealized PnL, liquidation price
- **Performa** — Win rate, streak, equity curve, long vs short breakdown
- **Log Live** — 40 baris log terbaru

---

## Catatan Keamanan

- Jangan commit file `.env` atau `.envy` ke git
- Selalu test di **TESTNET** sebelum switch ke live
- Gunakan API key dengan permission **Futures only**, tanpa permission withdraw
- Simpan API key di `.env`, tidak pernah hardcode di kode
