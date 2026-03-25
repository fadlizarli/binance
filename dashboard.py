"""
dashboard.py — CryptoBot Web Dashboard
"""
import os
import re
import sys
import glob
from datetime import datetime
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

_client = None
def get_client():
    global _client
    if _client is None:
        try:
            from exchange.binance_client import BinanceClient
            _client = BinanceClient()
        except Exception:
            pass
    return _client

def get_log_file():
    files = sorted(glob.glob(os.path.join(BASE_DIR, "logs", "cryptobot_*.log")))
    return files[-1] if files else None

def parse_logs(today_only=False):
    pattern = os.path.join(BASE_DIR, "logs", "cryptobot_*.log")
    files = sorted(glob.glob(pattern))
    if not files:
        return []
    try:
        if today_only:
            files = [files[-1]]
        all_lines = []
        for path in files:
            with open(path, "r") as f:
                all_lines.extend(f.readlines())
        return [l.rstrip() for l in all_lines if l.strip()]
    except:
        return []

def parse_trades():
    import re as re2
    trades = []
    pattern = os.path.join(BASE_DIR, "logs", "cryptobot_*.log")
    files   = sorted(glob.glob(pattern))
    for path in files:
        try:
            with open(path, "r") as f:
                lines = f.readlines()
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if "POSISI DITUTUP" in line:
                    date   = line[:19]
                    reason = "TAKE_PROFIT" if "TAKE_PROFIT" in line else "STOP_LOSS"
                    if i + 1 < len(lines):
                        detail  = lines[i+1].strip()
                        side    = "LONG" if "LONG" in detail else "SHORT"
                        sym_m   = re2.search(r"(SOLUSDT|BTCUSDT|ETHUSDT|DOGEUSDT)", detail)
                        symbol  = sym_m.group(1) if sym_m else "SOLUSDT"
                        entry_m = re2.search(r"Entry: \$([\d.]+)", detail)
                        exit_m  = re2.search(r"Exit: \$([\d.]+)", detail)
                        pnl_m   = re2.search(r"PnL: \$([+-]?[\d.]+)", detail)
                        if entry_m and exit_m:
                            raw = float(pnl_m.group(1)) if pnl_m else 0
                            pnl = round(raw / 3 if date < "2026-03-21 00:00" else raw, 2)
                            trades.append({
                                "date": date, "side": side, "symbol": symbol,
                                "entry": float(entry_m.group(1)),
                                "exit":  float(exit_m.group(1)),
                                "pnl":   pnl, "reason": reason,
                            })
                i += 1
        except:
            continue
    return list(reversed(trades))

