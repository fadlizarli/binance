"""
dashboard.py — Web Dashboard untuk CryptoBot
Akses dari browser: http://IP_VPS:5000

Jalankan:
  pip install flask --break-system-packages
  python dashboard.py

Atau jalankan bersamaan dengan bot:
  python dashboard.py &
  python main.py --strategy support_bounce
"""
import os
import re
import json
import glob
from datetime import datetime
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

import glob
BASE_DIR = "/home/pixel/binance"
LOG_FILE = sorted(glob.glob(BASE_DIR + "/logs/cryptobot_*.log"))[-1] if glob.glob(BASE_DIR + "/logs/cryptobot_*.log") else BASE_DIR + "/logs/bot.log"
TRADE_FILE = "data/trades.json"   # opsional, jika bot menyimpan trade

# ─────────────────────────────────────────
# HTML TEMPLATE
# ─────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CryptoBot Monitor</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:      #090c10;
    --surface: #0d1117;
    --card:    #111820;
    --border:  #1e2d3d;
    --accent:  #00ff88;
    --red:     #ff4466;
    --yellow:  #ffd060;
    --dim:     #4a6070;
    --text:    #c9d8e8;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Syne', sans-serif;
    min-height: 100vh;
    padding: 0 0 60px;
  }

  /* Header */
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 20px 28px 18px;
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    background: var(--bg);
    z-index: 10;
  }
  .logo {
    font-size: 18px;
    font-weight: 800;
    letter-spacing: 2px;
    color: var(--accent);
    text-transform: uppercase;
  }
  .logo span { color: var(--text); }
  .status-pill {
    display: flex;
    align-items: center;
    gap: 8px;
    font-family: 'Space Mono', monospace;
    font-size: 12px;
    padding: 6px 14px;
    border-radius: 20px;
    background: var(--card);
    border: 1px solid var(--border);
  }
  .dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--dim);
    animation: pulse 2s infinite;
  }
  .dot.online { background: var(--accent); }
  .dot.offline { background: var(--red); animation: none; }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }

  /* Grid layout */
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px;
    padding: 20px 20px 0;
  }

  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 20px;
    position: relative;
    overflow: hidden;
  }
  .card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: var(--border);
  }
  .card.accent::before { background: var(--accent); }
  .card.red::before    { background: var(--red); }
  .card.yellow::before { background: var(--yellow); }

  .card-label {
    font-size: 10px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--dim);
    margin-bottom: 10px;
    font-family: 'Space Mono', monospace;
  }
  .card-value {
    font-size: 26px;
    font-weight: 800;
    line-height: 1;
    color: #fff;
  }
  .card-value.green  { color: var(--accent); }
  .card-value.red    { color: var(--red); }
  .card-value.yellow { color: var(--yellow); }
  .card-sub {
    font-size: 11px;
    color: var(--dim);
    margin-top: 6px;
    font-family: 'Space Mono', monospace;
  }

  /* Section */
  .section {
    margin: 20px 20px 0;
  }
  .section-title {
    font-size: 11px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: var(--dim);
    margin-bottom: 12px;
    font-family: 'Space Mono', monospace;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .section-title::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
  }

  /* Position card */
  .position-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 20px;
  }
  .pos-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 14px;
  }
  .pos-side {
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 2px;
    padding: 4px 12px;
    border-radius: 6px;
  }
  .pos-side.long  { background: rgba(0,255,136,0.15); color: var(--accent); }
  .pos-side.short { background: rgba(255,68,102,0.15); color: var(--red); }
  .pos-side.none  { background: var(--border); color: var(--dim); }
  .pos-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  .pos-item { }
  .pos-item-label {
    font-size: 9px;
    letter-spacing: 2px;
    color: var(--dim);
    text-transform: uppercase;
    font-family: 'Space Mono', monospace;
    margin-bottom: 3px;
  }
  .pos-item-value {
    font-size: 15px;
    font-weight: 700;
    color: #fff;
    font-family: 'Space Mono', monospace;
  }

  /* Progress bar SL→Price→TP */
  .price-bar-wrap {
    margin: 16px 0 6px;
  }
  .price-bar-labels {
    display: flex;
    justify-content: space-between;
    font-size: 9px;
    color: var(--dim);
    font-family: 'Space Mono', monospace;
    margin-bottom: 5px;
  }
  .price-bar-bg {
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    overflow: hidden;
    position: relative;
  }
  .price-bar-fill {
    height: 100%;
    border-radius: 3px;
    background: linear-gradient(90deg, var(--red), var(--accent));
    transition: width 1s ease;
  }

  /* Log */
  .log-box {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    font-family: 'Space Mono', monospace;
    font-size: 11px;
    line-height: 1.7;
    max-height: 300px;
    overflow-y: auto;
  }
  .log-line { padding: 1px 0; }
  .log-line.info    { color: var(--text); }
  .log-line.warn    { color: var(--yellow); }
  .log-line.error   { color: var(--red); }
  .log-line.success { color: var(--accent); }
  .log-line.wait    { color: var(--dim); }

  /* Refresh indicator */
  .refresh-bar {
    position: fixed;
    bottom: 0; left: 0; right: 0;
    height: 3px;
    background: var(--border);
    z-index: 100;
  }
  .refresh-bar-fill {
    height: 100%;
    background: var(--accent);
    animation: refill 10s linear infinite;
  }
  @keyframes refill {
    from { width: 100%; }
    to   { width: 0%; }
  }

  .last-update {
    text-align: center;
    font-size: 10px;
    color: var(--dim);
    font-family: 'Space Mono', monospace;
    margin-top: 20px;
  }

  /* Mobile tweak */
  @media (max-width: 480px) {
    header { padding: 14px 16px; }
    .grid, .section { padding-left: 12px; padding-right: 12px; }
    .card-value { font-size: 22px; }
  }
