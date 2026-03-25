"""
dashboard.py — CryptoBot Web Dashboard
Akses: http://IP_VPS:5000

Install: pip install flask
Jalankan: python dashboard.py
"""
import os
import re
import glob
from datetime import datetime
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Cache Binance client agar tidak reconnect setiap request
_binance_client = None
def get_binance_client():
    global _binance_client
    if _binance_client is None:
        try:
            import sys
            sys.path.insert(0, BASE_DIR)
            from exchange.binance_client import BinanceClient
            _binance_client = BinanceClient()
        except Exception:
            pass
    return _binance_client

def get_log_file():
    pattern = os.path.join(BASE_DIR, "logs", "cryptobot_*.log")
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None

def parse_logs():
    path = get_log_file()
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            lines = f.readlines()
        return [l.rstrip() for l in lines if l.strip()]
    except:
        return []

def extract_state(logs):
    state = {
        "bot_running":   False,
        "balance":       None,
        "total_pnl":     0.0,
        "total_trades":  0,
        "win_count":     0,
        "loss_count":    0,
        "win_rate":      0,
        "strategy":      None,
        "symbol":        "BTCUSDT",
        "timeframe":     "1h",
        "current_price": None,
        "position":      None,
        "logs":          [],
    }

    if not logs:
        return state

    # Tampilkan 40 log terakhir di dashboard
    state["logs"] = logs[-40:]

    for line in logs:
        # --- Balance ---
        # Format: 💰 Balance: $5,000.00 USDT
        m = re.search(r"Balance: \$([\d,]+\.?\d*) USDT", line)
        if m:
            state["balance"] = float(m.group(1).replace(",", ""))

        # --- Config ---
        # Format: Config: BTCUSDT | 1h | support_bounce | Leverage 5x | Mode: TESTNET
        m = re.search(r"Config: (\w+) \| (\w+) \| (\w+)", line)
        if m:
            state["symbol"]    = m.group(1)
            state["timeframe"] = m.group(2)
            state["strategy"]  = m.group(3)

        # --- Harga sekarang ---
        # Format: Close: $71,255.80
        m = re.search(r"Close: \$([\d,]+\.?\d*)", line)
        if m:
            state["current_price"] = float(m.group(1).replace(",", ""))

        # --- Track side dari baris "Membuka posisi" ---
        if "Membuka posisi LONG" in line:
            state["_last_side"] = "LONG"
        elif "Membuka posisi SHORT" in line:
            state["_last_side"] = "SHORT"

        # --- Entry posisi ---
        if "Entry:" in line and "SL:" in line and "TP:" in line:
            side  = state.get("_last_side", "LONG")
            entry = sl = tp = None
            m = re.search(r"Entry: \$([\d,]+\.?\d*)", line)
            if m: entry = float(m.group(1).replace(",", ""))
            m = re.search(r"SL: \$([\d,]+\.?\d*)", line)
            if m: sl = float(m.group(1).replace(",", ""))
            m = re.search(r"TP: \$([\d,]+\.?\d*)", line)
            if m: tp = float(m.group(1).replace(",", ""))
            if entry:
                state["position"] = {
                    "side": side, "entry": entry,
                    "sl": sl, "tp": tp,
                    "symbol": state["symbol"]
                }

        # --- Posisi ditutup ---
        if any(x in line for x in ["TAKE_PROFIT", "STOP_LOSS", "POSISI DITUTUP", "Posisi ditutup", "🔒 POSISI"]):
            state["position"] = None

        # --- Trade ditutup ---
        m = re.search(r"POSISI DITUTUP \| (\w+)", line)
        if m:
            state["total_trades"] += 1
            if m.group(1) == "TAKE_PROFIT":
                state["win_count"] += 1
            else:
                state["loss_count"] += 1

        # PnL hanya dari baris penutupan posisi
        if "POSISI DITUTUP" in line:
            m = re.search(r"PnL: \$([+-]?[\d,.]+)", line)
            if m:
                state["total_pnl"] += float(m.group(1).replace(",",""))

        # --- PnL & Trade stats ---
        m = re.search(r"Total Trade\s*:\s*(\d+)", line)
        if m: state["total_trades"] = int(m.group(1))

        m = re.search(r"Win Rate\s*:\s*([\d.]+)%", line)
        if m: state["win_rate"] = float(m.group(1))

        m = re.search(r"Total PnL\s*:\s*\$([+-]?[\d,]+\.?\d*)", line)
        if m: state["total_pnl"] = float(m.group(1).replace(",", ""))

        m = re.search(r"Win / Loss\s*:\s*(\d+) / (\d+)", line)
        if m:
            state["win_count"]  = int(m.group(1))
            state["loss_count"] = int(m.group(2))

    # Cek bot running — log terbaru dalam 3 menit?
    if logs:
        last = logs[-1]
        m = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", last)
        if m:
            try:
                log_time = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                diff = (datetime.now() - log_time).total_seconds()
                state["bot_running"] = diff < 180
            except:
                state["bot_running"] = True
        else:
            state["bot_running"] = True

    return state


HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CryptoBot Monitor</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:#090c10; --surface:#0d1117; --card:#111820; --border:#1e2d3d;
    --accent:#00ff88; --red:#ff4466; --yellow:#ffd060; --dim:#4a6070; --text:#c9d8e8;
  }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:var(--bg); color:var(--text); font-family:'Syne',sans-serif; min-height:100vh; padding-bottom:60px; }
  header { display:flex; align-items:center; justify-content:space-between; padding:20px 24px; border-bottom:1px solid var(--border); position:sticky; top:0; background:var(--bg); z-index:10; }
  .logo { font-size:18px; font-weight:800; letter-spacing:2px; color:var(--accent); text-transform:uppercase; }
  .logo span { color:var(--text); }
  .pill { display:flex; align-items:center; gap:8px; font-family:'Space Mono',monospace; font-size:12px; padding:6px 14px; border-radius:20px; background:var(--card); border:1px solid var(--border); }
  .dot { width:8px; height:8px; border-radius:50%; background:var(--dim); }
  .dot.on { background:var(--accent); animation:pulse 2s infinite; }
  .dot.off { background:var(--red); }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }
  .grid { display:grid; grid-template-columns:repeat(2,1fr); gap:12px; padding:16px; }
  .card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:18px; position:relative; overflow:hidden; }
  .card::before { content:''; position:absolute; top:0; left:0; right:0; height:2px; background:var(--border); }
  .card.a::before { background:var(--accent); }
  .card.r::before { background:var(--red); }
  .card.y::before { background:var(--yellow); }
  .lbl { font-size:10px; letter-spacing:2px; text-transform:uppercase; color:var(--dim); margin-bottom:10px; font-family:'Space Mono',monospace; }
  .val { font-size:24px; font-weight:800; color:#fff; line-height:1; }
  .val.g { color:var(--accent); }
  .val.r { color:var(--red); }
  .val.y { color:var(--yellow); }
  .sub { font-size:11px; color:var(--dim); margin-top:6px; font-family:'Space Mono',monospace; }
  .sec { margin:0 16px 16px; }
  .sec-title { font-size:10px; letter-spacing:3px; text-transform:uppercase; color:var(--dim); margin-bottom:10px; font-family:'Space Mono',monospace; display:flex; align-items:center; gap:10px; }
  .sec-title::after { content:''; flex:1; height:1px; background:var(--border); }
  .pos-card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:18px; }
  .pos-hdr { display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; }
  .side { font-size:12px; font-weight:800; letter-spacing:2px; padding:4px 12px; border-radius:6px; }
  .side.LONG  { background:rgba(0,255,136,.15); color:var(--accent); }
  .side.SHORT { background:rgba(255,68,102,.15); color:var(--red); }
  .side.NONE  { background:var(--border); color:var(--dim); }
  .pos-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  .pi-lbl { font-size:9px; letter-spacing:2px; color:var(--dim); text-transform:uppercase; font-family:'Space Mono',monospace; margin-bottom:3px; }
  .pi-val { font-size:14px; font-weight:700; color:#fff; font-family:'Space Mono',monospace; }
  .bar-wrap { margin:14px 0 4px; }
  .bar-lbls { display:flex; justify-content:space-between; font-size:9px; color:var(--dim); font-family:'Space Mono',monospace; margin-bottom:5px; }
  .bar-bg { height:6px; background:var(--border); border-radius:3px; overflow:hidden; }
  .bar-fill { height:100%; border-radius:3px; background:linear-gradient(90deg,var(--red),var(--accent)); transition:width 1s; }
  .log-box { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:14px; font-family:'Space Mono',monospace; font-size:10px; line-height:1.8; max-height:280px; overflow-y:auto; }
  .ll { }
  .ll.e { color:var(--red); }
  .ll.w { color:var(--yellow); }
  .ll.s { color:var(--accent); }
  .ll.d { color:var(--dim); }
  .foot { text-align:center; font-size:10px; color:var(--dim); font-family:'Space Mono',monospace; margin-top:16px; }
  .rbar { position:fixed; bottom:0; left:0; right:0; height:3px; background:var(--border); }
  .rbar-fill { height:100%; background:var(--accent); animation:rf 10s linear infinite; }
  @keyframes rf { from{width:100%} to{width:0%} }
</style>
</head>
<body>
<header>
  <div class="logo">Crypto<span>Bot</span></div>
  <div class="pill"><div class="dot" id="dot"></div><span id="stxt">...</span></div>
</header>

<div class="grid">
  <div class="card a">
    <div class="lbl">Balance</div>
    <div class="val" id="bal">—</div>
    <div class="sub">USDT Testnet</div>
  </div>
  <div class="card">
    <div class="lbl">PnL Hari Ini</div>
    <div class="val" id="pnl">+$0.00</div>
    <div class="sub" id="pnlsub">Total</div>
  </div>
  <div class="card">
    <div class="lbl">Total Trade</div>
    <div class="val" id="trades">0</div>
    <div class="sub" id="wrsub">Belum ada trade</div>
  </div>
  <div class="card y">
    <div class="lbl">Strategi</div>
    <div class="val y" id="strat" style="font-size:14px">—</div>
    <div class="sub" id="symsub">—</div>
  </div>
  <div class="card">
    <div class="lbl">Unrealized PnL</div>
    <div class="val" id="upnl">—</div>
    <div class="sub" id="liqprice">Liq: —</div>
  </div>
</div>

<div class="sec">
  <div class="sec-title">Posisi Aktif</div>
  <div class="pos-card">
    <div class="pos-hdr">
      <span class="side NONE" id="pside">TIDAK ADA</span>
      <span style="font-size:11px;color:var(--dim);font-family:'Space Mono',monospace" id="psym">—</span>
    </div>
    <div class="pos-grid">
      <div><div class="pi-lbl">Entry</div><div class="pi-val" id="pentry">—</div></div>
      <div><div class="pi-lbl">Harga Sekarang</div><div class="pi-val" id="pprice">—</div></div>
      <div><div class="pi-lbl">Stop Loss</div><div class="pi-val" style="color:var(--red)" id="psl">—</div></div>
      <div><div class="pi-lbl">Take Profit</div><div class="pi-val" style="color:var(--accent)" id="ptp">—</div></div>
    </div>
    <div class="bar-wrap" id="barwrap" style="display:none">
      <div class="bar-lbls"><span id="bsl">SL</span><span style="color:var(--yellow)">▲ PRICE</span><span id="btp">TP</span></div>
      <div class="bar-bg"><div class="bar-fill" id="bfill" style="width:50%"></div></div>
    </div>
  </div>
</div>

<div class="sec">
  <div class="sec-title">Log Terbaru</div>
  <div class="log-box" id="logbox">Memuat...</div>
</div>

<div class="foot">Auto-refresh 10s · <span id="upd">—</span></div>
<div class="rbar"><div class="rbar-fill"></div></div>

<script>
const fmt = (n, d=2) => n != null ? '$' + Number(n).toLocaleString('en',{minimumFractionDigits:d,maximumFractionDigits:d}) : '—';

async function refresh() {
  try {
    const d = await (await fetch('/api/status')).json();

    // Status
    document.getElementById('dot').className = 'dot ' + (d.bot_running ? 'on' : 'off');
    document.getElementById('stxt').textContent = d.bot_running ? 'RUNNING' : 'STOPPED';

    // Balance
    document.getElementById('bal').textContent = d.balance != null ? fmt(d.balance) : '—';

    // PnL
    const pnl = d.total_pnl || 0;
    const pe = document.getElementById('pnl');
    pe.textContent = (pnl >= 0 ? '+' : '') + fmt(Math.abs(pnl));
    pe.className = 'val ' + (pnl > 0 ? 'g' : pnl < 0 ? 'r' : '');

    // Trades
    document.getElementById('trades').textContent = d.total_trades || 0;
    document.getElementById('wrsub').textContent = d.total_trades
      ? d.win_count + 'W ' + d.loss_count + 'L · ' + d.win_rate + '%'
      : 'Belum ada trade';

    // Strategi
    // Unrealized PnL
    const upnl = d.unrealized_pnl || 0;
    const ue = document.getElementById('upnl');
    ue.textContent = (upnl >= 0 ? '+' : '') + '$' + Math.abs(upnl).toFixed(4);
    ue.className = 'val ' + (upnl > 0 ? 'g' : upnl < 0 ? 'r' : '');
    document.getElementById('liqprice').textContent =
      d.liquidation_price ? 'Liq: $' + d.liquidation_price : 'Liq: —';

    document.getElementById('strat').textContent = d.strategy
      ? d.strategy.replace(/_/g,' ').toUpperCase() : '—';
    document.getElementById('symsub').textContent = (d.symbol||'—') + ' · ' + (d.timeframe||'—');

    // Posisi
    const p = d.position;
    if (p && p.side) {
      const se = document.getElementById('pside');
      se.textContent = p.side;
      se.className = 'side ' + p.side;
      document.getElementById('psym').textContent = p.symbol || d.symbol;
      document.getElementById('pentry').textContent = fmt(p.entry);
      document.getElementById('pprice').textContent = fmt(d.current_price);
      document.getElementById('psl').textContent = fmt(p.sl);
      document.getElementById('ptp').textContent = fmt(p.tp);
      if (p.sl && p.tp && d.current_price) {
        const pct = p.side === 'LONG'
          ? (d.current_price - p.sl) / (p.tp - p.sl) * 100
          : (p.sl - d.current_price) / (p.sl - p.tp) * 100;
        document.getElementById('bfill').style.width = Math.min(Math.max(pct,0),100) + '%';
        document.getElementById('bsl').textContent = 'SL ' + fmt(p.sl,0);
        document.getElementById('btp').textContent = 'TP ' + fmt(p.tp,0);
        document.getElementById('barwrap').style.display = 'block';
      }
    } else {
      document.getElementById('pside').textContent = 'TIDAK ADA';
      document.getElementById('pside').className = 'side NONE';
      ['pentry','pprice','psl','ptp'].forEach(id => document.getElementById(id).textContent = '—');
      document.getElementById('barwrap').style.display = 'none';
    }

    // Log
    if (d.logs && d.logs.length) {
      const lb = document.getElementById('logbox');
      lb.innerHTML = d.logs.map(l => {
        let c = '';
        if (l.includes('ERROR') || l.includes('❌') || l.includes('STOP_LOSS')) c = 'e';
        else if (l.includes('WARNING') || l.includes('⛔') || l.includes('⚠')) c = 'w';
        else if (l.includes('✅') || l.includes('TAKE_PROFIT') || l.includes('💰')) c = 's';
        else if (l.includes('DEBUG') || l.includes('WAIT') || l.includes('⏳')) c = 'd';
        return '<div class="ll ' + c + '">' + l.replace(/</g,'&lt;') + '</div>';
      }).join('');
      lb.scrollTop = lb.scrollHeight;
    }

    document.getElementById('upd').textContent = new Date().toLocaleTimeString('id-ID');
  } catch(e) {
    document.getElementById('dot').className = 'dot off';
    document.getElementById('stxt').textContent = 'ERROR';
  }
}

refresh();
setInterval(refresh, 10000);
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/api/status")
def api_status():
    logs  = parse_logs()
    state = extract_state(logs)

    # Override balance dengan data real-time dari Binance
    try:
        import sys
        sys.path.insert(0, BASE_DIR)
        from exchange.binance_client import BinanceClient
        client = BinanceClient()
        bal = client.get_account_balance()
        if bal and bal > 0:
            state["balance"] = bal
            # Hitung PnL dari selisih balance vs 5000 awal
            initial = 5000.0
            state["total_pnl"] = round(bal - 5000.0, 2)
    except Exception as e:
        pass  # Gunakan balance dari log jika gagal

    return jsonify(state)

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"""
╔══════════════════════════════════════╗
║       CryptoBot Dashboard            ║
╚══════════════════════════════════════╝
  Buka di browser : http://0.0.0.0:{port}
  Dari luar VPS   : http://IP_VPS:{port}
  Log dibaca dari : {get_log_file() or 'belum ada log'}
""")
    app.run(host="0.0.0.0", port=port, debug=False)

