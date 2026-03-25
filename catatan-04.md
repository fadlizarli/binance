Setelah 2 minggu, jalankan command ini:

```bash
cd ~/binance
source venv/bin/activate

# Lihat semua trade
grep "POSISI DITUTUP" ~/binance/logs/cryptobot_*.log

# Statistik lengkap
python3 -c "
import re, glob

logs = []
for f in sorted(glob.glob('/home/pixel/binance/logs/cryptobot_*.log')):
    with open(f) as file:
        logs.extend(file.readlines())

trades = []
for line in logs:
    if 'POSISI DITUTUP' in line:
        result = 'WIN' if 'TAKE_PROFIT' in line else 'LOSS'
        trades.append(result)

# Ambil balance awal dan akhir
balance_awal = 5000.0
balance_akhir = balance_awal
for line in logs:
    m = re.search(r'💰 Balance: \\\$([\d,]+\.?\d*)', line)
    if m:
        balance_akhir = float(m.group(1).replace(',',''))

total  = len(trades)
wins   = trades.count('WIN')
losses = trades.count('LOSS')
wr     = wins/total*100 if total else 0
roi    = (balance_akhir - balance_awal) / balance_awal * 100

print('='*40)
print(f'Total Trade : {total}')
print(f'Win / Loss  : {wins} / {losses}')
print(f'Win Rate    : {wr:.1f}%')
print(f'ROI         : {roi:+.2f}%')
print(f'Balance     : \${balance_akhir:,.2f}')
print('='*40)
if wr >= 35 and roi > 0:
    print('✅ HASIL BAGUS — Siap pertimbangkan LIVE')
elif roi < 0:
    print('❌ ROI NEGATIF — Perpanjang testnet')
else:
    print('⚠️  PERLU EVALUASI — Cek strategi')
print('='*40)
"
```

Hasilnya akan langsung kasih rekomendasi apakah siap live atau tidak. Simpan command ini untuk dipakai 2 minggu lagi! 📊
