import os, re, sys, glob
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)
CLOSE_PIN = "1234"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

_client = None
def get_client():
    global _client
    if _client is None:
        try:
            from exchange.binance_client import BinanceClient
            _client = BinanceClient()
        except: pass
    return _client

def parse_logs(today_only=False):
    pattern = os.path.join(BASE_DIR, "logs", "cryptobot_*.log")
    files = sorted(glob.glob(pattern))
    if not files: return []
    lines = []
    if today_only:
        today = datetime.now().strftime("%Y-%m-%d")
        for f in files[-2:]:
            try:
                with open(f) as fp:
                    filtered = [l.rstrip() for l in fp if today in l]
                lines.extend(filtered)
            except: pass
    else:
        for f in files[-3:]:
            try:
                with open(f) as fp:
                    lines.extend(l.rstrip() for l in fp)
            except: pass
    return lines

def parse_trades():
    pattern = os.path.join(BASE_DIR, "logs", "cryptobot_*.log")
    files = sorted(glob.glob(pattern))
    trades = []
    for f in files:
        try:
            with open(f) as fp:
                lines = fp.readlines()
            for i, line in enumerate(lines):
                if "POSISI DITUTUP" in line:
                    reason = "STOP_LOSS"
                    if "TAKE_PROFIT" in line: reason = "TAKE_PROFIT"
                    elif "MANUAL" in line: reason = "MANUAL"
                    if i+1 < len(lines):
                        d = lines[i+1].strip()
                        pm = re.search(r"(LONG|SHORT) \S+ \| Entry: \$([0-9.]+) . Exit: \$([0-9.]+) \| PnL: \$([+-]?[0-9.]+)", d)
                        if pm:
                            ts = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", line)
                            trades.append({"date": ts.group(1) if ts else "", "side": pm.group(1), "entry": pm.group(2), "exit": pm.group(3), "pnl": pm.group(4), "reason": reason})
        except: pass
    return trades

def get_entry_reasons(entry_price):
    files = sorted(glob.glob(os.path.join(BASE_DIR, "logs", "cryptobot_*.log")))
    for f in reversed(files):
        try:
            with open(f) as fp:
                lines = fp.readlines()
            for i, line in enumerate(lines):
                if "Membuka posisi" in line:
                    reasons = []
                    claude_conf = None
                    htf_trend = None
                    for j in range(max(0,i-20), i):
                        l = lines[j].strip()
                        if "Sinyal:" in l:
                            m = re.search(r"Sinyal: \S+ .strength: [0-9.]+. \| (.+)", l)
                            if m:
                                parts = m.group(1).split(" | ")
                                reasons = [p for p in parts if p.strip()]
                        if "Claude" in l and "/10" in l:
                            m = re.search(r"(\d+)/10", l)
                            if m: claude_conf = m.group(1)+"/10"
                        if "HTF 4h Trend:" in l:
                            m = re.search(r"HTF 4h Trend: (\w+)", l)
                            if m: htf_trend = m.group(1)
                    return reasons, claude_conf, htf_trend
        except: pass
    return [], None, None

def get_perf(trades):
    if not trades:
        return {"total":0,"wins":0,"losses":0,"win_rate":0,"avg_win":0,"avg_loss":0,
                "rr":0,"streak":0,"streak_type":"NONE","last5":[],"long_total":0,
                "long_wr":0,"short_total":0,"short_wr":0,"equity_points":[],
                "be_progress":0,"target_avg_win":0}
    wins=[t for t in trades if float(t["pnl"])>0]
    losses=[t for t in trades if float(t["pnl"])<=0]
    aw=sum(float(t["pnl"]) for t in wins)/len(wins) if wins else 0
    al=sum(abs(float(t["pnl"])) for t in losses)/len(losses) if losses else 0
    rr=aw/al if al>0 else 0
    wr=round(len(wins)/len(trades)*100,1)
    streak=0; streak_type="NONE"
    for t in reversed(trades):
        pv=float(t["pnl"])
        if streak==0:
            streak=1; streak_type="WIN" if pv>0 else "LOSS"
        elif (pv>0 and streak_type=="WIN") or (pv<=0 and streak_type=="LOSS"):
            streak+=1
        else: break
    last5=[]
    for t in trades[-5:]:
        pv=float(t["pnl"])
        last5.append("W" if pv>0 else "L")
    longs=[t for t in trades if t["side"]=="LONG"]
    shorts=[t for t in trades if t["side"]=="SHORT"]
    lw=[t for t in longs if float(t["pnl"])>0]
    sw=[t for t in shorts if float(t["pnl"])>0]
    eq=[131.12]
    for t in trades:
        eq.append(round(eq[-1]+float(t["pnl"]),2))
    eq_pts=eq[1:]
    taw=max(al,1.30) if losses else 1.30
    bep=min(100,round(aw/taw*100,1)) if taw>0 else 0
    return {"total":len(trades),"wins":len(wins),"losses":len(losses),
        "win_rate":wr,"avg_win":round(aw,2),"avg_loss":round(al,2),
        "rr":round(rr,2),"streak":streak,"streak_type":streak_type,
        "last5":last5,"long_total":len(longs),
        "long_wr":round(len(lw)/len(longs)*100,1) if longs else 0,
        "short_total":len(shorts),
        "short_wr":round(len(sw)/len(shorts)*100,1) if shorts else 0,
        "equity_points":eq_pts,"be_progress":bep,"target_avg_win":round(taw,2)}

def extract_state(logs):
    state = {"bot_running": False, "balance": None, "position": None,
        "current_price": None, "fg_value": None, "fg_label": None,
        "htf_current": None, "liquidation_price": None, "logs": [],
        "claude_approve": 0, "claude_skip": 0,
        "last_signal": None, "last_indicators": {}}
    if not logs: return state
    state["logs"] = sorted(logs, key=lambda x: x[:23])[-40:]
    last_side = None
    entry_p = sl_p = tp_p = None
    for line in logs:
        if "BOT DIMULAI" in line or "MODE LIVE" in line: state["bot_running"] = True
        if "Balance:" in line:
            m = re.search(r"Balance: \$([0-9.]+)", line)
            if m: state["balance"] = float(m.group(1))
        if "Fear & Greed" in line and "update:" in line:
            m = re.search(r"update: (\d+) \((.+?)\)", line)
            if m: state["fg_value"] = int(m.group(1)); state["fg_label"] = m.group(2)
        if "HTF 4h Trend:" in line:
            m = re.search(r"HTF 4h Trend: (\w+)", line)
            if m: state["htf_current"] = m.group(1)
        if "Membuka posisi LONG" in line: last_side = "LONG"
        elif "Membuka posisi SHORT" in line: last_side = "SHORT"
        if "Entry:" in line and "SL:" in line and "TP:" in line and "Risk" in line:
            m = re.search(r"Entry:([0-9.]+) SL:([0-9.]+).*TP:([0-9.]+)", line)
            if m: entry_p=float(m.group(1)); sl_p=float(m.group(2)); tp_p=float(m.group(3))
        if "POSISI DITUTUP" in line: last_side=None; entry_p=sl_p=tp_p=None
        if "Full size" in line or "Medium size" in line: state["claude_approve"]+=1
        if "Reduced size" in line: state["claude_skip"]+=1
        if "Sinyal:" in line:
            m = re.search(r"Sinyal: (\w+) \(strength: ([0-9.]+)\)(.*)", line)
            if m: state["last_signal"] = {"action": m.group(1), "strength": float(m.group(2)), "reason": m.group(3).strip()}
        if "Close:" in line and "ATR:" in line:
            m = re.search(r"Close: \$([0-9.]+) \| ATR: ([0-9.]+)", line)
            if m: state["last_indicators"]["close"]=float(m.group(1)); state["last_indicators"]["atr"]=float(m.group(2))
        if "EMA  :" in line:
            m = re.search(r"EMA\s+: ([0-9.]+)/([0-9.]+)/([0-9.]+) \[(\w+)\]", line)
            if m: state["last_indicators"]["ema9"]=float(m.group(1)); state["last_indicators"]["ema21"]=float(m.group(2)); state["last_indicators"]["ema55"]=float(m.group(3)); state["last_indicators"]["ema_trend"]=m.group(4)
        if "RSI  :" in line:
            m = re.search(r"RSI\s+: ([0-9.]+)", line)
            if m: state["last_indicators"]["rsi"]=float(m.group(1))
        if "MACD :" in line:
            m = re.search(r"MACD\s+: ([+-]?[0-9.]+) hist:([+-]?[0-9.]+)", line)
            if m: state["last_indicators"]["macd"]=float(m.group(1)); state["last_indicators"]["macd_hist"]=float(m.group(2))
        if "BB   :" in line:
            m = re.search(r"BB\s+: ([0-9.]+)/([0-9.]+)/([0-9.]+) \[(\w+)\] Squeeze:(\w+)", line)
            if m: state["last_indicators"]["bb_lower"]=float(m.group(1)); state["last_indicators"]["bb_mid"]=float(m.group(2)); state["last_indicators"]["bb_upper"]=float(m.group(3)); state["last_indicators"]["bb_pos"]=m.group(4); state["last_indicators"]["squeeze"]=m.group(5)=="True"
        if "Vol  :" in line:
            m = re.search(r"Vol\s+: ([0-9.]+)x \[(\w+)\]", line)
            if m: state["last_indicators"]["vol_ratio"]=float(m.group(1)); state["last_indicators"]["vol_status"]=m.group(2)
    if last_side and entry_p:
        reasons, cc, ht = get_entry_reasons(entry_p)
        state["position"] = {"side": last_side, "entry": entry_p, "sl": sl_p, "tp": tp_p,
            "entry_reasons": reasons, "claude_conf": cc, "htf_trend": ht}
    return state