</style>
</head>
<body>

<header>
  <div class="logo">Crypto<span>Bot</span></div>
  <div class="status-pill">
    <div class="dot" id="statusDot"></div>
    <span id="statusText">Memuat...</span>
  </div>
</header>

<!-- Stats Grid -->
<div class="grid" id="statsGrid">
  <div class="card accent">
    <div class="card-label">Balance</div>
    <div class="card-value" id="balance">—</div>
    <div class="card-sub" id="balanceSub">USDT</div>
  </div>
  <div class="card">
    <div class="card-label">PnL Hari Ini</div>
    <div class="card-value" id="pnl">—</div>
    <div class="card-sub" id="pnlSub">Total</div>
  </div>
  <div class="card">
    <div class="card-label">Total Trade</div>
    <div class="card-value" id="totalTrades">—</div>
    <div class="card-sub" id="winRate">Win Rate</div>
  </div>
  <div class="card">
    <div class="card-label">Strategi</div>
    <div class="card-value yellow" id="strategy" style="font-size:16px">—</div>
    <div class="card-sub" id="symbol">—</div>
  </div>
</div>

<!-- Posisi Aktif -->
<div class="section">
  <div class="section-title">Posisi Aktif</div>
  <div class="position-card">
    <div class="pos-header">
      <span class="pos-side none" id="posSide">TIDAK ADA</span>
      <span style="font-size:12px;color:var(--dim);font-family:'Space Mono',monospace" id="posSymbol">—</span>
    </div>
    <div class="pos-grid" id="posGrid">
      <div class="pos-item">
        <div class="pos-item-label">Entry</div>
        <div class="pos-item-value" id="posEntry">—</div>
      </div>
      <div class="pos-item">
        <div class="pos-item-label">Harga Sekarang</div>
        <div class="pos-item-value" id="posPrice">—</div>
      </div>
      <div class="pos-item">
        <div class="pos-item-label">Stop Loss</div>
        <div class="pos-item-value" style="color:var(--red)" id="posSL">—</div>
      </div>
      <div class="pos-item">
        <div class="pos-item-label">Take Profit</div>
        <div class="pos-item-value" style="color:var(--accent)" id="posTP">—</div>
      </div>
    </div>
    <div class="price-bar-wrap" id="barWrap" style="display:none">
      <div class="price-bar-labels">
        <span id="barSL">SL</span>
        <span style="color:var(--yellow)">▲ PRICE</span>
        <span id="barTP">TP</span>
      </div>
      <div class="price-bar-bg">
        <div class="price-bar-fill" id="barFill" style="width:50%"></div>
      </div>
    </div>
  </div>
</div>

<!-- Log -->
<div class="section">
  <div class="section-title">Log Terbaru</div>
  <div class="log-box" id="logBox">Memuat log...</div>
</div>

<div class="last-update">Auto-refresh tiap 10 detik · <span id="lastUpdate">—</span></div>
<div class="refresh-bar"><div class="refresh-bar-fill"></div></div>