def extract_state(logs):
    state = {
        "bot_running": False, "balance": None, "total_pnl": 0.0,
        "total_trades": 0, "win_count": 0, "loss_count": 0, "win_rate": 0,
        "strategy": None, "symbol": "SOLUSDT", "timeframe": "1h",
        "current_price": None, "position": None,
        "unrealized_pnl": 0.0, "liquidation_price": None, "logs": [],
    }
    if not logs:
        return state
    state["logs"] = logs[-40:]
    last_side = None
    for line in logs:
        m = re.search(r"Balance:\s*\$([\d,]+\.?\d*)\s*USDT", line)
        if m: state["balance"] = float(m.group(1).replace(",", ""))
        m = re.search(r"Config: (\w+) \| (\w+) \| (\w+)", line)
        if m:
            state["symbol"]   = m.group(1)
            state["timeframe"] = m.group(2)
            state["strategy"] = m.group(3)
        m = re.search(r"Close: \$([\d,]+\.?\d*)", line)
        if m: state["current_price"] = float(m.group(1).replace(",", ""))
        if "Membuka posisi LONG" in line:   last_side = "LONG"
        elif "Membuka posisi SHORT" in line: last_side = "SHORT"
        if "Entry:" in line and "SL:" in line and "TP:" in line:
            entry = sl = tp = None
            m = re.search(r"Entry: \$([\d,]+\.?\d*)", line)
            if m: entry = float(m.group(1).replace(",", ""))
            m = re.search(r"SL: \$([\d,]+\.?\d*)", line)
            if m: sl = float(m.group(1).replace(",", ""))
            m = re.search(r"TP: \$([\d,]+\.?\d*)", line)
            if m: tp = float(m.group(1).replace(",", ""))
            if entry and last_side:
                state["position"] = {"side": last_side, "entry": entry,
                                     "sl": sl, "tp": tp, "symbol": state["symbol"]}
        if any(x in line for x in ["POSISI DITUTUP", "TAKE_PROFIT", "STOP_LOSS", "🔒 POSISI"]):
            state["position"] = None
        if "POSISI DITUTUP" in line:
            state["total_trades"] += 1
            if "TAKE_PROFIT" in line: state["win_count"] += 1
            else: state["loss_count"] += 1
    if state["total_trades"] > 0:
        state["win_rate"] = round(state["win_count"] / state["total_trades"] * 100, 1)
    if logs:
        m = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", logs[-1])
        if m:
            try:
                diff = (datetime.now() - datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")).total_seconds()
                state["bot_running"] = diff < 180
            except:
                state["bot_running"] = True
    return state

def enrich_with_binance(state):
    client = get_client()
    if not client:
        return state
    try:
        for b in client.client.futures_account_balance():
            if b["asset"] == "USDT":
                wallet = float(b["balance"])
                if wallet > 0:
                    state["balance"]   = wallet
                    state["total_pnl"] = round(wallet - 5000.0, 2)
                break
    except:
        pass
    try:
        symbol = state.get("symbol", "SOLUSDT")
        positions = client.client.futures_position_information(symbol=symbol)
        has_pos = False
        for p in positions:
            amt = float(p["positionAmt"])
            if amt != 0:
                has_pos = True
                side  = "LONG" if amt > 0 else "SHORT"
                entry = float(p["entryPrice"])
                mark  = float(p["markPrice"])
                upnl  = float(p["unRealizedProfit"])
                liq   = float(p["liquidationPrice"])
                log_pos = state.get("position") or {}
                state["position"] = {"side": side, "entry": round(entry, 4), "symbol": symbol,
                                     "sl": log_pos.get("sl"), "tp": log_pos.get("tp")}
                state["current_price"]     = round(mark, 4)
                state["unrealized_pnl"]    = round(upnl, 2)
                state["liquidation_price"] = round(liq, 2)
        if not has_pos:
            state["position"]       = None
            state["unrealized_pnl"] = 0.0
    except:
        pass
    return state

HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CryptoBot Monitor</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
<style>
  :root{--bg:#090c10;--card:#111820;--border:#1e2d3d;--accent:#00ff88;--red:#ff4466;--yellow:#ffd060;--dim:#4a6070;--text:#c9d8e8;}
  *{box-sizing:border-box;margin:0;padding:0;}
  body{background:var(--bg);color:var(--text);font-family:'Syne',sans-serif;padding-bottom:60px;}
  header{display:flex;align-items:center;justify-content:space-between;padding:20px 24px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg);z-index:10;}
  .logo{font-size:18px;font-weight:800;letter-spacing:2px;color:var(--accent);}
  .logo span{color:var(--text);}
  .pill{display:flex;align-items:center;gap:8px;font-family:'Space Mono',monospace;font-size:12px;padding:6px 14px;border-radius:20px;background:var(--card);border:1px solid var(--border);}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--dim);}
  .dot.on{background:var(--accent);animation:pulse 2s infinite;}
  .dot.off{background:var(--red);}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
  .grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;padding:16px;}
  .card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px;position:relative;overflow:hidden;}
  .card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--border);}
  .card.a::before{background:var(--accent);}
  .card.y::before{background:var(--yellow);}
  .lbl{font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--dim);margin-bottom:10px;font-family:'Space Mono',monospace;}
  .val{font-size:22px;font-weight:800;color:#fff;line-height:1;}
  .val.g{color:var(--accent);}.val.r{color:var(--red);}.val.y{color:var(--yellow);}
  .sub{font-size:11px;color:var(--dim);margin-top:6px;font-family:'Space Mono',monospace;}
  .sec{margin:0 16px 16px;}
  .sec-title{font-size:10px;letter-spacing:3px;text-transform:uppercase;color:var(--dim);margin-bottom:10px;font-family:'Space Mono',monospace;display:flex;align-items:center;gap:10px;}
  .sec-title::after{content:'';flex:1;height:1px;background:var(--border);}
  .pos-card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px;}
  .pos-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;}
  .side{font-size:12px;font-weight:800;letter-spacing:2px;padding:4px 12px;border-radius:6px;}
  .side.LONG{background:rgba(0,255,136,.15);color:var(--accent);}
  .side.SHORT{background:rgba(255,68,102,.15);color:var(--red);}
  .side.NONE{background:var(--border);color:var(--dim);}
  .pos-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
  .pi-lbl{font-size:9px;letter-spacing:2px;color:var(--dim);text-transform:uppercase;font-family:'Space Mono',monospace;margin-bottom:3px;}
  .pi-val{font-size:14px;font-weight:700;color:#fff;font-family:'Space Mono',monospace;}
  .bar-wrap{margin:14px 0 4px;}
  .bar-lbls{display:flex;justify-content:space-between;font-size:9px;color:var(--dim);font-family:'Space Mono',monospace;margin-bottom:5px;}
  .bar-bg{height:6px;background:var(--border);border-radius:3px;overflow:hidden;}
  .bar-fill{height:100%;border-radius:3px;background:linear-gradient(90deg,var(--red),var(--accent));transition:width 1s;}
  .log-box{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px;font-family:'Space Mono',monospace;font-size:10px;line-height:1.8;max-height:260px;overflow-y:auto;}
  .ll.e{color:var(--red);}.ll.w{color:var(--yellow);}.ll.s{color:var(--accent);}.ll.d{color:var(--dim);}
  .foot{text-align:center;font-size:10px;color:var(--dim);font-family:'Space Mono',monospace;margin-top:16px;}
  .rbar{position:fixed;bottom:0;left:0;right:0;height:3px;background:var(--border);}
  .rbar-fill{height:100%;background:var(--accent);animation:rf 10s linear infinite;}
  @keyframes rf{from{width:100%}to{width:0}}
</style>
</head>
<body>
<header>
  <div class="logo">Crypto<span>Bot</span></div>
  <div class="pill"><div class="dot" id="dot"></div><span id="stxt">...</span></div>
</header>
<div class="grid">
  <div class="card a"><div class="lbl">Balance</div><div class="val" id="bal">—</div><div class="sub">USDT Testnet</div></div>
  <div class="card"><div class="lbl">PnL Total</div><div class="val" id="pnl">—</div><div class="sub">Dari $5,000 awal</div></div>
  <div class="card"><div class="lbl">Unrealized PnL</div><div class="val" id="upnl">+$0.00</div><div class="sub" id="liq">Liq: —</div></div>
  <div class="card y"><div class="lbl">Strategi</div><div class="val y" id="strat" style="font-size:13px">—</div><div class="sub" id="symsub">—</div></div>
  <div class="card"><div class="lbl">Trade Hari Ini</div><div class="val" id="trades_today">0</div><div class="sub" id="wrsub_today">Belum ada trade</div></div>
  <div class="card"><div class="lbl">Total Semua Trade</div><div class="val" id="trades">0</div><div class="sub" id="wrsub">Kumulatif</div></div>
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
  <div class="sec-title">Riwayat Trade</div>
  <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;overflow:hidden">
    <table style="width:100%;border-collapse:collapse;font-family:'Space Mono',monospace;font-size:10px">
      <thead>
        <tr style="border-bottom:1px solid var(--border)">
          <th style="padding:10px 12px;text-align:left;color:var(--dim)">TANGGAL</th>
          <th style="padding:10px 8px;text-align:center;color:var(--dim)">SIDE</th>
          <th style="padding:10px 8px;text-align:right;color:var(--dim)">ENTRY</th>
          <th style="padding:10px 8px;text-align:right;color:var(--dim)">EXIT</th>
          <th style="padding:10px 8px;text-align:right;color:var(--dim)">PNL</th>
          <th style="padding:10px 8px;text-align:center;color:var(--dim)">HASIL</th>
        </tr>
      </thead>
      <tbody id="tradeTable">
        <tr><td colspan="6" style="padding:16px;text-align:center;color:var(--dim)">Memuat...</td></tr>
      </tbody>
    </table>
  </div>
</div>
<div class="sec">
  <div class="sec-title">Log Terbaru</div>
  <div class="log-box" id="logbox">Memuat...</div>
</div>
<div class="foot">Auto-refresh 10s · <span id="upd">—</span></div>
<div class="rbar"><div class="rbar-fill"></div></div>
<script>
const fmt=(n,d=2)=>n!=null?'$'+Number(n).toLocaleString('en',{minimumFractionDigits:d,maximumFractionDigits:d}):'—';

async function loadTrades(){
  try{
    const d=await(await fetch('/api/trades')).json();
    const tb=document.getElementById('tradeTable');
    if(!d.trades||!d.trades.length){
      tb.innerHTML='<tr><td colspan="6" style="padding:16px;text-align:center;color:var(--dim)">Belum ada trade</td></tr>';
      return;
    }
    tb.innerHTML=d.trades.slice(0,5).map(t=>{
      const pnlVal=parseFloat(t.pnl)||0;
      const pnlColor=pnlVal>0?'var(--accent)':'var(--red)';
      const sideColor=t.side==='LONG'?'var(--accent)':'var(--red)';
      const result=t.reason==='TAKE_PROFIT'?'✅ TP':t.reason==='STOP_LOSS'&&pnlVal>0?'🔄 TS':'❌ SL';
      const date=t.date?t.date.substring(5,16):'—';
      return '<tr style="border-bottom:1px solid var(--border)">'+
        '<td style="padding:8px 12px;color:var(--dim)">'+date+'</td>'+
        '<td style="padding:8px;text-align:center;color:'+sideColor+';font-weight:700">'+t.side+'</td>'+
        '<td style="padding:8px;text-align:right;color:var(--text)">$'+parseFloat(t.entry).toFixed(2)+'</td>'+
        '<td style="padding:8px;text-align:right;color:var(--text)">$'+parseFloat(t.exit).toFixed(2)+'</td>'+
        '<td style="padding:8px;text-align:right;color:'+pnlColor+';font-weight:700">'+(pnlVal>=0?'+':'')+fmt(Math.abs(pnlVal))+'</td>'+
        '<td style="padding:8px;text-align:center;color:var(--dim)">'+result+'</td>'+
        '</tr>';
    }).join('');
  }catch(e){console.error('trades error:',e);}
}

async function refresh(){
  try{
    const d=await(await fetch('/api/status')).json();
    document.getElementById('dot').className='dot '+(d.bot_running?'on':'off');
    document.getElementById('stxt').textContent=d.bot_running?'RUNNING':'STOPPED';
    document.getElementById('bal').textContent=d.balance!=null?fmt(d.balance):'—';
    const pnl=d.total_pnl||0;
    const pe=document.getElementById('pnl');
    pe.textContent=(pnl>=0?'+':'')+fmt(Math.abs(pnl));
    pe.className='val '+(pnl>0?'g':pnl<0?'r':'');
    const upnl=d.unrealized_pnl||0;
    const ue=document.getElementById('upnl');
    ue.textContent=(upnl>=0?'+':'')+fmt(upnl);
    ue.className='val '+(upnl>0?'g':upnl<0?'r':'');
    document.getElementById('liq').textContent=d.liquidation_price?'Liq: '+fmt(d.liquidation_price):'Liq: —';
    document.getElementById('strat').textContent=d.strategy?d.strategy.replace(/_/g,' ').toUpperCase():'—';
    document.getElementById('symsub').textContent=(d.symbol||'—')+' · '+(d.timeframe||'—');
    document.getElementById('trades_today').textContent=d.trades_today||0;
    document.getElementById('wrsub_today').textContent=d.trades_today?(d.wins_today||0)+'W '+(d.losses_today||0)+'L':'Belum ada trade hari ini';
    document.getElementById('trades').textContent=d.total_trades||0;
    document.getElementById('wrsub').textContent=d.total_trades?d.win_count+'W '+d.loss_count+'L · '+d.win_rate+'%':'Belum ada trade';
    const p=d.position;
    if(p&&p.side){
      const se=document.getElementById('pside');
      se.textContent=p.side;se.className='side '+p.side;
      document.getElementById('psym').textContent=p.symbol||d.symbol;
      document.getElementById('pentry').textContent=fmt(p.entry);
      document.getElementById('pprice').textContent=fmt(d.current_price);
      document.getElementById('psl').textContent=p.sl?fmt(p.sl):'—';
      document.getElementById('ptp').textContent=p.tp?fmt(p.tp):'—';
      if(p.sl&&p.tp&&d.current_price){
        const pct=p.side==='LONG'?(d.current_price-p.sl)/(p.tp-p.sl)*100:(p.sl-d.current_price)/(p.sl-p.tp)*100;
        document.getElementById('bfill').style.width=Math.min(Math.max(pct,0),100)+'%';
        document.getElementById('bsl').textContent='SL '+fmt(p.sl,1);
        document.getElementById('btp').textContent='TP '+fmt(p.tp,1);
        document.getElementById('barwrap').style.display='block';
      }
    }else{
      document.getElementById('pside').textContent='TIDAK ADA';
      document.getElementById('pside').className='side NONE';
      ['pentry','pprice','psl','ptp'].forEach(id=>document.getElementById(id).textContent='—');
      document.getElementById('barwrap').style.display='none';
    }
    if(d.logs&&d.logs.length){
      const lb=document.getElementById('logbox');
      lb.innerHTML=d.logs.map(l=>{
        let c='';
        if(l.includes('ERROR')||l.includes('STOP_LOSS'))c='e';
        else if(l.includes('WARNING')||l.includes('⛔'))c='w';
        else if(l.includes('✅')||l.includes('TAKE_PROFIT')||l.includes('💰'))c='s';
        else if(l.includes('DEBUG')||l.includes('WAIT'))c='d';
        return '<div class="ll '+c+'">'+l.replace(/</g,'&lt;')+'</div>';
      }).join('');
      lb.scrollTop=lb.scrollHeight;
    }
    document.getElementById('upd').textContent=new Date().toLocaleTimeString('id-ID');
  }catch(e){
    document.getElementById('dot').className='dot off';
    document.getElementById('stxt').textContent='ERROR';
  }
}

refresh();
loadTrades();
setInterval(refresh,10000);
setInterval(loadTrades,30000);
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/api/status")
def api_status():
    state = extract_state(parse_logs(today_only=False))
    today = extract_state(parse_logs(today_only=True))
    state["trades_today"]  = today["total_trades"]
    state["wins_today"]    = today["win_count"]
    state["losses_today"]  = today["loss_count"]
    state = enrich_with_binance(state)
    return jsonify(state)

@app.route("/api/trades")
def api_trades():
    return jsonify({"trades": parse_trades()[:5]})

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"""
╔══════════════════════════════════════╗
║       CryptoBot Dashboard            ║
╚══════════════════════════════════════╝
  Buka : http://0.0.0.0:{port}
  VPS  : http://IP_VPS:{port}
  Log  : {get_log_file() or 'belum ada'}
""")
    app.run(host="0.0.0.0", port=port, debug=False)