def enrich_with_binance(state):
    try:
        client = get_client()
        if not client or not client.is_connected(): return state
        from config import config
        symbol = config.trading.symbol
        price = client.get_ticker_price(symbol)
        if price: state["current_price"] = price
        balance = client.get_account_balance()
        if balance: state["balance"] = balance
        positions = client.get_open_positions(symbol)
        pos = positions[0] if positions else None
        if pos and pos.get("positionAmt") and float(pos["positionAmt"]) != 0:
            amt = float(pos["positionAmt"])
            ep = float(pos.get("entryPrice", 0))
            liq = float(pos.get("liquidationPrice", 0))
            upnl = float(pos.get("unRealizedProfit", 0))
            side = "LONG" if amt > 0 else "SHORT"
            log_pos = state.get("position") or {}
            sl_val = log_pos.get("sl")
            tp_val = log_pos.get("tp")
            trail_progress = 0; trail_active = False; trail_mult = 0
            if ep and tp_val and sl_val and price:
                total = (tp_val - ep) if side=="LONG" else (ep - tp_val)
                if total > 0:
                    curr = (price - ep) if side=="LONG" else (ep - price)
                    trail_progress = min(100, max(0, curr/total*100))
                    trail_active = trail_progress >= 50
                    if trail_progress >= 90: trail_mult = 0.5
                    elif trail_progress >= 75: trail_mult = 0.8
                    elif trail_progress >= 60: trail_mult = 1.2
                    else: trail_mult = 2.0
            state["position"] = {**(log_pos or {}), "side": side, "entry": ep,
                "symbol": symbol, "liquidation_price": liq, "unrealized_pnl": upnl,
                "sl": sl_val, "tp": tp_val, "trail_progress": round(trail_progress,1),
                "trail_active": trail_active, "trail_mult": trail_mult}
            state["unrealized_pnl"] = upnl
            state["liquidation_price"] = liq
        else:
            state["position"] = None
            state["unrealized_pnl"] = 0
    except Exception as e:
        pass
    return state

HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CryptoBot Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Syne:wght@400;600;700;800&display=swap');
:root{--bg:#070a0e;--bg2:#0d1117;--bg3:#161b22;--border:#1e2530;--green:#00e676;--red:#ff3d57;--yellow:#ffd600;--blue:#2979ff;--text:#e6edf3;--muted:#586069}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:'Syne',sans-serif;min-height:100vh;padding:14px;padding-bottom:80px}
.header{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
.logo{font-family:'JetBrains Mono',monospace;font-size:16px;font-weight:700;color:var(--green);letter-spacing:3px}
.logo span{color:var(--muted)}
.status-pill{display:flex;align-items:center;gap:6px;background:rgba(0,230,118,0.08);border:1px solid rgba(0,230,118,0.2);padding:4px 10px;border-radius:20px;font-size:11px;font-family:'JetBrains Mono',monospace;color:var(--green)}
.dot{width:6px;height:6px;border-radius:50%;background:var(--green);animation:pulse 1.5s infinite}
.dot.off{background:var(--red);animation:none}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.2}}
.tabs{display:flex;gap:3px;margin-bottom:14px;background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:4px;position:sticky;top:0;z-index:99}
.tab{flex:1;text-align:center;padding:7px 2px;border-radius:6px;font-size:10px;font-weight:700;cursor:pointer;color:var(--muted);transition:all .2s;letter-spacing:.5px;text-transform:uppercase}
.tab.active{background:var(--bg3);color:var(--text);border:1px solid var(--border)}
.page{display:none}.page.active{display:block}
.card{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:10px}
.card-title{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:1.5px;font-family:'JetBrains Mono',monospace;margin-bottom:10px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
.stat-card{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:12px}
.stat-label{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;font-family:'JetBrains Mono',monospace;margin-bottom:4px}
.stat-val{font-size:20px;font-weight:700;font-family:'JetBrains Mono',monospace}
.stat-sub{font-size:10px;color:var(--muted);margin-top:2px;font-family:'JetBrains Mono',monospace}
.section-title{font-size:9px;font-weight:700;color:var(--muted);letter-spacing:1.5px;text-transform:uppercase;margin:14px 0 8px;font-family:'JetBrains Mono',monospace}
.info-row{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--border);font-size:12px;font-family:'JetBrains Mono',monospace}
.info-row:last-child{border-bottom:none}
.info-key{color:var(--muted)}
.green{color:var(--green)}.red{color:var(--red)}.yellow{color:var(--yellow)}.blue{color:var(--blue)}
.c-green{color:var(--green)}.c-red{color:var(--red)}.c-yellow{color:var(--yellow)}
.htf-badge{display:inline-block;padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700;font-family:'JetBrains Mono',monospace}
.badge-bearish{background:rgba(255,61,87,0.15);color:var(--red);border:1px solid rgba(255,61,87,0.3)}
.badge-bullish{background:rgba(0,230,118,0.15);color:var(--green);border:1px solid rgba(0,230,118,0.3)}
.badge-neutral{background:rgba(255,214,0,0.15);color:var(--yellow);border:1px solid rgba(255,214,0,0.3)}
.badge-wait{background:rgba(88,96,105,0.2);color:var(--muted);border:1px solid var(--border)}
.prog-track{height:6px;background:var(--border);border-radius:3px;overflow:hidden;margin-top:4px}
.prog-fill{height:100%;border-radius:3px;transition:width .5s}
.score-wrap{display:flex;gap:8px;margin-bottom:10px}
.score-box{flex:1;border-radius:8px;padding:10px;text-align:center}
.score-long{background:rgba(0,230,118,0.08);border:1px solid rgba(0,230,118,0.2)}
.score-short{background:rgba(255,61,87,0.08);border:1px solid rgba(255,61,87,0.2)}
.score-num{font-size:32px;font-weight:800;font-family:'JetBrains Mono',monospace}
.score-lbl{font-size:9px;letter-spacing:1px;text-transform:uppercase;font-family:'JetBrains Mono',monospace;color:var(--muted)}
.signal-result{text-align:center;padding:8px;border-radius:6px;font-size:12px;font-weight:700;font-family:'JetBrains Mono',monospace;letter-spacing:1px;margin-bottom:10px}
.rsi-track{height:10px;background:linear-gradient(90deg,var(--red) 0%,var(--yellow) 30%,var(--green) 50%,var(--yellow) 70%,var(--red) 100%);border-radius:5px;position:relative;margin:10px 0 4px}
.rsi-ptr{position:absolute;top:-5px;width:20px;height:20px;background:white;border-radius:50%;border:3px solid var(--bg);transform:translateX(-50%);box-shadow:0 0 8px rgba(255,255,255,0.3);transition:left .5s}
.rsi-labels{display:flex;justify-content:space-between;font-size:9px;color:var(--muted);font-family:'JetBrains Mono',monospace}
.macd-hist-bar{display:flex;align-items:flex-end;gap:2px;height:50px;justify-content:center;margin:8px 0}
.mbar{width:14px;border-radius:2px 2px 0 0}.mbar.pos{background:var(--green)}.mbar.neg{background:var(--red);align-self:flex-start;border-radius:0 0 2px 2px}
.ema-line{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.ema-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.ema-bar-track{flex:1;height:3px;background:var(--border);border-radius:2px;overflow:hidden}
.ema-bar-fill{height:100%;border-radius:2px}
.vol-bar-outer{height:10px;background:var(--border);border-radius:5px;overflow:hidden;margin:6px 0}
.vol-bar-inner{height:100%;border-radius:5px;background:linear-gradient(90deg,var(--blue),#00b0ff);transition:width .5s}
.pos-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.side-badge{padding:4px 12px;border-radius:6px;font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace}
.side-badge.LONG{background:rgba(0,230,118,0.15);color:var(--green);border:1px solid rgba(0,230,118,0.3)}
.side-badge.SHORT{background:rgba(255,61,87,0.15);color:var(--red);border:1px solid rgba(255,61,87,0.3)}
.side-badge.NONE{background:var(--bg3);color:var(--muted);border:1px solid var(--border)}
.pos-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px}
.pos-label{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;font-family:'JetBrains Mono',monospace;margin-bottom:3px}
.pos-value{font-size:15px;font-weight:700;font-family:'JetBrains Mono',monospace}
.info-box{background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:10px}
.info-box-title{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:1.5px;font-family:'JetBrains Mono',monospace;margin-bottom:8px}
.reason-item{font-size:11px;color:var(--text);padding:4px 0;border-bottom:1px solid var(--border);font-family:'JetBrains Mono',monospace}
.reason-item:last-child{border-bottom:none}
.log-box{background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:12px;font-family:'JetBrains Mono',monospace;font-size:10px;line-height:1.8;max-height:500px;overflow-y:auto}
.ll{padding:1px 0}.ll.e{color:var(--red)}.ll.w{color:var(--yellow)}.ll.s{color:var(--green)}.ll.d{color:var(--muted)}
.trade-table{width:100%;border-collapse:collapse;font-size:11px;font-family:'JetBrains Mono',monospace}
.trade-table th{padding:8px;text-align:left;color:var(--muted);font-weight:600;font-size:9px;letter-spacing:.5px;border-bottom:1px solid var(--border);text-transform:uppercase}
.trade-table td{padding:8px;border-bottom:1px solid var(--border)}
.trade-table tr:last-child td{border-bottom:none}
.btn-close{width:100%;padding:12px;background:rgba(255,61,87,0.1);border:1px solid rgba(255,61,87,0.3);color:var(--red);border-radius:8px;font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;letter-spacing:1px;cursor:pointer;margin-top:10px}
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.8);z-index:999;align-items:center;justify-content:center;padding:20px}
.modal-box{background:var(--bg2);border:1px solid var(--border);border-radius:14px;padding:24px;width:100%;max-width:320px;text-align:center}
.modal-btns{display:flex;gap:10px;margin-top:16px}
.modal-btn{flex:1;padding:11px;border-radius:8px;font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;cursor:pointer;border:none}
.modal-btn.confirm{background:var(--red);color:white}
.modal-btn.cancel{background:var(--bg3);color:var(--muted);border:1px solid var(--border)}
.timestamp{text-align:center;font-size:9px;color:var(--muted);font-family:'JetBrains Mono',monospace;margin-top:10px;padding-top:10px;border-top:1px solid var(--border)}
</style>
</head>
<body>
<div class="header">
  <div class="logo">CRYPTO<span>BOT</span></div>
  <div class="status-pill"><div class="dot" id="dot"></div><span id="stxt">...</span></div>
</div>
<div class="tabs">
  <div class="tab active" onclick="showPage('ringkasan',0)">Ringkasan</div>
  <div class="tab" onclick="showPage('analisa',1)">Analisa</div>
  <div class="tab" onclick="showPage('posisi',2)">Posisi</div>
  <div class="tab" onclick="showPage('performa',3)">Performa</div>
  <div class="tab" onclick="showPage('log',4)">Log</div>
</div>
<div class="page active" id="page-ringkasan">
  <div class="grid2">
    <div class="stat-card"><div class="stat-label">Balance</div><div class="stat-val green" id="bal">-</div><div class="stat-sub">USDT Live</div></div>
    <div class="stat-card"><div class="stat-label">PnL Total</div><div class="stat-val" id="pnl">-</div><div class="stat-sub">dari $131.12</div></div>
    <div class="stat-card"><div class="stat-label">Unrealized</div><div class="stat-val" id="upnl">-</div><div class="stat-sub" id="liq">Liq: -</div></div>
    <div class="stat-card"><div class="stat-label">Strategi</div><div class="stat-val yellow" style="font-size:13px" id="strat">-</div><div class="stat-sub" id="symsub">-</div></div>
  </div>
  <div class="section-title">Kondisi Market</div>
  <div class="card">
    <div class="info-row"><span class="info-key">Fear and Greed</span><span id="fg_d">-</span></div>
    <div class="info-row"><span class="info-key">HTF 4h Trend</span><span id="htf_d">-</span></div>
    <div class="info-row"><span class="info-key">Harga SOL</span><span id="sol_p">-</span></div>
    <div class="info-row"><span class="info-key">Posisi Aktif</span><span id="pos_status">Tidak Ada</span></div>
  </div>
  <div class="section-title">Ringkasan Performa</div>
  <div class="card">
    <div class="info-row"><span class="info-key">Total Trade</span><span id="r_total">-</span></div>
    <div class="info-row"><span class="info-key">Win Rate</span><span id="r_wr">-</span></div>
    <div class="info-row"><span class="info-key">R:R Aktual</span><span id="r_rr">-</span></div>
    <div class="info-row"><span class="info-key">Streak</span><span id="r_streak">-</span></div>
  </div>
  <div class="section-title">Filter System</div>
  <div class="card">
    <div class="info-row"><span class="info-key">Mode</span><span class="green">LONG ONLY</span></div>
    <div class="info-row"><span class="info-key">Fear and Greed</span><span class="green">Aktif</span></div>
    <div class="info-row"><span class="info-key">Claude Min</span><span class="green">7/10</span></div>
    <div class="info-row"><span class="info-key">Risk Dynamic</span><span class="green">0.75% / 1.25%</span></div>
    <div class="info-row"><span class="info-key">HTF Filter</span><span class="green">Aktif + MACD Fallback</span></div>
    <div class="info-row"><span class="info-key">Trailing Stop</span><span class="green">50% TP Dynamic</span></div>
    <div class="info-row"><span class="info-key">Claude Setuju</span><span class="green" id="ca">0</span></div>
    <div class="info-row"><span class="info-key">Claude Skip</span><span class="red" id="cs">0</span></div>
  </div>