<script>
async function fetchData() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();

    // Status dot
    const dot  = document.getElementById('statusDot');
    const stxt = document.getElementById('statusText');
    if (d.bot_running) {
      dot.className = 'dot online';
      stxt.textContent = 'RUNNING';
    } else {
      dot.className = 'dot offline';
      stxt.textContent = 'STOPPED';
    }

    // Stats
    document.getElementById('balance').textContent =
      d.balance ? '$' + Number(d.balance).toLocaleString('en', {minimumFractionDigits:2, maximumFractionDigits:2}) : '—';

    const pnl = d.total_pnl || 0;
    const pnlEl = document.getElementById('pnl');
    pnlEl.textContent = (pnl >= 0 ? '+' : '') + '$' + Math.abs(pnl).toFixed(2);
    pnlEl.className = 'card-value ' + (pnl > 0 ? 'green' : pnl < 0 ? 'red' : '');

    document.getElementById('totalTrades').textContent = d.total_trades || '0';
    document.getElementById('winRate').textContent =
      d.total_trades ? `${d.win_count||0}W ${d.loss_count||0}L · ${d.win_rate||0}%` : 'Belum ada trade';

    document.getElementById('strategy').textContent = (d.strategy || '—').replace('_', ' ').toUpperCase();
    document.getElementById('symbol').textContent = (d.symbol || '—') + ' · ' + (d.timeframe || '—');

    // Posisi aktif
    const pos = d.position;
    if (pos && pos.side) {
      const sideEl = document.getElementById('posSide');
      sideEl.textContent = pos.side;
      sideEl.className = 'pos-side ' + pos.side.toLowerCase();
      document.getElementById('posSymbol').textContent = pos.symbol || d.symbol;
      document.getElementById('posEntry').textContent = pos.entry ? '$' + Number(pos.entry).toLocaleString('en', {minimumFractionDigits:2}) : '—';
      document.getElementById('posPrice').textContent = d.current_price ? '$' + Number(d.current_price).toLocaleString('en', {minimumFractionDigits:2}) : '—';
      document.getElementById('posSL').textContent = pos.sl ? '$' + Number(pos.sl).toLocaleString('en', {minimumFractionDigits:2}) : '—';
      document.getElementById('posTP').textContent = pos.tp ? '$' + Number(pos.tp).toLocaleString('en', {minimumFractionDigits:2}) : '—';

      // Progress bar
      if (pos.entry && pos.sl && pos.tp && d.current_price) {
        const sl = Number(pos.sl), tp = Number(pos.tp);
        const entry = Number(pos.entry), price = Number(d.current_price);
        const total = Math.abs(tp - sl);
        const progress = pos.side === 'LONG'
          ? (price - sl) / total * 100
          : (sl - price) / total * 100;
        document.getElementById('barFill').style.width = Math.min(Math.max(progress, 0), 100) + '%';
        document.getElementById('barSL').textContent = 'SL $' + sl.toFixed(0);
        document.getElementById('barTP').textContent = 'TP $' + tp.toFixed(0);
        document.getElementById('barWrap').style.display = 'block';
      }
    } else {
      document.getElementById('posSide').textContent = 'TIDAK ADA';
      document.getElementById('posSide').className = 'pos-side none';
      document.getElementById('posEntry').textContent = '—';
      document.getElementById('posPrice').textContent = '—';
      document.getElementById('posSL').textContent = '—';
      document.getElementById('posTP').textContent = '—';
      document.getElementById('barWrap').style.display = 'none';
    }

    // Log
    const logBox = document.getElementById('logBox');
    if (d.logs && d.logs.length) {
      logBox.innerHTML = d.logs.map(line => {
        let cls = 'info';
        if (line.includes('ERROR') || line.includes('❌') || line.includes('STOP_LOSS')) cls = 'error';
        else if (line.includes('WARNING') || line.includes('⛔') || line.includes('⚠️')) cls = 'warn';
        else if (line.includes('✅') || line.includes('TAKE_PROFIT') || line.includes('💰')) cls = 'success';
        else if (line.includes('WAIT') || line.includes('⏳')) cls = 'wait';
        return `<div class="log-line ${cls}">${line}</div>`;
      }).join('');
      logBox.scrollTop = logBox.scrollHeight;
    }

    document.getElementById('lastUpdate').textContent =
      'Update: ' + new Date().toLocaleTimeString('id-ID');

  } catch(e) {
    document.getElementById('statusDot').className = 'dot offline';
    document.getElementById('statusText').textContent = 'ERROR';
    document.getElementById('logBox').innerHTML = '<div class="log-line error">Gagal fetch data: ' + e.message + '</div>';
  }
}

