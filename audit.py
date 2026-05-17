import glob, re
from datetime import datetime

trades = []
files = sorted(glob.glob("logs/cryptobot_*.log"))

for path in files:
    with open(path) as f:
        lines = f.readlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "POSISI DITUTUP" in line:
            date = line[:19]
            reason = "TAKE_PROFIT" if "TAKE_PROFIT" in line else "STOP_LOSS"
            if i + 1 < len(lines):
                detail = lines[i+1].strip()
                side = "LONG" if "LONG" in detail else "SHORT"
                em = re.search(r"Entry: \$([\d.]+)", detail)
                xm = re.search(r"Exit: \$([\d.]+)", detail)
                pm = re.search(r"PnL: \$([+-]?[\d.]+)", detail)
                if em and xm:
                    pnl = float(pm.group(1)) if pm else 0
                    pnl = round(pnl/3 if date < "2026-03-21" else pnl, 2)
                    # Cari ATR dan Claude dari log sebelum entry
                    atr_pct = 0; claude = 0; strength = 0
                    for j in range(max(0, i-30), i):
                        l = lines[j].strip()
                        m = re.search(r"ENTRY DETAIL.*ATR: ([\d.]+)%.*Claude: (\d+).*Strength: ([\d.]+)", l)
                        if m:
                            atr_pct = float(m.group(1))
                            claude = int(m.group(2))
                            strength = float(m.group(3))
                            break
                    trades.append({
                        "date": date, "side": side,
                        "entry": float(em.group(1)),
                        "exit": float(xm.group(1)),
                        "pnl": pnl, "reason": reason,
                        "result": "WIN" if pnl > 0 else "LOSS",
                        "atr_pct": atr_pct,
                        "claude": claude,
                        "strength": strength
                    })
        i += 1

live = [t for t in trades if t["date"] >= "2026-03-27"]
wins = [t for t in live if t["pnl"] > 0]
losses = [t for t in live if t["pnl"] <= 0]
aw = sum(t["pnl"] for t in wins)/len(wins) if wins else 0
al = sum(t["pnl"] for t in losses)/len(losses) if losses else 0
wr = len(wins)/len(live) if live else 0
expectancy = (wr * aw) - ((1-wr) * abs(al))

print("=" * 55)
print("AUDIT LENGKAP")
print("=" * 55)
print(f"Total trade   : {len(live)}")
print(f"Win / Loss    : {len(wins)}W {len(losses)}L")
print(f"Win Rate      : {wr*100:.1f}%")
print(f"Avg Win       : ${aw:.2f}")
print(f"Avg Loss      : ${al:.2f}")
print(f"R:R Aktual    : {abs(aw/al):.2f}" if al else "")
print(f"Profit Factor : {abs(sum(t['pnl'] for t in wins)/sum(t['pnl'] for t in losses)):.2f}" if losses else "")
print(f"Expectancy    : ${expectancy:.3f} per trade")
print(f"Total PnL     : ${sum(t['pnl'] for t in live):+.2f}")

print("\n--- Target ---")
print(f"WR target     : 38-48%  ← {'✅' if 38<=wr*100<=48 else '❌'}")
print(f"Avg win target: >$1.30  ← {'✅' if aw>1.30 else f'❌ (perlu naik ${1.30-aw:.2f})'}")
print(f"Avg loss target:<$1.10 ← {'✅' if abs(al)<1.10 else '❌'}")
print(f"Expectancy    : >$0     ← {'✅' if expectancy>0 else f'❌ ({expectancy:.3f})'}")