</div>
<div class="page" id="page-analisa">
  <div class="card">
    <div class="card-title">Signal Score</div>
    <div class="score-wrap">
      <div class="score-box score-long"><div class="score-num green" id="a_lscore">-</div><div class="score-lbl">LONG</div></div>
      <div class="score-box score-short"><div class="score-num red" id="a_sscore">-</div><div class="score-lbl">SHORT</div></div>
    </div>
    <div class="signal-result badge-neutral" id="a_signal_result">MENUNGGU DATA</div>
  </div>
  <div class="card">
    <div class="card-title">EMA Stack (1H)</div>
    <div class="ema-line">
      <div class="ema-dot" style="background:var(--blue)"></div>
      <div style="flex:1">
        <div style="display:flex;justify-content:space-between;font-size:10px;font-family:'JetBrains Mono',monospace;margin-bottom:3px"><span style="color:var(--muted)">EMA 9</span><span id="ema9_val">-</span></div>
        <div class="ema-bar-track"><div class="ema-bar-fill" id="ema9_bar" style="background:var(--blue);width:30%"></div></div>
      </div>
    </div>
    <div class="ema-line">
      <div class="ema-dot" style="background:var(--yellow)"></div>
      <div style="flex:1">
        <div style="display:flex;justify-content:space-between;font-size:10px;font-family:'JetBrains Mono',monospace;margin-bottom:3px"><span style="color:var(--muted)">EMA 21</span><span id="ema21_val">-</span></div>
        <div class="ema-bar-track"><div class="ema-bar-fill" id="ema21_bar" style="background:var(--yellow);width:50%"></div></div>
      </div>
    </div>
    <div class="ema-line" style="margin-bottom:0">
      <div class="ema-dot" style="background:var(--green)"></div>
      <div style="flex:1">
        <div style="display:flex;justify-content:space-between;font-size:10px;font-family:'JetBrains Mono',monospace;margin-bottom:3px"><span style="color:var(--muted)">EMA 55</span><span id="ema55_val">-</span></div>
        <div class="ema-bar-track"><div class="ema-bar-fill" id="ema55_bar" style="background:var(--green);width:70%"></div></div>
      </div>
    </div>
    <div style="margin-top:10px;text-align:center"><span class="htf-badge" id="ema_trend_badge">-</span></div>
  </div>
  <div class="card">
    <div class="card-title">RSI (14)</div>
    <div style="text-align:center">
      <div style="font-size:32px;font-weight:700;font-family:'JetBrains Mono',monospace" id="rsi_big">-</div>
      <div style="font-size:10px;font-family:'JetBrains Mono',monospace;margin-top:2px" id="rsi_zone">-</div>
    </div>
    <div class="rsi-track"><div class="rsi-ptr" id="rsi_ptr" style="left:50%"></div></div>
    <div class="rsi-labels"><span>0</span><span>Oversold 30</span><span>50</span><span>OB 70</span><span>100</span></div>
  </div>
  <div class="card">
    <div class="card-title">MACD Histogram</div>
    <div class="macd-hist-bar" id="macd_bars"></div>
    <div style="display:flex;justify-content:space-between;margin-top:4px">
      <div style="text-align:center"><div style="font-size:13px;font-family:'JetBrains Mono',monospace;font-weight:600" id="macd_val">-</div><div style="font-size:9px;color:var(--muted);font-family:'JetBrains Mono',monospace">MACD</div></div>
      <div style="text-align:center"><div style="font-size:13px;font-family:'JetBrains Mono',monospace;font-weight:600" id="macd_hist_val">-</div><div style="font-size:9px;color:var(--muted);font-family:'JetBrains Mono',monospace">HIST</div></div>
      <div style="text-align:center"><div style="font-size:11px;font-family:'JetBrains Mono',monospace;font-weight:600" id="macd_signal">-</div><div style="font-size:9px;color:var(--muted);font-family:'JetBrains Mono',monospace">SIGNAL</div></div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">Bollinger Band</div>
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
      <div id="squeeze_icon" style="width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:18px;background:rgba(255,214,0,0.1);border:1px solid rgba(255,214,0,0.2)">-</div>
      <div><div style="font-size:13px;font-weight:600" id="squeeze_title">-</div><div style="font-size:10px;color:var(--muted);font-family:'JetBrains Mono',monospace" id="squeeze_sub">-</div></div>
    </div>
    <div style="display:flex;gap:8px">
      <div style="flex:1;background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:8px;text-align:center"><div style="font-size:9px;color:var(--muted);font-family:'JetBrains Mono',monospace">Lower</div><div style="font-size:12px;font-family:'JetBrains Mono',monospace;color:var(--red)" id="bb_lower">-</div></div>
      <div style="flex:1;background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:8px;text-align:center"><div style="font-size:9px;color:var(--muted);font-family:'JetBrains Mono',monospace">Mid</div><div style="font-size:12px;font-family:'JetBrains Mono',monospace;color:var(--yellow)" id="bb_mid">-</div></div>
      <div style="flex:1;background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:8px;text-align:center"><div style="font-size:9px;color:var(--muted);font-family:'JetBrains Mono',monospace">Upper</div><div style="font-size:12px;font-family:'JetBrains Mono',monospace;color:var(--green)" id="bb_upper">-</div></div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">Volume</div>
    <div style="display:flex;justify-content:space-between;font-size:11px;font-family:'JetBrains Mono',monospace;margin-bottom:6px"><span style="color:var(--muted)">Ratio vs MA</span><span id="vol_label" class="blue">-</span></div>
    <div class="vol-bar-outer"><div class="vol-bar-inner" id="vol_bar" style="width:0%"></div></div>
    <div style="display:flex;justify-content:space-between;margin-top:4px;font-size:9px;color:var(--muted);font-family:'JetBrains Mono',monospace"><span>0x</span><span style="color:var(--yellow)">Normal 0.7x</span><span style="color:var(--green)">High 1.5x</span></div>
  </div>
  <div class="card">
    <div class="card-title">HTF 4H</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
      <div style="background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:10px;text-align:center"><div style="font-size:9px;color:var(--muted);font-family:'JetBrains Mono',monospace;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Trend</div><span class="htf-badge" id="htf_trend_badge">-</span></div>
      <div style="background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:10px;text-align:center"><div style="font-size:9px;color:var(--muted);font-family:'JetBrains Mono',monospace;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">EMA 4H</div><span class="htf-badge" id="htf_ema_badge">-</span></div>
      <div style="background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:10px;text-align:center"><div style="font-size:9px;color:var(--muted);font-family:'JetBrains Mono',monospace;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">MACD 4H</div><span class="htf-badge" id="htf_macd_badge">-</span></div>
      <div style="background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:10px;text-align:center"><div style="font-size:9px;color:var(--muted);font-family:'JetBrains Mono',monospace;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">F&amp;G</div><span class="htf-badge" id="htf_fg_badge">-</span></div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">Claude AI Filter</div>
    <div id="claude_decision" style="display:flex;align-items:center;gap:10px;padding:10px;background:rgba(88,96,105,0.1);border:1px solid var(--border);border-radius:8px;margin-bottom:10px">
      <div style="font-size:22px">🤖</div>
      <div><div style="font-size:14px;font-weight:700;font-family:'JetBrains Mono',monospace" id="claude_action">MENUNGGU</div><div style="font-size:10px;color:var(--muted);margin-top:2px;line-height:1.4" id="claude_reason">-</div></div>
    </div>
    <div style="display:flex;justify-content:space-between;font-size:11px;font-family:'JetBrains Mono',monospace;margin-bottom:4px"><span style="color:var(--muted)">Confidence</span><span id="claude_conf_val">-</span></div>
    <div class="prog-track" style="height:8px"><div class="prog-fill" id="claude_conf_bar" style="background:linear-gradient(90deg,var(--yellow),#ff8800);width:0%"></div></div>
  </div>