fetchData();
setInterval(fetchData, 10000);
</script>
</body>
</html>"""


# ─────────────────────────────────────────
# STATE (dibaca dari log dan shared state)
# ─────────────────────────────────────────

bot_state = {
    "bot_running":   False,
    "balance":       0,
    "total_pnl":     0,
    "total_trades":  0,
    "win_count":     0,
    "loss_count":    0,
    "win_rate":      0,
    "strategy":      "—",
    "symbol":        "BTCUSDT",
    "timeframe":     "1h",
    "current_price": 0,
    "position":      None,
    "logs":          [],
}


def parse_logs():
    """Baca dan parse file log terbaru."""
    if not os.path.exists(LOG_FILE):
        return []

    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
        # Ambil 80 baris terakhir
        return [l.rstrip() for l in lines[-80:] if l.strip()]
    except Exception:
        return []


def extract_state_from_logs(logs):
    """Ekstrak state bot dari baris-baris log."""
    state = bot_state.copy()
    state["logs"] = logs[-40:]  # tampilkan 40 baris terakhir

    for line in logs:
        # Balance
        m = re.search(r"💰 Balance: \$([\d,]+\.?\d*)", line)
        if m and state["balance"] == 0:
            state["balance"] = float(m.group(1).replace(",",""))
        # Config
        if "Config:" in line and "|" in line:
            try:
                parts = line.split("Config:")[1].strip().split("|")
                state["symbol"]    = parts[0].strip()
                state["timeframe"] = parts[1].strip()
                state["strategy"]  = parts[2].strip()
            except: pass

    for line in reversed(logs):
        # Balance
        if ("Balance:" in line or "Balance" in line) and "$" in line:
            try:
                m = re.search(r"Balance: \\$([\d,]+\.?\d*)", line)
                if m:
                    state["balance"] = float(m.group(1).replace(",", ""))
            except: pass

        # Strategy & symbol dari Config line
        if "Config:" in line:
            try:
                parts = line.split("Config:")[1].strip().split("|")
                if len(parts) >= 3:
                    state["symbol"]    = parts[0].strip()
                    state["timeframe"] = parts[1].strip()
                    state["strategy"]  = parts[2].strip()
            except: pass

        # Harga sekarang
        if "Close:" in line and "$" in line:
            try:
                price = line.split("Close: $")[1].split()[0].replace(",", "")
                state["current_price"] = float(price)
            except: pass

        # Entry posisi
        if "Membuka posisi" in line or "ENTRY" in line:
            try:
                side = "LONG" if "LONG" in line else "SHORT"
                entry = sl = tp = None
                if "Entry:" in line:
                    entry = float(line.split("Entry: $")[1].split()[0].replace(",","").rstrip("|"))
                if "SL:" in line:
                    sl = float(line.split("SL: $")[1].split()[0].replace(",","").rstrip("|"))
                if "TP:" in line:
                    tp = float(line.split("TP: $")[1].split()[0].replace(",","").rstrip("|"))
                state["position"] = {"side": side, "entry": entry, "sl": sl, "tp": tp, "symbol": state["symbol"]}
            except: pass

        # Posisi ditutup
        if "TAKE_PROFIT" in line or "STOP_LOSS" in line or "Posisi ditutup" in line:
            state["position"] = None

        # Trade stats
        if "Total Trade" in line:
            try:
                state["total_trades"] = int(line.split(":")[1].strip())
            except: pass
        if "Win Rate" in line and "%" in line:
            try:
                state["win_rate"] = float(line.split(":")[1].strip().replace("%",""))
            except: pass
        if "Total PnL" in line and "$" in line:
            try:
                pnl_str = line.split("$")[1].split()[0].replace(",","")
                state["total_pnl"] = float(pnl_str)
            except: pass

    # Bot dianggap running jika ada log dalam 3 menit terakhir
    if logs:
        try:
            last_line = logs[-1]
            time_str = last_line[:8]
            now = datetime.now()
            log_time = datetime.strptime(time_str, "%H:%M:%S").replace(
                year=now.year, month=now.month, day=now.day)
            diff = (now - log_time).total_seconds()
            state["bot_running"] = diff < 180
        except:
            state["bot_running"] = True

    state.pop("_found", None)
    return state


# ─────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/status")
def api_status():
    logs  = parse_logs()
    state = extract_state_from_logs(logs)
    return jsonify(state)


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"""
╔══════════════════════════════════════╗
║       CryptoBot Dashboard            ║
╚══════════════════════════════════════╝
  Buka di browser: http://0.0.0.0:{port}
  Dari luar VPS  : http://IP_VPS:{port}
  Stop           : Ctrl+C
""")
    app.run(host="0.0.0.0", port=port, debug=False)
y

