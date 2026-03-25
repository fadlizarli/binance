Setelah 2 minggu testnet, ini yang harus dilakukan:

---

## 1. Evaluasi Hasil (Hari 14)

```bash
# Lihat semua trade
cat ~/binance/logs/trades_*.log

# Statistik lengkap
grep -E "POSISI DITUTUP|Balance|PnL" ~/binance/logs/cryptobot_*.log
```

**Target minimum sebelum live:**
| Metrik | Target |
|---|---|
| Total trade | ≥ 30 |
| Win rate | ≥ 35% |
| Profit Factor | ≥ 1.1 |
| Max Drawdown | ≤ 20% |
| ROI | Positif |

---

## 2. Jika Hasil Bagus → Persiapan Live

**Keamanan:**
```bash
# Ganti ke API Key LIVE (bukan testnet)
nano ~/binance/.env
```
```env
TRADE_MODE=live
BINANCE_API_KEY=key_live_kamu
BINANCE_SECRET_KEY=secret_live_kamu
```

**Mulai dengan modal kecil dulu:**
```env
# Mulai $30-50, jangan langsung semua modal
RISK_PER_TRADE=1.0
LEVERAGE=2
MAX_DAILY_DRAWDOWN=5.0
```

---

## 3. Checklist Sebelum Live

```
□ SL/TP terbukti bekerja di testnet
□ Minimal 30 trade dengan hasil konsisten  
□ Tidak ada bug posisi tidak tertutup
□ API Key live sudah diset permission Futures
□ Modal yang dipakai adalah uang yang siap hilang
□ Telegram notifikasi aktif
□ Dashboard terpantau rutin
```

---

## 4. Hal yang Perlu Diperbaiki Sebelum Live

Dari pengalaman testnet kita, masih ada yang perlu difix:

**A. SL/TP di exchange** — saat ini dikelola software, kalau VPS mati posisi tidak terlindungi:
```bash
# Perlu implement trailing stop via API alternatif
# Atau gunakan Binance Algo Order API
```

**B. Notifikasi Telegram** — supaya dapat alert tanpa buka dashboard:
```env
TELEGRAM_BOT_TOKEN=isi_token
TELEGRAM_CHAT_ID=isi_chat_id
```

**C. Auto-restart bot** — kalau bot crash, otomatis restart:
```bash
# Buat service systemd
sudo nano /etc/systemd/system/cryptobot.service
```

```ini
[Unit]
Description=CryptoBot Trading
After=network.target

[Service]
User=pixel
WorkingDirectory=/home/pixel/binance
ExecStart=/home/pixel/binance/venv/bin/python main.py --strategy trend_following
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable cryptobot
sudo systemctl start cryptobot
```

---

## 5. Kapan Boleh Live?

```
Testnet profit 2 minggu berturut-turut → boleh live
Testnet masih loss atau break even     → perpanjang testnet
Testnet profit tapi MaxDD > 30%        → turunkan leverage dulu
```

---

Mau saya bantu setup **Telegram notifikasi** atau **auto-restart systemd** sekarang selagi testnet berjalan?