</div>
<div class="page" id="page-posisi">
  <div class="section-title">Posisi Aktif</div>
  <div class="card">
    <div class="pos-header">
      <span class="side-badge NONE" id="pside">TIDAK ADA</span>
      <span style="font-size:12px;color:var(--muted);font-family:JetBrains Mono,monospace" id="psym">-</span>
    </div>
    <div class="pos-grid">
      <div><div class="pos-label">Entry</div><div class="pos-value" id="pe">-</div></div>
      <div><div class="pos-label">Harga Kini</div><div class="pos-value" id="pp">-</div></div>
      <div><div class="pos-label">Stop Loss</div><div class="pos-value red" id="psl">-</div></div>
      <div><div class="pos-label">Take Profit</div><div class="pos-value green" id="ptp">-</div></div>
    </div>
    <div id="bwrap" style="display:none;margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--muted);font-family:JetBrains Mono,monospace;margin-bottom:4px">
        <span id="bsl">SL</span><span style="color:var(--yellow)">PRICE</span><span id="btp">TP</span>
      </div>
      <div class="prog-track" style="height:6px"><div class="prog-fill" id="bfill" style="background:linear-gradient(90deg,var(--red),var(--green));width:50%"></div></div>
    </div>
    <div id="tw" style="display:none">
      <div class="info-box">
        <div class="info-box-title">Trailing Stop</div>
        <div style="display:flex;justify-content:space-between;font-size:11px;font-family:JetBrains Mono,monospace;margin-bottom:6px">
          <span id="ts" style="color:var(--muted)">Menunggu 50% TP</span><span class="yellow" id="tm"></span>
        </div>
        <div class="prog-track"><div class="prog-fill" id="tf" style="background:linear-gradient(90deg,var(--yellow),var(--green));width:0%"></div></div>
        <div style="display:flex;justify-content:space-between;margin-top:4px;font-size:9px;color:var(--muted);font-family:JetBrains Mono,monospace">
          <span>0%</span><span id="tp2">0%</span><span>100%</span>
        </div>
      </div>
    </div>
    <div id="erw" style="display:none">
      <div class="info-box">
        <div class="info-box-title">Alasan Entry</div>
        <div style="margin-bottom:8px;display:flex;gap:8px;align-items:center">
          <span style="font-size:12px;font-weight:600;color:var(--green);font-family:JetBrains Mono,monospace" id="ec"></span>
          <span style="font-size:11px;color:var(--muted);font-family:JetBrains Mono,monospace" id="eh"></span>
        </div>
        <div id="er"></div>
      </div>
    </div>
    <button id="cbw" onclick="confirmClose()" class="btn-close" style="display:none">CLOSE POSITION</button>
  </div>
  <div class="section-title">Riwayat Trade</div>
  <div class="card" style="overflow:hidden;padding:0">
    <table class="trade-table">
      <thead><tr>
        <th style="padding:10px 8px">Tanggal</th><th>Side</th>
        <th style="text-align:right">Entry</th><th style="text-align:right">Exit</th>
        <th style="text-align:right">PnL</th><th style="text-align:center">Hasil</th>
      </tr></thead>
      <tbody id="tt"><tr><td colspan="6" style="padding:16px;text-align:center;color:var(--muted)">Belum ada trade</td></tr></tbody>
    </table>
  </div>
</div>
<div class="page" id="page-performa">
  <div class="section-title">Statistik</div>
  <div class="card">
    <div class="info-row"><span class="info-key">Total Trade</span><span id="p_total">-</span></div>
    <div class="info-row"><span class="info-key">Win Rate</span><span id="p_wr">-</span></div>
    <div class="info-row"><span class="info-key">Avg Win</span><span class="green" id="p_aw">-</span></div>
    <div class="info-row"><span class="info-key">Avg Loss</span><span class="red" id="p_al">-</span></div>
    <div class="info-row"><span class="info-key">R:R Aktual</span><span id="p_rr">-</span></div>
    <div class="info-row"><span class="info-key">Expectancy</span><span id="p_exp">-</span></div>
  </div>
  <div class="section-title">Long vs Short</div>
  <div class="card">
    <div style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;font-size:11px;font-family:JetBrains Mono,monospace;margin-bottom:4px">
        <span id="p_ll" style="color:var(--muted)">LONG 0T</span><span class="green" id="p_lwr">-</span>
      </div>
      <div class="prog-track"><div class="prog-fill" id="p_lb" style="background:var(--green);width:0%"></div></div>
    </div>
    <div>
      <div style="display:flex;justify-content:space-between;font-size:11px;font-family:JetBrains Mono,monospace;margin-bottom:4px">
        <span id="p_sl" style="color:var(--muted)">SHORT 0T</span><span class="red" id="p_swr">-</span>
      </div>
      <div class="prog-track"><div class="prog-fill" id="p_sb" style="background:var(--red);width:0%"></div></div>
    </div>
  </div>
  <div class="section-title">Tren Terkini</div>
  <div class="card">
    <div class="info-row"><span class="info-key">Streak</span><span id="p_streak">-</span></div>
    <div class="info-row"><span class="info-key">5 Trade Terakhir</span><span id="p_l5" style="letter-spacing:4px">-</span></div>
  </div>
  <div class="section-title">Break Even Progress</div>
  <div class="card">
    <div style="display:flex;justify-content:space-between;font-size:11px;font-family:JetBrains Mono,monospace;margin-bottom:4px">
      <span style="color:var(--muted)">Avg win <span id="p_awn" class="green">$0</span> menuju <span id="p_awt" class="yellow">$0</span></span>
      <span class="yellow" id="p_bep">-</span>
    </div>
    <div class="prog-track"><div class="prog-fill" id="p_beb" style="background:linear-gradient(90deg,var(--red),var(--yellow),var(--green));width:0%"></div></div>
  </div>
  <div class="section-title">Equity Curve</div>
  <div class="card"><canvas id="equityChart" height="120"></canvas></div>
</div>
<div class="page" id="page-log">
  <div class="section-title">Log Terbaru</div>
  <div class="log-box" id="lb2">Memuat...</div>
</div>
<div class="modal-overlay" id="cm">
  <div class="modal-box">
    <div style="font-size:28px;margin-bottom:12px">!</div>
    <div style="font-size:11px;color:var(--muted);margin-bottom:8px;font-family:JetBrains Mono,monospace">KONFIRMASI CLOSE</div>
    <div style="font-size:16px;font-weight:700;margin-bottom:4px" id="ms">-</div>
    <div style="font-size:12px;color:var(--muted);font-family:JetBrains Mono,monospace;margin-bottom:16px" id="mp">-</div>
    <input id="pin_input" type="password" maxlength="6" placeholder="Masukkan PIN"
      style="width:100%;padding:11px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-family:JetBrains Mono,monospace;font-size:16px;text-align:center;letter-spacing:6px;outline:none;margin-bottom:8px"
      onkeydown="if(event.key===Enter)doClose()">
    <div id="pin_error" style="color:var(--red);font-size:11px;display:none;margin-bottom:8px">PIN salah!</div>
    <div class="modal-btns">
      <button class="modal-btn confirm" onclick="doClose()">Ya, Close</button>
      <button class="modal-btn cancel" onclick="cancelClose()">Batal</button>
    </div>
  </div>
