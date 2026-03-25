Untuk analisa strategi yang maksimal, saya butuh data berlapis:

---

## 1. Data Performa Bot (Paling Penting)

```bash
# Hasil trade yang sudah terjadi
cat ~/binance/logs/trades_20260313.log

# Statistik lengkap dari log
grep -E "Win|Loss|PnL|ROI|Trade|Balance" ~/binance/logs/cryptobot_20260313.log | tail -30
```

---

## 2. Data Market BTC

```bash
# Jalankan backtest dengan data real terbaru
python backtest.py --real --all --days 365 --tf 15m --save
python backtest.py --real --all --days 365 --tf 1h --save
python backtest.py --real --all --days 365 --tf 4h --save
```

Ini akan hasilkan CSV di `data/` yang bisa saya analisis.

---

## 3. Kondisi Market Saat Ini

```bash
python3 -c "
from exchange.binance_client import BinanceClient
from core.indicators import IndicatorEngine
c = BinanceClient()
df = c.get_klines('BTCUSDT', '1d', limit=30)
eng = IndicatorEngine()
ind = eng.calculate(df)
print('Trend  :', ind.ema_trend)
print('RSI    :', round(ind.rsi, 2))
print('MACD   :', round(ind.macd, 2))
print('ATR    :', round(ind.atr, 2))
print('Vol    :', round(ind.volume_ratio, 2), 'x')
"
```

---

## 4. Data Yang Sudah Ada

Dari sesi kita sebelumnya saya sudah punya:

| Data | Status |
|---|---|
| Backtest 365 hari 15m | ✅ Ada |
| Harga BTC Mar 2025–2026 | ✅ Cache |
| Performa 4 strategi | ✅ Ada |
| Live trade hari ini | ⏳ Perlu |
| Multi-timeframe | ❌ Belum |
| Kondisi market harian | ❌ Belum |

---

## Yang Paling Berguna Sekarang

Jalankan ketiga command ini dan share hasilnya:

```bash
# 1. Trade log hari ini
cat ~/binance/logs/trades_20260313.log

# 2. Backtest multi timeframe
python backtest.py --real --all --days 365 --tf 4h --save
python backtest.py --real --all --days 90 --tf 15m --save

# 3. Kondisi market harian
python3 -c "
from exchange.binance_client import BinanceClient
from core.indicators import IndicatorEngine
c = BinanceClient()
for tf in ['15m','1h','4h','1d']:
    df = c.get_klines('BTCUSDT', tf, limit=100)
    ind = IndicatorEngine().calculate(df)
    print(f'{tf:4} | Trend:{ind.ema_trend:8} | RSI:{ind.rsi:.1f} | Vol:{ind.volume_ratio:.2f}x | MACD:{\"BULL\" if ind.macd > 0 else \"BEAR\"}')
"
```

Dengan data ini saya bisa tentukan:
- Timeframe terbaik untuk kondisi market sekarang
- Strategi mana yang paling cocok
- Parameter optimal (SL multiplier, RR ratio, leverage)
- Jam trading terbaik untuk BTC