</div>
<div class="timestamp">Auto-refresh 10s | <span id="upd">-</span></div>
<script>
let _cp=null,_eqChart=null,_macdHist=[];
function showPage(name,idx){
  ['ringkasan','analisa','posisi','performa','log'].forEach((n,i)=>{
    document.querySelectorAll('.tab')[i].classList.toggle('active',i===idx);
    document.getElementById('page-'+n).classList.toggle('active',n===name);
  });
}
const fmt=(n,d=2)=>n!=null?'$'+Number(n).toLocaleString('en',{minimumFractionDigits:d,maximumFractionDigits:d}):'-';
function badgeClass(v){return v==='BULLISH'?'htf-badge badge-bullish':v==='BEARISH'?'htf-badge badge-bearish':'htf-badge badge-neutral';}
function updateMacdBars(h){
  if(h!==null)_macdHist.push(h);
  if(_macdHist.length>14)_macdHist=_macdHist.slice(-14);
  const c=document.getElementById('macd_bars');
  if(!c||!_macdHist.length)return;
  const mx=Math.max(..._macdHist.map(Math.abs),0.01);
  c.innerHTML=_macdHist.map(v=>'<div class="mbar '+(v>=0?'pos':'neg')+'" style="height:'+Math.max(2,Math.abs(v)/mx*45)+'px"></div>').join('');
}
function updateEquityChart(pts,bal){
  const ctx=document.getElementById('equityChart');
  if(!ctx)return;
  const data=[131.12,...(pts||[])];
  if(bal)data.push(bal);
  const col=data[data.length-1]>=131.12?'#00e676':'#ff3d57';
  if(_eqChart){_eqChart.data.datasets[0].data=data;_eqChart.data.datasets[0].borderColor=col;_eqChart.update();return;}
  _eqChart=new Chart(ctx,{type:'line',data:{labels:data.map((_,i)=>i),datasets:[{data,borderColor:col,borderWidth:1.5,pointRadius:0,fill:true,backgroundColor:(ctx)=>{const{ctx:c,chartArea}=ctx.chart;if(!chartArea)return 'transparent';const g=c.createLinearGradient(0,chartArea.top,0,chartArea.bottom);g.addColorStop(0,col+'33');g.addColorStop(1,col+'00');return g;},tension:0.4}]},options:{responsive:true,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>'$'+c.raw.toFixed(2)},backgroundColor:'#161b22',titleColor:'#586069',bodyColor:'#e6edf3',borderColor:'#1e2530',borderWidth:1}},scales:{x:{display:false},y:{grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#586069',font:{family:'JetBrains Mono',size:9},callback:v=>'$'+v.toFixed(0)}}}}});
}
async function loadTrades(){
  try{
    const d=await(await fetch('/api/trades')).json();
    const tb=document.getElementById('tt');
    if(!d.trades||!d.trades.length){tb.innerHTML='<tr><td colspan="6" style="padding:16px;text-align:center;color:var(--muted)">Belum ada trade</td></tr>';return;}
    tb.innerHTML=d.trades.slice().reverse().slice(0,10).map(t=>{
      const pv=parseFloat(t.pnl)||0;
      const pc=pv>0?'var(--green)':'var(--red)';
      const sc=t.side==='LONG'?'var(--green)':'var(--red)';
      const rs=t.reason==='TAKE_PROFIT'?'TP':pv>0?'TS':'SL';
      const dt=t.date?t.date.substring(5,16):'-';
      return '<tr><td style="color:var(--muted);font-size:10px">'+dt+'</td><td style="color:'+sc+';font-weight:700">'+t.side+'</td><td style="text-align:right">$'+parseFloat(t.entry).toFixed(2)+'</td><td style="text-align:right">$'+parseFloat(t.exit).toFixed(2)+'</td><td style="text-align:right;color:'+pc+';font-weight:700">'+(pv>=0?'+':'')+fmt(Math.abs(pv))+'</td><td style="text-align:center;color:var(--muted)">'+rs+'</td></tr>';
    }).join('');
  }catch(e){console.error(e);}
}
async function refresh(){
  try{
    const d=await(await fetch('/api/status')).json();
    document.getElementById('dot').className='dot '+(d.bot_running?'on':'off');
    document.getElementById('stxt').textContent=d.bot_running?'RUNNING':'STOPPED';
    document.getElementById('bal').textContent=d.balance!=null?fmt(d.balance):'-';
    const pnl=d.total_pnl||0;
    const pe=document.getElementById('pnl');pe.textContent=(pnl>=0?'+':'')+fmt(Math.abs(pnl));pe.className='stat-val '+(pnl>0?'green':pnl<0?'red':'');
    const upnl=d.unrealized_pnl||0;
    const ue=document.getElementById('upnl');ue.textContent=(upnl>=0?'+':'')+fmt(upnl);ue.className='stat-val '+(upnl>0?'green':upnl<0?'red':'');
    document.getElementById('liq').textContent=d.liquidation_price?'Liq: '+fmt(d.liquidation_price):'Liq: -';
    document.getElementById('strat').textContent=d.strategy?d.strategy.replace(/_/g,' ').toUpperCase():'-';
    document.getElementById('symsub').textContent=(d.symbol||'-')+' . '+(d.timeframe||'-');
    const fg=d.fg_value;
    const fe=document.getElementById('fg_d');
    if(fg!=null){fe.textContent=fg+' ('+d.fg_label+')';fe.className=fg<35?'red':fg<50?'yellow':'green';}
    const htf=d.htf_current||'?';
    const he=document.getElementById('htf_d');he.textContent=htf;he.className=htf==='BULLISH'?'green':htf==='BEARISH'?'red':'yellow';
    document.getElementById('sol_p').textContent=d.current_price?fmt(d.current_price):'-';
    const p=d.position;
    const ps=document.getElementById('pos_status');
    ps.textContent=p&&p.side?p.side+' @ '+fmt(p.entry):'Tidak Ada';
    ps.className=p&&p.side==='LONG'?'green':p&&p.side==='SHORT'?'red':'';
    const pf=d.perf||{};const wr=pf.win_rate||0;
    document.getElementById('r_total').textContent=(pf.total||0)+' trade';
    const rw=document.getElementById('r_wr');rw.textContent=wr+'% ('+(pf.wins||0)+'W '+(pf.losses||0)+'L)';rw.className=wr>=45?'green':wr>=35?'yellow':'red';
    const rr=document.getElementById('r_rr');rr.textContent=(pf.rr||0).toFixed(2);rr.className=(pf.rr||0)>=1?'green':(pf.rr||0)>=0.7?'yellow':'red';
    const st=pf.streak||0;const stype=pf.streak_type||'NONE';
    const se=document.getElementById('r_streak');
    if(st>0&&stype!='NONE'){se.textContent=st+' '+(stype=='WIN'?'Win':'Loss')+' berturut';se.className=stype=='WIN'?'green':'red';}
    else{se.textContent='-';se.className='';}
    document.getElementById('ca').textContent=d.claude_approve||0;
    document.getElementById('cs').textContent=d.claude_skip||0;
    document.getElementById('p_total').textContent=(pf.total||0)+' trade';
    const pw=document.getElementById('p_wr');pw.textContent=wr+'% ('+(pf.wins||0)+'W '+(pf.losses||0)+'L)';pw.className=wr>=45?'green':wr>=35?'yellow':'red';
    const aw=pf.avg_win||0;const al=pf.avg_loss||0;
    document.getElementById('p_aw').textContent='+'+(aw||0).toFixed(2);
    document.getElementById('p_al').textContent='-'+(al||0).toFixed(2);
    const pr=document.getElementById('p_rr');pr.textContent=(pf.rr||0).toFixed(2);pr.className=(pf.rr||0)>=1?'green':(pf.rr||0)>=0.7?'yellow':'red';
    const exp=(aw*wr/100)-(al*(100-wr)/100);
    const ee=document.getElementById('p_exp');ee.textContent=(exp>=0?'+':'')+exp.toFixed(3);ee.className=exp>=0?'green':'red';
    document.getElementById('p_ll').textContent='LONG '+(pf.long_total||0)+'T';
    document.getElementById('p_lwr').textContent=(pf.long_wr||0)+'%';
    document.getElementById('p_lb').style.width=(pf.long_wr||0)+'%';
    document.getElementById('p_sl').textContent='SHORT '+(pf.short_total||0)+'T';
    document.getElementById('p_swr').textContent=(pf.short_wr||0)+'%';
    document.getElementById('p_sb').style.width=(pf.short_wr||0)+'%';
    const se2=document.getElementById('p_streak');
    if(st>0&&stype!='NONE'){se2.textContent=st+' '+(stype=='WIN'?'Win':'Loss')+' berturut';se2.className=stype=='WIN'?'green':'red';}
    else{se2.textContent='-';se2.className='';}
    document.getElementById('p_l5').textContent=(pf.last5||[]).join(' ')||'-';
    const bp=pf.be_progress||0;
    document.getElementById('p_bep').textContent=bp.toFixed(1)+'%';
    document.getElementById('p_beb').style.width=Math.min(bp,100)+'%';
    document.getElementById('p_awn').textContent='$'+(aw||0).toFixed(2);
    document.getElementById('p_awt').textContent='$'+(pf.target_avg_win||0).toFixed(2);
    updateEquityChart(pf.equity_points,d.balance);
    const ind=d.last_indicators||{};const sig=d.last_signal||{};
    const sm=sig.reason?sig.reason.match(/L:(\d+) S:(\d+)/):null;
    document.getElementById('a_lscore').textContent=sm?sm[1]:'-';
    document.getElementById('a_sscore').textContent=sm?sm[2]:'-';
    const sr=document.getElementById('a_signal_result');
    if(sig.action==='LONG'){sr.textContent='LONG '+sig.reason;sr.className='signal-result badge-bullish';}
    else if(sig.action==='SHORT'){sr.textContent='SHORT '+sig.reason;sr.className='signal-result badge-bearish';}
    else{sr.textContent='WAIT'+(sig.reason?' - '+sig.reason:'');sr.className='signal-result badge-wait';}
    if(ind.ema9&&ind.ema21&&ind.ema55){
      const mn=Math.min(ind.ema9,ind.ema21,ind.ema55)*0.999;
      const mx=Math.max(ind.ema9,ind.ema21,ind.ema55)*1.001;
      const pct=v=>Math.max(5,Math.min(95,(v-mn)/(mx-mn)*100));
      document.getElementById('ema9_val').textContent=ind.ema9.toFixed(2);
      document.getElementById('ema9_val').className=ind.ema_trend==='BEARISH'?'red':'green';
      document.getElementById('ema9_bar').style.width=pct(ind.ema9)+'%';
      document.getElementById('ema21_val').textContent=ind.ema21.toFixed(2);
      document.getElementById('ema21_bar').style.width=pct(ind.ema21)+'%';
      document.getElementById('ema55_val').textContent=ind.ema55.toFixed(2);
      document.getElementById('ema55_bar').style.width=pct(ind.ema55)+'%';
    }
    const eb=document.getElementById('ema_trend_badge');eb.textContent=ind.ema_trend||'-';eb.className=badgeClass(ind.ema_trend);
    if(ind.rsi){
      document.getElementById('rsi_big').textContent=ind.rsi.toFixed(1);
      document.getElementById('rsi_big').className=ind.rsi<30?'red':ind.rsi>70?'yellow':'green';
      document.getElementById('rsi_zone').textContent=ind.rsi<30?'OVERSOLD':ind.rsi>70?'OVERBOUGHT':'NEUTRAL ZONE';
      document.getElementById('rsi_zone').className=ind.rsi<30?'red':ind.rsi>70?'yellow':'green';
      document.getElementById('rsi_ptr').style.left=ind.rsi+'%';
    }
    if(ind.macd!==undefined){
      const mv=ind.macd;const hv=ind.macd_hist;
      document.getElementById('macd_val').textContent=mv.toFixed(3);document.getElementById('macd_val').className=mv>=0?'green':'red';
      document.getElementById('macd_hist_val').textContent=(hv>=0?'+':'')+hv.toFixed(3);document.getElementById('macd_hist_val').className=hv>=0?'green':'red';
      document.getElementById('macd_signal').textContent=mv>=0&&hv>=0?'BULLISH':mv<0&&hv<0?'BEARISH':'MIXED';
      document.getElementById('macd_signal').className=mv>=0&&hv>=0?'green':mv<0&&hv<0?'red':'yellow';
      updateMacdBars(hv);
    }
    if(ind.bb_lower){
      document.getElementById('bb_lower').textContent=ind.bb_lower.toFixed(2);
      document.getElementById('bb_mid').textContent=ind.bb_mid.toFixed(2);
      document.getElementById('bb_upper').textContent=ind.bb_upper.toFixed(2);
      const sq=ind.squeeze;
      document.getElementById('squeeze_icon').textContent=sq?'🔥':'✅';
      document.getElementById('squeeze_title').textContent=sq?'Squeeze AKTIF':'Squeeze Tidak Aktif';
      document.getElementById('squeeze_title').className=sq?'yellow':'green';
      document.getElementById('squeeze_sub').textContent=sq?'Volatilitas rendah - breakout akan terjadi':'Harga bergerak bebas';
    }
    if(ind.vol_ratio!==undefined){
      const vr=ind.vol_ratio;
      document.getElementById('vol_label').textContent=vr.toFixed(2)+'x - '+(ind.vol_status||'-');
      document.getElementById('vol_label').className=vr>=1.5?'green':vr>=0.7?'blue':'yellow';
      document.getElementById('vol_bar').style.width=Math.min(vr/2*100,100)+'%';
    }
    const tb=document.getElementById('htf_trend_badge');tb.textContent=htf;tb.className=badgeClass(htf);
    document.getElementById('htf_ema_badge').textContent=ind.ema_trend||'-';document.getElementById('htf_ema_badge').className=badgeClass(ind.ema_trend);
    const fb=document.getElementById('htf_fg_badge');
    if(fg!=null){fb.textContent=fg+' '+d.fg_label;fb.className=fg<35?'htf-badge badge-bearish':fg<50?'htf-badge badge-neutral':'htf-badge badge-bullish';}
    const mb=document.getElementById('htf_macd_badge');
    if(ind.macd!==undefined){mb.textContent=ind.macd.toFixed(2);mb.className=ind.macd<-0.3?'htf-badge badge-bearish':ind.macd>0.3?'htf-badge badge-bullish':'htf-badge badge-neutral';}
    const ll=d.logs?d.logs.slice().reverse().find(l=>l.includes('Claude API:')||l.includes('Claude cache')):null;
    if(ll){
      const cm=ll.match(/(LONG|SHORT|WAIT) \((\d+)\/10\) \| (.+)/);
      if(cm){
        const ca=cm[1];const cc=parseInt(cm[2]);const cr=cm[3];
        document.getElementById('claude_action').textContent=ca+' ('+cc+'/10)';
        document.getElementById('claude_action').className=ca==='LONG'?'green':ca==='SHORT'?'red':'yellow';
        document.getElementById('claude_reason').textContent=cr;
        document.getElementById('claude_conf_bar').style.width=(cc*10)+'%';
        document.getElementById('claude_conf_val').textContent=cc+'/10';
        document.getElementById('claude_conf_val').className=cc>=7?'green':cc>=5?'yellow':'red';
        const cd=document.getElementById('claude_decision');
        cd.style.background=ca==='LONG'?'rgba(0,230,118,0.06)':ca==='SHORT'?'rgba(255,61,87,0.06)':'rgba(255,214,0,0.06)';
        cd.style.borderColor=ca==='LONG'?'rgba(0,230,118,0.2)':ca==='SHORT'?'rgba(255,61,87,0.2)':'rgba(255,214,0,0.2)';
      }
    }
    if(p&&p.side){
      document.getElementById('pside').textContent=p.side;document.getElementById('pside').className='side-badge '+p.side;
      document.getElementById('psym').textContent=p.symbol||d.symbol||'-';
      document.getElementById('pe').textContent=fmt(p.entry);document.getElementById('pe').className='pos-value '+(p.side==='LONG'?'green':'red');
      document.getElementById('pp').textContent=fmt(d.current_price);
      document.getElementById('psl').textContent=p.sl?fmt(p.sl):'-';
      document.getElementById('ptp').textContent=p.tp?fmt(p.tp):'-';
      if(p.sl&&p.tp&&d.current_price){
        const pct=p.side==='LONG'?(d.current_price-p.sl)/(p.tp-p.sl)*100:(p.sl-d.current_price)/(p.sl-p.tp)*100;
        document.getElementById('bfill').style.width=Math.min(Math.max(pct,0),100)+'%';
        document.getElementById('bsl').textContent='SL '+fmt(p.sl,1);
        document.getElementById('btp').textContent='TP '+fmt(p.tp,1);
        document.getElementById('bwrap').style.display='block';
      }
      const tprog=p.trail_progress||0;const ta=p.trail_active||false;const tmu=p.trail_mult||0;
      document.getElementById('tw').style.display='block';
      document.getElementById('tf').style.width=tprog+'%';
      document.getElementById('tp2').textContent=tprog.toFixed(1)+'%';
      if(ta){
        let ml=tmu==0.5?'ATR x0.5 Sangat ketat':tmu==0.8?'ATR x0.8 Ketat':tmu==1.2?'ATR x1.2 Agak ketat':'ATR x2.0 Longgar';
        document.getElementById('ts').textContent='Trailing AKTIF';document.getElementById('ts').className='green';
        document.getElementById('tm').textContent=ml;
      }else{
        document.getElementById('ts').textContent='Menunggu 50% TP ('+tprog.toFixed(1)+'%)';
        document.getElementById('ts').className='';document.getElementById('tm').textContent='';
      }
      if(p.entry_reasons&&p.entry_reasons.length){
        document.getElementById('erw').style.display='block';
        document.getElementById('ec').textContent=p.claude_conf?'Claude '+p.claude_conf:'';
        document.getElementById('eh').textContent=p.htf_trend?'HTF: '+p.htf_trend:'';
        document.getElementById('er').innerHTML=p.entry_reasons.map(r=>'<div class="reason-item">'+r+'</div>').join('');
      }
      _cp=p;document.getElementById('cbw').style.display='block';
    }else{
      document.getElementById('pside').textContent='TIDAK ADA';document.getElementById('pside').className='side-badge NONE';
      ['pe','pp','psl','ptp'].forEach(id=>{document.getElementById(id).textContent='-';document.getElementById(id).className='pos-value';});
      ['bwrap','tw','erw'].forEach(id=>document.getElementById(id).style.display='none');
      document.getElementById('cbw').style.display='none';_cp=null;
    }
    if(d.logs&&d.logs.length){
      const lb=document.getElementById('lb2');
      lb.innerHTML=d.logs.map(l=>{
        let c='';
        if(l.includes('ERROR')||l.includes('STOP_LOSS'))c='e';
        else if(l.includes('WARNING'))c='w';
        else if(l.includes('TAKE_PROFIT')||l.includes('Full size')||l.includes('Medium size'))c='s';
        else if(l.includes('DEBUG')||l.includes('WAIT'))c='d';
        return '<div class="ll '+c+'">'+l.replace(/</g,'&lt;')+'</div>';
      }).join('');
      lb.scrollTop=lb.scrollHeight;
    }
    document.getElementById('upd').textContent=new Date().toLocaleTimeString('id-ID');
  }catch(e){document.getElementById('dot').className='dot off';document.getElementById('stxt').textContent='ERROR';}
}
let _cp2=null;
function confirmClose(){
  if(!_cp)return;
  document.getElementById('ms').textContent=_cp.side+' @ $'+parseFloat(_cp.entry).toFixed(2);
  const upnl=parseFloat((document.getElementById('upnl').textContent||'0').replace('$','').replace('+',''))||0;
  document.getElementById('mp').textContent='PnL: '+(upnl>=0?'+':'')+'$'+Math.abs(upnl).toFixed(2);
  document.getElementById('cm').style.display='flex';
  document.getElementById('pin_input').value='';document.getElementById('pin_error').style.display='none';
  setTimeout(()=>document.getElementById('pin_input').focus(),100);
}
function cancelClose(){document.getElementById('cm').style.display='none';}
async function doClose(){
  const pin=document.getElementById('pin_input').value;
  if(!pin){document.getElementById('pin_error').style.display='block';document.getElementById('pin_error').textContent='Masukkan PIN!';return;}
  try{
    const r=await fetch('/api/close_position',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin})});
    const d=await r.json();
    if(d.success){document.getElementById('cm').style.display='none';alert(d.message);refresh();}
    else{document.getElementById('pin_error').style.display='block';document.getElementById('pin_error').textContent=d.error||'Gagal!';}
  }catch(e){alert('Error: '+e.message);}
}
refresh();loadTrades();
setInterval(refresh,10000);setInterval(loadTrades,30000);
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/api/status")
def api_status():
    try:
        logs = parse_logs()
        state = extract_state(logs)
        state = enrich_with_binance(state)
        trades = parse_trades()
        perf = get_perf(trades)
        total_pnl = round(sum(float(t["pnl"]) for t in trades), 2)
        from config import config
        return jsonify({
            **state,
            "total_pnl": total_pnl,
            "claude_approve": sum(1 for f in __import__("glob").glob(os.path.join(BASE_DIR,"logs","cryptobot_*.log")) for l in open(f) if "Full size" in l or "Medium size" in l),
            "claude_skip": sum(1 for f in __import__("glob").glob(os.path.join(BASE_DIR,"logs","cryptobot_*.log")) for l in open(f) if "Reduced size" in l),
            "perf": perf,
            "strategy": getattr(config.trading, "strategy", "trend_following"),
            "symbol": config.trading.symbol,
            "timeframe": config.trading.timeframe,
        })
    except Exception as e:
        return jsonify({"error": str(e), "bot_running": False})

@app.route("/api/trades")
def api_trades():
    try:
        trades = parse_trades()
        return jsonify({"trades": trades})
    except Exception as e:
        return jsonify({"trades": [], "error": str(e)})

@app.route("/api/close_position", methods=["POST"])
def api_close_position():
    try:
        data = request.get_json()
        if not data or data.get("pin") != CLOSE_PIN:
            return jsonify({"success": False, "error": "PIN salah"})
        client = get_client()
        if not client:
            return jsonify({"success": False, "error": "Client tidak tersedia"})
        from config import config
        symbol = config.trading.symbol
        positions = client.get_open_positions(symbol)
        pos = positions[0] if positions else None
        if not pos or float(pos.get("positionAmt", 0)) == 0:
            return jsonify({"success": False, "error": "Tidak ada posisi aktif"})
        amt = float(pos["positionAmt"])
        side = "SELL" if amt > 0 else "BUY"
        result = client.place_market_order(symbol, side, abs(amt))
        if result:
            return jsonify({"success": True, "message": "Posisi berhasil ditutup"})
        return jsonify({"success": False, "error": "Gagal menutup posisi"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
