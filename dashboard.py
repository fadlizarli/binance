"""
dashboard.py — CryptoBot Web Dashboard (clean rewrite)
"""
import os, re, sys, glob, time
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request

app      = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

CLOSE_PIN = os.getenv("DASHBOARD_PIN", "1234")
LOG_GLOB  = os.path.join(BASE_DIR, "logs", "cryptobot_*.log")

_client     = None
_live_cache = {"ts": 0, "data": {}}
_scan_cache = {"ts": 0, "data": []}


# ── Exchange client ───────────────────────────────────────────────────────────
def get_client():
    global _client
    if _client is None:
        try:
            from exchange.binance_client import BinanceClient
            _client = BinanceClient()
        except Exception:
            pass
    return _client


# ── Log helpers ───────────────────────────────────────────────────────────────
def read_logs():
    files = sorted(glob.glob(LOG_GLOB))
    if not files:
        return []
    lines = []
    for f in files[-3:]:
        try:
            with open(f) as fp:
                lines.extend(l.rstrip() for l in fp)
        except Exception:
            pass
    return lines


def parse_trades():
    trades = []
    for f in sorted(glob.glob(LOG_GLOB)):
        try:
            with open(f) as fp:
                lines = fp.readlines()
            for i, line in enumerate(lines):
                if "POSISI DITUTUP" not in line or i + 1 >= len(lines):
                    continue
                reason = "TAKE_PROFIT" if "TAKE_PROFIT" in line else "STOP_LOSS"
                m = re.search(
                    r"(LONG|SHORT) \S+ \| Entry: \$([0-9.]+) . Exit: \$([0-9.]+) \| PnL: \$([+-]?[0-9.]+)",
                    lines[i + 1],
                )
                if not m:
                    continue
                ts = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", line)
                trades.append({
                    "date": ts.group(1) if ts else "",
                    "side": m.group(1), "entry": m.group(2),
                    "exit": m.group(3), "pnl":   m.group(4),
                    "reason": reason,
                })
        except Exception:
            pass
    return trades


def calc_perf(trades):
    if not trades:
        return {
            "total": 0, "wins": 0, "losses": 0, "win_rate": 0,
            "avg_win": 0, "avg_loss": 0, "rr": 0,
            "streak": 0, "streak_type": "NONE", "last5": [],
            "long_total": 0, "long_wr": 0, "short_total": 0, "short_wr": 0,
            "equity": [], "be_progress": 0, "target_avg_win": 0,
        }
    wins   = [t for t in trades if float(t["pnl"]) > 0]
    losses = [t for t in trades if float(t["pnl"]) <= 0]
    aw = sum(float(t["pnl"]) for t in wins)        / len(wins)   if wins   else 0
    al = sum(abs(float(t["pnl"])) for t in losses) / len(losses) if losses else 0
    wr = round(len(wins) / len(trades) * 100, 1)
    streak = 0; stype = "NONE"
    for t in reversed(trades):
        w = float(t["pnl"]) > 0
        if streak == 0:
            streak = 1; stype = "WIN" if w else "LOSS"
        elif (w and stype == "WIN") or (not w and stype == "LOSS"):
            streak += 1
        else:
            break
    longs  = [t for t in trades if t["side"] == "LONG"]
    shorts = [t for t in trades if t["side"] == "SHORT"]
    eq = [122.0]
    for t in trades:
        eq.append(round(eq[-1] + float(t["pnl"]), 2))
    taw = max(al, 1.30) if losses else 1.30
    return {
        "total": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate": wr, "avg_win": round(aw, 2), "avg_loss": round(al, 2),
        "rr": round(aw / al, 2) if al > 0 else 0,
        "streak": streak, "streak_type": stype,
        "last5": ["W" if float(t["pnl"]) > 0 else "L" for t in trades[-5:]],
        "long_total": len(longs),
        "long_wr":  round(len([t for t in longs  if float(t["pnl"]) > 0]) / len(longs)  * 100, 1) if longs  else 0,
        "short_total": len(shorts),
        "short_wr": round(len([t for t in shorts if float(t["pnl"]) > 0]) / len(shorts) * 100, 1) if shorts else 0,
        "equity": eq[1:],
        "be_progress":   min(100, round(aw / taw * 100, 1)) if taw > 0 else 0,
        "target_avg_win": round(taw, 2),
    }


def extract_state(logs):
    state = {
        "running": False, "balance": None,
        "fg_value": None, "fg_label": None, "htf": None,
        "signal": None, "ind": {},
        "log_pos": None,
        "claude_approve": 0, "claude_skip": 0,
        "logs": [],
    }
    if not logs:
        return state
    state["logs"] = logs[-40:]
    last_side = last_entry = last_sl = last_tp = None
    for line in logs:
        if "BOT DIMULAI" in line:
            state["running"] = True
        if "💰 Balance:" in line:
            m = re.search(r"Balance: \$([0-9,.]+)", line)
            if m:
                state["balance"] = float(m.group(1).replace(",", ""))
        if "Fear & Greed" in line and "update:" in line:
            m = re.search(r"update: (\d+) \((.+?)\)", line)
            if m:
                state["fg_value"] = int(m.group(1))
                state["fg_label"] = m.group(2)
        if "HTF 4h" in line and any(x in line for x in ("BULLISH", "BEARISH", "NEUTRAL")):
            m = re.search(r"HTF 4h[^:]*: (\w+)", line)
            if m:
                state["htf"] = m.group(1)
        if "Membuka posisi LONG"  in line: last_side = "LONG"
        if "Membuka posisi SHORT" in line: last_side = "SHORT"
        if "Entry:" in line and "SL:" in line and "TP:" in line and "Risk" not in line:
            m = re.search(r"Entry: \$([0-9,.]+).*SL: \$([0-9,.]+).*TP: \$([0-9,.]+)", line)
            if m:
                last_entry = float(m.group(1).replace(",", ""))
                last_sl    = float(m.group(2).replace(",", ""))
                last_tp    = float(m.group(3).replace(",", ""))
        if "POSISI DITUTUP" in line:
            last_side = last_entry = last_sl = last_tp = None
        if "Full size" in line or "Medium size" in line:
            state["claude_approve"] += 1
        if "Reduced size" in line:
            state["claude_skip"] += 1
        if "Sinyal:" in line:
            m = re.search(r"Sinyal: (\w+) \(strength: ([0-9.]+)\)(.*)", line)
            if m:
                state["signal"] = {
                    "action": m.group(1),
                    "strength": float(m.group(2)),
                    "reason": m.group(3).strip(),
                }
        if "Scanner pilih:" in line:
            m = re.search(r"Scanner pilih: (\w+) \| (\w+) \(score=([0-9.]+)\)(.*)", line)
            if m:
                state["signal"] = {
                    "action": m.group(2),
                    "strength": float(m.group(3)),
                    "reason": m.group(4).strip(),
                    "symbol": m.group(1),
                }
        if "Close:" in line and "ATR:" in line:
            m = re.search(r"Close: \$([0-9.]+) \| ATR: ([0-9.]+)", line)
            if m:
                state["ind"]["close"] = float(m.group(1))
                state["ind"]["atr"]   = float(m.group(2))
        if "EMA  :" in line:
            m = re.search(r"EMA\s+: ([0-9.]+)/([0-9.]+)/([0-9.]+) \[(\w+)\]", line)
            if m:
                state["ind"].update({
                    "ema9": float(m.group(1)), "ema21": float(m.group(2)),
                    "ema55": float(m.group(3)), "ema_trend": m.group(4),
                })
        if "RSI  :" in line:
            m = re.search(r"RSI\s+: ([0-9.]+)", line)
            if m: state["ind"]["rsi"] = float(m.group(1))
        if "MACD :" in line:
            m = re.search(r"MACD\s+: ([+-]?[0-9.]+) hist:([+-]?[0-9.]+)", line)
            if m:
                state["ind"]["macd"]      = float(m.group(1))
                state["ind"]["macd_hist"] = float(m.group(2))
        if "BB   :" in line:
            m = re.search(r"BB\s+: ([0-9.]+)/([0-9.]+)/([0-9.]+) \[(\w+)\] Squeeze:(\w+)", line)
            if m:
                state["ind"].update({
                    "bb_lower": float(m.group(1)), "bb_mid": float(m.group(2)),
                    "bb_upper": float(m.group(3)), "bb_pos": m.group(4),
                    "squeeze":  m.group(5) == "True",
                })
        if "Vol  :" in line:
            m = re.search(r"Vol\s+: ([0-9.]+)x \[(\w+)\]", line)
            if m:
                state["ind"]["vol_ratio"]  = float(m.group(1))
                state["ind"]["vol_status"] = m.group(2)

    if last_side and last_entry:
        state["log_pos"] = {
            "side": last_side, "entry": last_entry,
            "sl": last_sl, "tp": last_tp,
        }
    return state


def get_live_data():
    global _live_cache
    now = time.time()
    if now - _live_cache["ts"] < 15 and _live_cache["data"]:
        return {**_live_cache["data"], "cached": True}
    result = {
        "balance": None, "price": None,
        "live_pos": None, "upnl": 0, "liq": None,
    }
    try:
        from config import config
        symbol       = config.trading.symbol
        scan_symbols = config.trading.scan_symbols or []
    except Exception:
        symbol = "SOLUSDT"; scan_symbols = []

    try:
        import requests as _req
        r = _req.get(
            f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
            timeout=4,
        )
        if r.status_code == 200:
            result["price"] = float(r.json()["price"])
    except Exception:
        pass

    try:
        client = get_client()
        if client and client.is_connected():
            bal = client.get_account_balance()
            if bal:
                result["balance"] = bal
            for sym in (scan_symbols or [symbol]):
                try:
                    pos = client.get_open_positions(sym)
                    if not pos:
                        continue
                    amt = float(pos[0].get("positionAmt", 0))
                    if amt == 0:
                        continue
                    ep   = float(pos[0].get("entryPrice", 0))
                    liq  = float(pos[0].get("liquidationPrice", 0))
                    upnl = float(pos[0].get("unRealizedProfit", 0))
                    px   = client.get_ticker_price(sym)
                    if px:
                        result["price"] = px
                    result["live_pos"] = {
                        "symbol": sym,
                        "side":   "LONG" if amt > 0 else "SHORT",
                        "entry":  ep, "liq": liq, "upnl": upnl,
                    }
                    result["upnl"] = upnl
                    result["liq"]  = liq
                    break
                except Exception:
                    continue
    except Exception:
        pass

    _live_cache = {"ts": now, "data": result}
    return {**result, "cached": False}


# ── HTML ──────────────────────────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CryptoBot v4</title>
<style>
:root{--bg:#070a0e;--bg2:#0d1117;--bg3:#161b22;--brd:#1e2530;--grn:#00e676;--red:#ff3d57;--ylw:#ffd600;--blu:#2979ff;--txt:#e6edf3;--mut:#586069}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--txt);font-family:'Segoe UI',system-ui,-apple-system,sans-serif;min-height:100vh;padding:12px;padding-bottom:80px}
/* Header */
.hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.logo{font-family:'Courier New',monospace;font-size:15px;font-weight:700;color:var(--grn);letter-spacing:3px}
.logo span{color:var(--mut)}
.pill{display:flex;align-items:center;gap:6px;background:rgba(255,255,255,0.04);border:1px solid var(--brd);padding:4px 10px;border-radius:20px;font-size:11px;font-family:'Courier New',monospace}
.dot{width:7px;height:7px;border-radius:50%;background:var(--mut)}
.dot.on{background:var(--grn);animation:pulse 1.5s infinite}
.dot.off{background:var(--red)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
/* Tabs */
.tabs{display:flex;gap:3px;background:var(--bg2);border:1px solid var(--brd);border-radius:8px;padding:4px;position:sticky;top:0;z-index:99;margin-bottom:12px}
.tab{flex:1;text-align:center;padding:7px 2px;border-radius:5px;font-size:10px;font-weight:700;cursor:pointer;color:var(--mut);transition:all .2s;text-transform:uppercase;letter-spacing:.5px}
.tab.active{background:var(--bg3);color:var(--txt);border:1px solid var(--brd)}
.page{display:none}.page.active{display:block}
/* Cards */
.card{background:var(--bg2);border:1px solid var(--brd);border-radius:10px;padding:14px;margin-bottom:10px}
.card-title{font-size:9px;color:var(--mut);text-transform:uppercase;letter-spacing:1.5px;font-family:'Courier New',monospace;margin-bottom:10px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
.scard{background:var(--bg2);border:1px solid var(--brd);border-radius:10px;padding:12px}
.slabel{font-size:9px;color:var(--mut);text-transform:uppercase;letter-spacing:1px;font-family:'Courier New',monospace;margin-bottom:4px}
.sval{font-size:20px;font-weight:700;font-family:'Courier New',monospace}
.ssub{font-size:10px;color:var(--mut);margin-top:2px;font-family:'Courier New',monospace}
/* Info rows */
.sec{font-size:9px;font-weight:700;color:var(--mut);letter-spacing:1.5px;text-transform:uppercase;margin:12px 0 8px;font-family:'Courier New',monospace}
.row{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--brd);font-size:12px;font-family:'Courier New',monospace}
.row:last-child{border-bottom:none}
.rk{color:var(--mut)}
/* Colors */
.grn{color:var(--grn)}.red{color:var(--red)}.ylw{color:var(--ylw)}.blu{color:var(--blu)}
/* Badge */
.badge{display:inline-block;padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700;font-family:'Courier New',monospace}
.b-bull{background:rgba(0,230,118,.15);color:var(--grn);border:1px solid rgba(0,230,118,.3)}
.b-bear{background:rgba(255,61,87,.15);color:var(--red);border:1px solid rgba(255,61,87,.3)}
.b-neut{background:rgba(255,214,0,.15);color:var(--ylw);border:1px solid rgba(255,214,0,.3)}
.b-wait{background:rgba(88,96,105,.2);color:var(--mut);border:1px solid var(--brd)}
/* Progress */
.bar-track{height:6px;background:var(--brd);border-radius:3px;overflow:hidden;margin-top:4px}
.bar-fill{height:100%;border-radius:3px;transition:width .5s}
/* Position page */
.pos-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.side-badge{padding:4px 12px;border-radius:6px;font-size:13px;font-weight:700;font-family:'Courier New',monospace}
.sb-long{background:rgba(0,230,118,.15);color:var(--grn);border:1px solid rgba(0,230,118,.3)}
.sb-short{background:rgba(255,61,87,.15);color:var(--red);border:1px solid rgba(255,61,87,.3)}
.sb-none{background:var(--bg3);color:var(--mut);border:1px solid var(--brd)}
.pos-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
.plabel{font-size:9px;color:var(--mut);text-transform:uppercase;letter-spacing:1px;font-family:'Courier New',monospace;margin-bottom:3px}
.pval{font-size:15px;font-weight:700;font-family:'Courier New',monospace}
/* Analisa */
.rsi-track{height:10px;background:linear-gradient(90deg,var(--red) 0%,var(--ylw) 30%,var(--grn) 50%,var(--ylw) 70%,var(--red) 100%);border-radius:5px;position:relative;margin:10px 0 4px}
.rsi-ptr{position:absolute;top:-5px;width:20px;height:20px;background:white;border-radius:50%;border:3px solid var(--bg);transform:translateX(-50%);box-shadow:0 0 8px rgba(255,255,255,.3);transition:left .5s}
.rsi-lbl{display:flex;justify-content:space-between;font-size:9px;color:var(--mut);font-family:'Courier New',monospace}
.ema-row{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.ema-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.ema-bar{flex:1;height:3px;background:var(--brd);border-radius:2px;overflow:hidden}
.ema-fill{height:100%;border-radius:2px}
.macd-bars{display:flex;align-items:flex-end;gap:2px;height:50px;justify-content:center;margin:8px 0}
.mb{width:14px;border-radius:2px 2px 0 0}.mb.p{background:var(--grn)}.mb.n{background:var(--red);align-self:flex-start;border-radius:0 0 2px 2px}
.vol-bar{height:10px;background:var(--brd);border-radius:5px;overflow:hidden;margin:6px 0}
.vol-fill{height:100%;border-radius:5px;background:linear-gradient(90deg,var(--blu),#00b0ff);transition:width .5s}
/* Signal score */
.sc-wrap{display:flex;gap:8px;margin-bottom:10px}
.sc-box{flex:1;border-radius:8px;padding:10px;text-align:center}
.sc-long{background:rgba(0,230,118,.08);border:1px solid rgba(0,230,118,.2)}
.sc-short{background:rgba(255,61,87,.08);border:1px solid rgba(255,61,87,.2)}
.sc-num{font-size:32px;font-weight:800;font-family:'Courier New',monospace}
.sig-result{text-align:center;padding:8px;border-radius:6px;font-size:12px;font-weight:700;font-family:'Courier New',monospace;letter-spacing:1px;margin-bottom:10px}
/* Pair cards */
.pair-scroll{overflow-x:auto;scrollbar-width:none;margin-bottom:10px}
.pair-scroll::-webkit-scrollbar{display:none}
.pair-row{display:flex;gap:6px;min-width:max-content;padding-bottom:2px}
.pair-card{background:var(--bg3);border:1px solid var(--brd);border-radius:8px;padding:8px 10px;min-width:74px;cursor:pointer;text-align:center;transition:border-color .2s}
.pair-card.active{border-color:var(--grn)!important;background:rgba(0,230,118,.06)}
.pair-card.sl{border-color:rgba(0,230,118,.35)}
.pair-card.ss{border-color:rgba(255,61,87,.35)}
.pc-sym{font-size:11px;font-weight:700;font-family:'Courier New',monospace;margin-bottom:3px}
.pc-sig{font-size:9px;font-weight:700;letter-spacing:.5px;font-family:'Courier New',monospace;margin-bottom:3px}
.pc-bar{height:3px;background:var(--brd);border-radius:2px;overflow:hidden;margin-bottom:3px}
.pc-fill{height:100%;border-radius:2px}
.pc-meta{font-size:9px;font-family:'Courier New',monospace;color:var(--mut);line-height:1.6}
/* Trade table */
.trade-table{width:100%;border-collapse:collapse;font-size:11px;font-family:'Courier New',monospace}
.trade-table th{padding:8px;text-align:left;color:var(--mut);font-size:9px;letter-spacing:.5px;border-bottom:1px solid var(--brd);text-transform:uppercase;font-weight:600}
.trade-table td{padding:8px;border-bottom:1px solid var(--brd)}
.trade-table tr:last-child td{border-bottom:none}
/* Log */
.log-box{background:var(--bg3);border:1px solid var(--brd);border-radius:8px;padding:12px;font-family:'Courier New',monospace;font-size:10px;line-height:1.8;max-height:500px;overflow-y:auto}
.ll.e{color:var(--red)}.ll.w{color:var(--ylw)}.ll.s{color:var(--grn)}.ll.d{color:var(--mut)}
/* Close button & modal */
.btn-close{width:100%;padding:12px;background:rgba(255,61,87,.1);border:1px solid rgba(255,61,87,.3);color:var(--red);border-radius:8px;font-family:'Courier New',monospace;font-size:12px;font-weight:700;cursor:pointer;margin-top:10px}
.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:999;align-items:center;justify-content:center;padding:20px}
.modal-box{background:var(--bg2);border:1px solid var(--brd);border-radius:14px;padding:24px;width:100%;max-width:320px;text-align:center}
.modal-btns{display:flex;gap:10px;margin-top:16px}
.mbtn{flex:1;padding:11px;border-radius:8px;font-family:'Courier New',monospace;font-size:12px;font-weight:700;cursor:pointer;border:none}
.mbtn.ok{background:var(--red);color:white}
.mbtn.cancel{background:var(--bg3);color:var(--mut);border:1px solid var(--brd)}
.ts{text-align:center;font-size:9px;color:var(--mut);font-family:'Courier New',monospace;margin-top:10px;padding-top:10px;border-top:1px solid var(--brd)}
</style>
</head>
<body>
<div class="hdr">
  <div class="logo">CRYPTO<span>BOT</span> <span style="font-size:9px;opacity:.4">v4</span></div>
  <div class="pill"><div class="dot" id="dot"></div><span id="stxt">LOADING</span></div>
</div>
<div class="tabs">
  <div class="tab active" onclick="tab('ringkasan',0)">Ringkasan</div>
  <div class="tab" onclick="tab('analisa',1);if(scanMode)loadPairs()">Analisa</div>
  <div class="tab" onclick="tab('posisi',2)">Posisi</div>
  <div class="tab" onclick="tab('performa',3)">Performa</div>
  <div class="tab" onclick="tab('log',4)">Log</div>
</div>

<!-- RINGKASAN -->
<div class="page active" id="p-ringkasan">
  <div class="grid2">
    <div class="scard"><div class="slabel">Balance</div><div class="sval grn" id="s-bal">-</div><div class="ssub">USDT Live</div></div>
    <div class="scard"><div class="slabel">PnL Total</div><div class="sval" id="s-pnl">-</div><div class="ssub">dari $122.00</div></div>
    <div class="scard"><div class="slabel">Unrealized</div><div class="sval" id="s-upnl">-</div><div class="ssub" id="s-liq">Liq: -</div></div>
    <div class="scard"><div class="slabel">Strategi</div><div class="sval ylw" style="font-size:13px" id="s-strat">-</div><div class="ssub" id="s-sym">-</div></div>
  </div>
  <div class="sec">Kondisi Market</div>
  <div class="card">
    <div class="row"><span class="rk">Fear &amp; Greed</span><span id="s-fg">-</span></div>
    <div class="row"><span class="rk">HTF 4h Trend</span><span id="s-htf">-</span></div>
    <div class="row"><span class="rk">Signal Terkuat</span><span id="s-signal">-</span></div>
    <div class="row"><span class="rk">Harga Live</span><span id="s-price">-</span></div>
    <div class="row"><span class="rk">Posisi Aktif</span><span id="s-posisi">Tidak Ada</span></div>
  </div>
  <div class="sec">Ringkasan Performa</div>
  <div class="card">
    <div class="row"><span class="rk">Total Trade</span><span id="s-total">-</span></div>
    <div class="row"><span class="rk">Win Rate</span><span id="s-wr">-</span></div>
    <div class="row"><span class="rk">R:R Aktual</span><span id="s-rr">-</span></div>
    <div class="row"><span class="rk">Streak</span><span id="s-streak">-</span></div>
  </div>
  <div class="sec">Filter Aktif</div>
  <div class="card">
    <div class="row"><span class="rk">Fear &amp; Greed</span><span class="grn">Aktif</span></div>
    <div class="row"><span class="rk">HTF 4h Filter</span><span class="grn">Aktif + MACD Fallback</span></div>
    <div class="row"><span class="rk">Trailing Stop</span><span class="grn">50% TP Dynamic</span></div>
    <div class="row"><span class="rk">Claude Full</span><span class="grn" id="s-ca">0</span></div>
    <div class="row"><span class="rk">Claude Reduce</span><span class="red" id="s-cs">0</span></div>
  </div>
</div>

<!-- ANALISA -->
<div class="page" id="p-analisa">
  <div id="pair-selector" style="display:none">
    <div class="sec" style="display:flex;justify-content:space-between">
      <span>Scan Pairs</span><span id="scan-ts" style="font-weight:400;color:var(--mut)"></span>
    </div>
    <div class="pair-scroll">
      <div class="pair-row" id="pair-cards"><div style="color:var(--mut);font-size:11px;font-family:'Courier New',monospace;padding:8px">Memuat...</div></div>
    </div>
    <div class="sec">Detail: <span id="pair-sym" class="grn">-</span></div>
  </div>
  <div class="card">
    <div class="card-title">Signal Score</div>
    <div class="sc-wrap">
      <div class="sc-box sc-long"><div class="sc-num grn" id="a-ls">-</div><div style="font-size:9px;color:var(--mut);font-family:'Courier New',monospace;text-transform:uppercase;letter-spacing:1px">LONG</div></div>
      <div class="sc-box sc-short"><div class="sc-num red" id="a-ss">-</div><div style="font-size:9px;color:var(--mut);font-family:'Courier New',monospace;text-transform:uppercase;letter-spacing:1px">SHORT</div></div>
    </div>
    <div class="sig-result b-wait" id="a-sig">MENUNGGU DATA</div>
  </div>
  <div class="card">
    <div class="card-title">EMA Stack (1H)</div>
    <div class="ema-row">
      <div class="ema-dot" style="background:var(--blu)"></div>
      <div style="flex:1"><div style="display:flex;justify-content:space-between;font-size:10px;font-family:'Courier New',monospace;margin-bottom:3px"><span style="color:var(--mut)">EMA 9</span><span id="a-e9">-</span></div><div class="ema-bar"><div class="ema-fill" id="a-e9b" style="background:var(--blu);width:30%"></div></div></div>
    </div>
    <div class="ema-row">
      <div class="ema-dot" style="background:var(--ylw)"></div>
      <div style="flex:1"><div style="display:flex;justify-content:space-between;font-size:10px;font-family:'Courier New',monospace;margin-bottom:3px"><span style="color:var(--mut)">EMA 21</span><span id="a-e21">-</span></div><div class="ema-bar"><div class="ema-fill" id="a-e21b" style="background:var(--ylw);width:50%"></div></div></div>
    </div>
    <div class="ema-row" style="margin-bottom:0">
      <div class="ema-dot" style="background:var(--grn)"></div>
      <div style="flex:1"><div style="display:flex;justify-content:space-between;font-size:10px;font-family:'Courier New',monospace;margin-bottom:3px"><span style="color:var(--mut)">EMA 55</span><span id="a-e55">-</span></div><div class="ema-bar"><div class="ema-fill" id="a-e55b" style="background:var(--grn);width:70%"></div></div></div>
    </div>
    <div style="margin-top:10px;text-align:center"><span class="badge b-neut" id="a-etbadge">-</span></div>
  </div>
  <div class="card">
    <div class="card-title">RSI (14)</div>
    <div style="text-align:center"><div style="font-size:32px;font-weight:700;font-family:'Courier New',monospace" id="a-rsi">-</div><div style="font-size:10px;font-family:'Courier New',monospace;margin-top:2px" id="a-rsi-zone">-</div></div>
    <div class="rsi-track"><div class="rsi-ptr" id="a-rsi-ptr" style="left:50%"></div></div>
    <div class="rsi-lbl"><span>0</span><span>OS 30</span><span>50</span><span>OB 70</span><span>100</span></div>
  </div>
  <div class="card">
    <div class="card-title">MACD</div>
    <div class="macd-bars" id="a-macd-bars"></div>
    <div style="display:flex;justify-content:space-between;margin-top:4px">
      <div style="text-align:center"><div style="font-size:13px;font-family:'Courier New',monospace;font-weight:600" id="a-macd">-</div><div style="font-size:9px;color:var(--mut);font-family:'Courier New',monospace">MACD</div></div>
      <div style="text-align:center"><div style="font-size:13px;font-family:'Courier New',monospace;font-weight:600" id="a-hist">-</div><div style="font-size:9px;color:var(--mut);font-family:'Courier New',monospace">HIST</div></div>
      <div style="text-align:center"><div style="font-size:11px;font-family:'Courier New',monospace;font-weight:600" id="a-macd-sig">-</div><div style="font-size:9px;color:var(--mut);font-family:'Courier New',monospace">SIGNAL</div></div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">Bollinger Band</div>
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
      <div id="a-sq-icon" style="width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:18px;background:rgba(255,214,0,.1);border:1px solid rgba(255,214,0,.2)">-</div>
      <div><div style="font-size:13px;font-weight:600" id="a-sq-title">-</div><div style="font-size:10px;color:var(--mut);font-family:'Courier New',monospace" id="a-sq-sub">-</div></div>
    </div>
    <div style="display:flex;gap:8px">
      <div style="flex:1;background:var(--bg3);border:1px solid var(--brd);border-radius:6px;padding:8px;text-align:center"><div style="font-size:9px;color:var(--mut);font-family:'Courier New',monospace">Lower</div><div style="font-size:12px;font-family:'Courier New',monospace;color:var(--red)" id="a-bbl">-</div></div>
      <div style="flex:1;background:var(--bg3);border:1px solid var(--brd);border-radius:6px;padding:8px;text-align:center"><div style="font-size:9px;color:var(--mut);font-family:'Courier New',monospace">Mid</div><div style="font-size:12px;font-family:'Courier New',monospace;color:var(--ylw)" id="a-bbm">-</div></div>
      <div style="flex:1;background:var(--bg3);border:1px solid var(--brd);border-radius:6px;padding:8px;text-align:center"><div style="font-size:9px;color:var(--mut);font-family:'Courier New',monospace">Upper</div><div style="font-size:12px;font-family:'Courier New',monospace;color:var(--grn)" id="a-bbu">-</div></div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">Volume</div>
    <div style="display:flex;justify-content:space-between;font-size:11px;font-family:'Courier New',monospace;margin-bottom:6px"><span style="color:var(--mut)">Ratio vs MA</span><span id="a-vol" class="blu">-</span></div>
    <div class="vol-bar"><div class="vol-fill" id="a-volb" style="width:0%"></div></div>
    <div style="display:flex;justify-content:space-between;margin-top:4px;font-size:9px;color:var(--mut);font-family:'Courier New',monospace"><span>0x</span><span style="color:var(--ylw)">0.7x</span><span style="color:var(--grn)">1.5x</span></div>
  </div>
  <div class="card">
    <div class="card-title">HTF 4H Context</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
      <div style="background:var(--bg3);border:1px solid var(--brd);border-radius:8px;padding:10px;text-align:center"><div style="font-size:9px;color:var(--mut);font-family:'Courier New',monospace;margin-bottom:6px">TREND</div><span class="badge b-neut" id="a-htf">-</span></div>
      <div style="background:var(--bg3);border:1px solid var(--brd);border-radius:8px;padding:10px;text-align:center"><div style="font-size:9px;color:var(--mut);font-family:'Courier New',monospace;margin-bottom:6px">EMA 1H</div><span class="badge b-neut" id="a-ema-trend">-</span></div>
      <div style="background:var(--bg3);border:1px solid var(--brd);border-radius:8px;padding:10px;text-align:center"><div style="font-size:9px;color:var(--mut);font-family:'Courier New',monospace;margin-bottom:6px">MACD</div><span class="badge b-neut" id="a-macd-htf">-</span></div>
      <div style="background:var(--bg3);border:1px solid var(--brd);border-radius:8px;padding:10px;text-align:center"><div style="font-size:9px;color:var(--mut);font-family:'Courier New',monospace;margin-bottom:6px">F&amp;G</div><span class="badge b-neut" id="a-fg-badge">-</span></div>
    </div>
  </div>
</div>

<!-- POSISI -->
<div class="page" id="p-posisi">
  <div class="sec">Posisi Aktif</div>
  <div class="card">
    <div class="pos-hdr">
      <span class="side-badge sb-none" id="p-side">TIDAK ADA</span>
      <span style="font-size:12px;color:var(--mut);font-family:'Courier New',monospace" id="p-sym">-</span>
    </div>
    <div class="pos-grid">
      <div><div class="plabel">Entry</div><div class="pval" id="p-entry">-</div></div>
      <div><div class="plabel">Harga</div><div class="pval" id="p-price">-</div></div>
      <div><div class="plabel">Stop Loss</div><div class="pval red" id="p-sl">-</div></div>
      <div><div class="plabel">Take Profit</div><div class="pval grn" id="p-tp">-</div></div>
    </div>
    <div id="p-bar-wrap" style="display:none;margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--mut);font-family:'Courier New',monospace;margin-bottom:4px">
        <span id="p-bar-sl">SL</span><span style="color:var(--ylw)">PRICE</span><span id="p-bar-tp">TP</span>
      </div>
      <div class="bar-track" style="height:6px"><div class="bar-fill" id="p-bar-fill" style="background:linear-gradient(90deg,var(--red),var(--grn));width:50%"></div></div>
    </div>
    <div id="p-trail-wrap" style="display:none">
      <div style="background:var(--bg3);border:1px solid var(--brd);border-radius:8px;padding:12px;margin-bottom:10px">
        <div style="font-size:9px;color:var(--mut);text-transform:uppercase;letter-spacing:1.5px;font-family:'Courier New',monospace;margin-bottom:8px">Trailing Stop</div>
        <div style="display:flex;justify-content:space-between;font-size:11px;font-family:'Courier New',monospace;margin-bottom:6px"><span id="p-trail-status" style="color:var(--mut)">Menunggu 50% TP</span><span class="ylw" id="p-trail-mult"></span></div>
        <div class="bar-track"><div class="bar-fill" id="p-trail-fill" style="background:linear-gradient(90deg,var(--ylw),var(--grn));width:0%"></div></div>
        <div style="display:flex;justify-content:space-between;margin-top:4px;font-size:9px;color:var(--mut);font-family:'Courier New',monospace"><span>0%</span><span id="p-trail-pct">0%</span><span>100%</span></div>
      </div>
    </div>
    <div id="p-upnl-wrap" style="display:none">
      <div class="row"><span class="rk">Unrealized PnL</span><span id="p-upnl">-</span></div>
      <div class="row"><span class="rk">Liquidation</span><span class="red" id="p-liq">-</span></div>
    </div>
    <button id="p-close-btn" onclick="confirmClose()" class="btn-close" style="display:none">CLOSE POSITION</button>
  </div>
  <div class="sec">Riwayat Trade</div>
  <div class="card" style="overflow:hidden;padding:0">
    <table class="trade-table">
      <thead><tr><th style="padding:10px 8px">Tanggal</th><th>Side</th><th style="text-align:right">Entry</th><th style="text-align:right">Exit</th><th style="text-align:right">PnL</th><th style="text-align:center">Hasil</th></tr></thead>
      <tbody id="trade-body"><tr><td colspan="6" style="padding:16px;text-align:center;color:var(--mut)">Belum ada trade</td></tr></tbody>
    </table>
  </div>
</div>

<!-- PERFORMA -->
<div class="page" id="p-performa">
  <div class="sec">Statistik</div>
  <div class="card">
    <div class="row"><span class="rk">Total Trade</span><span id="pf-total">-</span></div>
    <div class="row"><span class="rk">Win Rate</span><span id="pf-wr">-</span></div>
    <div class="row"><span class="rk">Avg Win</span><span class="grn" id="pf-aw">-</span></div>
    <div class="row"><span class="rk">Avg Loss</span><span class="red" id="pf-al">-</span></div>
    <div class="row"><span class="rk">R:R Aktual</span><span id="pf-rr">-</span></div>
    <div class="row"><span class="rk">Expectancy</span><span id="pf-exp">-</span></div>
  </div>
  <div class="sec">Long vs Short</div>
  <div class="card">
    <div style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;font-size:11px;font-family:'Courier New',monospace;margin-bottom:4px"><span id="pf-ll" style="color:var(--mut)">LONG 0T</span><span class="grn" id="pf-lwr">-</span></div>
      <div class="bar-track"><div class="bar-fill" id="pf-lb" style="background:var(--grn);width:0%"></div></div>
    </div>
    <div>
      <div style="display:flex;justify-content:space-between;font-size:11px;font-family:'Courier New',monospace;margin-bottom:4px"><span id="pf-sl" style="color:var(--mut)">SHORT 0T</span><span class="red" id="pf-swr">-</span></div>
      <div class="bar-track"><div class="bar-fill" id="pf-sb" style="background:var(--red);width:0%"></div></div>
    </div>
  </div>
  <div class="sec">Tren Terkini</div>
  <div class="card">
    <div class="row"><span class="rk">Streak</span><span id="pf-streak">-</span></div>
    <div class="row"><span class="rk">5 Trade Terakhir</span><span id="pf-l5" style="letter-spacing:4px">-</span></div>
  </div>
  <div class="sec">Break Even Progress</div>
  <div class="card">
    <div style="display:flex;justify-content:space-between;font-size:11px;font-family:'Courier New',monospace;margin-bottom:4px">
      <span style="color:var(--mut)">Avg win <span id="pf-awn" class="grn">$0</span> menuju <span id="pf-awt" class="ylw">$0</span></span>
      <span class="ylw" id="pf-bep">-</span>
    </div>
    <div class="bar-track"><div class="bar-fill" id="pf-beb" style="background:linear-gradient(90deg,var(--red),var(--ylw),var(--grn));width:0%"></div></div>
  </div>
  <div class="sec">Equity Curve</div>
  <div class="card" style="padding:0;overflow:hidden"><svg id="eqChart" width="100%" height="120" style="display:block"></svg></div>
</div>

<!-- LOG -->
<div class="page" id="p-log">
  <div class="sec">Log Terbaru</div>
  <div class="log-box" id="log-box">Memuat...</div>
</div>

<!-- Modal Close -->
<div class="modal" id="modal">
  <div class="modal-box">
    <div style="font-size:28px;margin-bottom:12px">⚠️</div>
    <div style="font-size:11px;color:var(--mut);font-family:'Courier New',monospace;margin-bottom:8px">KONFIRMASI CLOSE</div>
    <div style="font-size:16px;font-weight:700;margin-bottom:4px" id="m-side">-</div>
    <div style="font-size:12px;color:var(--mut);font-family:'Courier New',monospace;margin-bottom:16px" id="m-pnl">-</div>
    <input id="m-pin" type="password" maxlength="6" placeholder="Masukkan PIN"
      style="width:100%;padding:11px;background:var(--bg);border:1px solid var(--brd);border-radius:8px;color:var(--txt);font-family:'Courier New',monospace;font-size:16px;text-align:center;letter-spacing:6px;outline:none;margin-bottom:8px">
    <div id="m-err" style="color:var(--red);font-size:11px;display:none;margin-bottom:8px">PIN salah!</div>
    <div class="modal-btns">
      <button class="mbtn ok" onclick="doClose()">Ya, Close</button>
      <button class="mbtn cancel" onclick="closeModal()">Batal</button>
    </div>
  </div>
</div>

<div class="ts">Auto-refresh 10s | Live 15s | <span id="ts-upd">-</span></div>

<script>
// ── State ────────────────────────────────────────────────────────────────────
var macdHist = [], scanMode = false, selPair = null, scanPairs = [], closingPos = null;

// ── Helpers ──────────────────────────────────────────────────────────────────
function $(id){ return document.getElementById(id); }
function fmt(n, d){ d = d||2; return n != null ? '$'+Number(n).toLocaleString('en',{minimumFractionDigits:d,maximumFractionDigits:d}) : '-'; }
function badgeCls(v){ return v==='BULLISH'?'badge b-bull':v==='BEARISH'?'badge b-bear':'badge b-neut'; }
function cls(el, v){ if(el) el.className = v; }
function txt(id, v){ var e=$(id); if(e) e.textContent = v; }

function tab(name, idx){
  ['ringkasan','analisa','posisi','performa','log'].forEach(function(n,i){
    document.querySelectorAll('.tab')[i].classList.toggle('active', i===idx);
    $('p-'+n).classList.toggle('active', n===name);
  });
}

// ── Equity chart (pure SVG, no external lib) ─────────────────────────────────
function updateEquity(pts, bal){
  var svg = $('eqChart'); if(!svg) return;
  var data = [122.0].concat(pts||[]);
  if(bal != null) data.push(bal);
  if(data.length < 2){ svg.innerHTML=''; return; }
  var W=svg.clientWidth||320, H=120, pad=28, bot=16;
  var mn=Math.min.apply(null,data), mx=Math.max.apply(null,data);
  var rng=mx-mn||1;
  var col=data[data.length-1]>=122.0?'#00e676':'#ff3d57';
  var xS=function(i){return pad+(i/(data.length-1))*(W-pad*2);};
  var yS=function(v){return bot+(1-(v-mn)/rng)*(H-bot*2);};
  var pts2=data.map(function(v,i){return xS(i)+','+yS(v);}).join(' ');
  var area='M '+xS(0)+','+H+' L '+data.map(function(v,i){return xS(i)+','+yS(v);}).join(' L ')+' L '+xS(data.length-1)+','+H+' Z';
  var yLbls=['',mx.toFixed(0),((mx+mn)/2).toFixed(0),mn.toFixed(0)].map(function(v,i){
    if(!v) return '';
    var y=bot+(i/3)*(H-bot*2);
    return '<text x="'+(pad-4)+'" y="'+y+'" fill="#586069" font-size="8" text-anchor="end" dominant-baseline="middle">$'+v+'</text>';
  }).join('');
  svg.innerHTML='<defs><linearGradient id="eq-g" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="'+col+'" stop-opacity="0.25"/><stop offset="100%" stop-color="'+col+'" stop-opacity="0"/></linearGradient></defs>'
    +'<path d="'+area+'" fill="url(#eq-g)"/>'
    +'<polyline points="'+pts2+'" fill="none" stroke="'+col+'" stroke-width="1.5" stroke-linejoin="round"/>'
    +yLbls;
}

// ── MACD bars ─────────────────────────────────────────────────────────────────
function pushMacd(h){
  if(h != null) macdHist.push(h);
  if(macdHist.length > 14) macdHist = macdHist.slice(-14);
  var c = $('a-macd-bars'); if(!c || !macdHist.length) return;
  var mx = Math.max.apply(null, macdHist.map(Math.abs).concat([0.01]));
  c.innerHTML = macdHist.map(function(v){
    return '<div class="mb '+(v>=0?'p':'n')+'" style="height:'+Math.max(2,Math.abs(v)/mx*45)+'px"></div>';
  }).join('');
}

// ── Update indicators display ─────────────────────────────────────────────────
function showInd(ind, sig, htf, fg, fgLbl, symLbl){
  if(symLbl) txt('pair-sym', symLbl);
  // Signal score
  var sm = sig && sig.reason ? sig.reason.match(/L:(\d+) S:(\d+)/) : null;
  txt('a-ls', sm ? sm[1] : '-');
  txt('a-ss', sm ? sm[2] : '-');
  var sr = $('a-sig');
  if(sr){
    if(sig && sig.action==='LONG'){sr.textContent='LONG '+(sig.reason||'');sr.className='sig-result b-bull';}
    else if(sig && sig.action==='SHORT'){sr.textContent='SHORT '+(sig.reason||'');sr.className='sig-result b-bear';}
    else{sr.textContent='WAIT'+(sig&&sig.reason?' - '+sig.reason:'');sr.className='sig-result b-wait';}
  }
  // EMA
  if(ind.ema9 && ind.ema21 && ind.ema55){
    var mn = Math.min(ind.ema9,ind.ema21,ind.ema55)*0.999;
    var mx = Math.max(ind.ema9,ind.ema21,ind.ema55)*1.001;
    var pct = function(v){ return Math.max(5,Math.min(95,(v-mn)/(mx-mn)*100)); };
    txt('a-e9',  ind.ema9.toFixed(2));  cls($('a-e9'),  ind.ema_trend==='BEARISH'?'red':'grn');
    $('a-e9b').style.width  = pct(ind.ema9)+'%';
    txt('a-e21', ind.ema21.toFixed(2)); $('a-e21b').style.width = pct(ind.ema21)+'%';
    txt('a-e55', ind.ema55.toFixed(2)); $('a-e55b').style.width = pct(ind.ema55)+'%';
  }
  var eb = $('a-etbadge'); if(eb){eb.textContent=ind.ema_trend||'-'; eb.className=badgeCls(ind.ema_trend);}
  // RSI
  if(ind.rsi){
    txt('a-rsi', ind.rsi.toFixed(1));
    cls($('a-rsi'), ind.rsi<30?'red':ind.rsi>70?'ylw':'grn');
    txt('a-rsi-zone', ind.rsi<30?'OVERSOLD':ind.rsi>70?'OVERBOUGHT':'NEUTRAL ZONE');
    cls($('a-rsi-zone'), ind.rsi<30?'red':ind.rsi>70?'ylw':'grn');
    $('a-rsi-ptr').style.left = ind.rsi+'%';
  }
  // MACD
  if(ind.macd != null){
    var mv=ind.macd, hv=ind.macd_hist||0;
    txt('a-macd', mv.toFixed(3)); cls($('a-macd'), mv>=0?'grn':'red');
    txt('a-hist', (hv>=0?'+':'')+hv.toFixed(3)); cls($('a-hist'), hv>=0?'grn':'red');
    var ms = mv>=0&&hv>=0?'BULLISH':mv<0&&hv<0?'BEARISH':'MIXED';
    txt('a-macd-sig', ms); cls($('a-macd-sig'), ms==='BULLISH'?'grn':ms==='BEARISH'?'red':'ylw');
    pushMacd(hv);
    var mb = $('a-macd-htf'); if(mb){mb.textContent=mv.toFixed(2);mb.className=mv<-0.3?'badge b-bear':mv>0.3?'badge b-bull':'badge b-neut';}
  }
  // BB
  if(ind.bb_lower){
    txt('a-bbl', ind.bb_lower.toFixed(2));
    txt('a-bbm', ind.bb_mid.toFixed(2));
    txt('a-bbu', ind.bb_upper.toFixed(2));
    var sq = ind.squeeze || ind.bb_squeeze;
    txt('a-sq-icon', sq?'🔥':'✅');
    txt('a-sq-title', sq?'Squeeze AKTIF':'Tidak Ada Squeeze');
    cls($('a-sq-title'), sq?'ylw':'grn');
    txt('a-sq-sub', sq?'Volatilitas rendah — breakout segera':'Harga bergerak bebas');
  }
  // Volume
  if(ind.vol_ratio != null){
    var vr = ind.vol_ratio;
    txt('a-vol', vr.toFixed(2)+'x - '+(ind.vol_status||'-'));
    cls($('a-vol'), vr>=1.5?'grn':vr>=0.7?'blu':'ylw');
    $('a-volb').style.width = Math.min(vr/2*100,100)+'%';
  }
  // HTF badges
  var htb = $('a-htf'); if(htb){htb.textContent=htf||'-';htb.className=badgeCls(htf);}
  var etb = $('a-ema-trend'); if(etb){etb.textContent=ind.ema_trend||'-';etb.className=badgeCls(ind.ema_trend);}
  var fb = $('a-fg-badge');
  if(fb && fg!=null){fb.textContent=fg+' '+(fgLbl||'');fb.className=fg<35?'badge b-bear':fg<50?'badge b-neut':'badge b-bull';}
}

// ── Pair scanner cards ────────────────────────────────────────────────────────
function selectPair(sym){
  selPair = sym;
  document.querySelectorAll('.pair-card').forEach(function(c){
    c.classList.toggle('active', c.dataset.sym === sym);
  });
  var p = scanPairs.find(function(x){ return x.symbol===sym; });
  if(!p || p.error) return;
  var ind = {
    ema9:p.ema9, ema21:p.ema21, ema55:p.ema55, ema_trend:p.ema_trend,
    rsi:p.rsi, macd:p.macd, macd_hist:p.macd_hist,
    bb_lower:p.bb_lower, bb_mid:p.bb_mid, bb_upper:p.bb_upper, squeeze:p.squeeze,
    vol_ratio:p.vol_ratio, vol_status:p.vol_status,
  };
  showInd(ind, {action:p.signal,strength:p.strength,reason:p.reason}, p.htf, null, null, p.symbol);
}

async function loadPairs(){
  try{
    var d = await (await fetch('/api/scan_pairs')).json();
    scanPairs = d.pairs || [];
    var tse = $('scan-ts');
    if(tse) tse.textContent = d.cached ? '(cache)' : new Date().toLocaleTimeString('id-ID');
    var container = $('pair-cards'); if(!container) return;
    if(!scanPairs.length){
      container.innerHTML = '<div style="color:var(--mut);font-size:11px;font-family:monospace;padding:8px">Tidak ada sinyal</div>';
      return;
    }
    container.innerHTML = scanPairs.map(function(p){
      if(p.error) return '<div class="pair-card" data-sym="'+p.symbol+'"><div class="pc-sym">'+p.symbol.replace('USDT','')+'</div><div class="pc-sig" style="color:var(--red)">ERR</div></div>';
      var sc = p.signal==='LONG'?'var(--grn)':p.signal==='SHORT'?'var(--red)':'var(--mut)';
      var htfc = p.htf==='BULLISH'?'var(--grn)':p.htf==='BEARISH'?'var(--red)':'var(--ylw)';
      var rsic = p.rsi<30?'var(--red)':p.rsi>70?'var(--ylw)':'var(--mut)';
      var sc2 = p.signal==='LONG'?' sl':p.signal==='SHORT'?' ss':'';
      var ac = selPair===p.symbol?' active':'';
      return '<div class="pair-card'+sc2+ac+'" data-sym="'+p.symbol+'" onclick="selectPair(this.dataset.sym)">'
        +'<div class="pc-sym">'+p.symbol.replace('USDT','')+'</div>'
        +'<div class="pc-sig" style="color:'+sc+'">'+p.signal+'</div>'
        +'<div class="pc-bar"><div class="pc-fill" style="background:'+sc+';width:'+Math.round((p.strength||0)*100)+'%"></div></div>'
        +'<div class="pc-meta" style="color:'+sc+';font-size:10px;font-weight:700">'+Math.round((p.strength||0)*100)+'%</div>'
        +'<div class="pc-meta" style="color:'+rsic+'">RSI '+p.rsi+'</div>'
        +'<div class="pc-meta" style="color:'+htfc+'">'+p.htf+'</div>'
        +'</div>';
    }).join('');
    if(!selPair && scanPairs.length) selectPair(scanPairs[0].symbol);
    else if(selPair){ var found=scanPairs.find(function(x){return x.symbol===selPair;}); if(found) selectPair(selPair); }
  }catch(e){}
}

// ── Live data (balance / position / price) ────────────────────────────────────
async function refreshLive(){
  try{
    var lv = await (await fetch('/api/live')).json();
    if(lv.balance != null) txt('s-bal', fmt(lv.balance));
    txt('s-price', lv.price ? fmt(lv.price) : '-');
    var upnl = lv.upnl||0;
    var ue = $('s-upnl'); if(ue){ue.textContent=(upnl>=0?'+':'')+fmt(upnl);ue.className='sval '+(upnl>0?'grn':upnl<0?'red':'');}
    txt('s-liq', lv.liq ? 'Liq: '+fmt(lv.liq) : 'Liq: -');
    // Update posisi page with live data
    var lp = lv.live_pos;
    if(lp){
      var sb = $('p-side');
      if(sb){sb.textContent=lp.side;sb.className='side-badge '+(lp.side==='LONG'?'sb-long':'sb-short');}
      txt('p-sym',   lp.symbol||'-');
      txt('p-entry', fmt(lp.entry));
      cls($('p-entry'), 'pval '+(lp.side==='LONG'?'grn':'red'));
      if(lv.price) txt('p-price', fmt(lv.price));
      if(lp.upnl != null){
        $('p-upnl-wrap').style.display='block';
        var upe=$('p-upnl');if(upe){upe.textContent=(lp.upnl>=0?'+':'')+fmt(lp.upnl);upe.className=lp.upnl>=0?'grn':'red';}
        txt('p-liq', lp.liq ? fmt(lp.liq) : '-');
      }
      txt('s-posisi', lp.side+' @ '+fmt(lp.entry));
      cls($('s-posisi'), lp.side==='LONG'?'grn':'red');
      $('p-close-btn').style.display='block';
      closingPos = lp;
    }else{
      var sb2=$('p-side');if(sb2){sb2.textContent='TIDAK ADA';sb2.className='side-badge sb-none';}
      txt('s-posisi','Tidak Ada');cls($('s-posisi'),'');
      $('p-close-btn').style.display='none';
      $('p-upnl-wrap').style.display='none';
      closingPos=null;
    }
  }catch(e){}
}

// ── Main status refresh ───────────────────────────────────────────────────────
async function refresh(){
  try{
    var d = await (await fetch('/api/status')).json();
    var dot=$('dot'), stxt=$('stxt');
    if(dot) dot.className='dot '+(d.running?'on':'off');
    txt('stxt', d.running?'RUNNING':'STOPPED');
    // Balance from logs (fallback until live loads)
    if(d.balance != null && $('s-bal').textContent==='-') txt('s-bal', fmt(d.balance));
    var pnl = d.total_pnl||0;
    var pe=$('s-pnl');if(pe){pe.textContent=(pnl>=0?'+':'')+fmt(Math.abs(pnl));pe.className='sval '+(pnl>0?'grn':pnl<0?'red':'');}
    txt('s-strat', d.strategy ? d.strategy.replace(/_/g,' ').toUpperCase() : '-');
    scanMode = d.scanner_mode||false;
    var symLabel = scanMode ? 'SCANNER ('+((d.scan_symbols||[]).length)+'P)' : (d.symbol||'-');
    txt('s-sym', symLabel+' · '+(d.timeframe||'-'));
    // Fear & Greed
    var fg=d.fg_value, fgLbl=d.fg_label||'';
    var fge=$('s-fg');
    if(fge && fg!=null){fge.textContent=fg+' ('+fgLbl+')';fge.className=fg<35?'red':fg<50?'ylw':'grn';}
    // HTF
    var htf=d.htf||'?';
    var he=$('s-htf');if(he){he.textContent=htf;he.className=htf==='BULLISH'?'grn':htf==='BEARISH'?'red':'ylw';}
    // Signal terkuat
    var sig=d.signal,se=$('s-signal');
    if(se&&sig&&sig.action&&sig.action!=='WAIT'){
      var sym=sig.symbol?sig.symbol.replace('USDT','')+' ':''
      se.textContent=sym+sig.action+' '+Math.round((sig.strength||0)*100)+'%';
      se.className=sig.action==='LONG'?'grn':'red';
    }else if(se){se.textContent='WAIT';se.className='';}
    // Log position
    var lp=d.log_pos;
    if(lp && !closingPos){
      txt('p-sym',  '(log) '+lp.side);
      txt('p-sl',   lp.sl ? fmt(lp.sl) : '-');
      txt('p-tp',   lp.tp ? fmt(lp.tp) : '-');
      // SL/TP bar
      if(lp.sl && lp.tp){
        $('p-bar-wrap').style.display='block';
        txt('p-bar-sl','SL '+fmt(lp.sl,1));
        txt('p-bar-tp','TP '+fmt(lp.tp,1));
      }
      $('p-trail-wrap').style.display='block';
    }
    // Perf
    var pf=d.perf||{},wr=pf.win_rate||0;
    txt('s-total', (pf.total||0)+' trade');
    var sw=$('s-wr');if(sw){sw.textContent=wr+'% ('+(pf.wins||0)+'W '+(pf.losses||0)+'L)';sw.className=wr>=45?'grn':wr>=35?'ylw':'red';}
    var sr=$('s-rr');if(sr){sr.textContent=(pf.rr||0).toFixed(2);sr.className=(pf.rr||0)>=1?'grn':(pf.rr||0)>=0.7?'ylw':'red';}
    var st=pf.streak||0,stype=pf.streak_type||'NONE';
    var sse=$('s-streak');
    if(sse){if(st>0&&stype!=='NONE'){sse.textContent=st+' '+(stype==='WIN'?'Win':'Loss')+' berturut';sse.className=stype==='WIN'?'grn':'red';}else{sse.textContent='-';sse.className='';}}
    txt('s-ca', d.claude_approve||0);
    txt('s-cs', d.claude_skip||0);
    // Performa page
    txt('pf-total',(pf.total||0)+' trade');
    var pw=$('pf-wr');if(pw){pw.textContent=wr+'% ('+(pf.wins||0)+'W '+(pf.losses||0)+'L)';pw.className=wr>=45?'grn':wr>=35?'ylw':'red';}
    var aw=pf.avg_win||0,al=pf.avg_loss||0;
    txt('pf-aw','+'+(aw||0).toFixed(2));
    txt('pf-al','-'+(al||0).toFixed(2));
    var prr=$('pf-rr');if(prr){prr.textContent=(pf.rr||0).toFixed(2);prr.className=(pf.rr||0)>=1?'grn':(pf.rr||0)>=0.7?'ylw':'red';}
    var exp=(aw*wr/100)-(al*(100-wr)/100);
    var ee=$('pf-exp');if(ee){ee.textContent=(exp>=0?'+':'')+exp.toFixed(3);ee.className=exp>=0?'grn':'red';}
    txt('pf-ll','LONG '+(pf.long_total||0)+'T');txt('pf-lwr',(pf.long_wr||0)+'%');$('pf-lb').style.width=(pf.long_wr||0)+'%';
    txt('pf-sl','SHORT '+(pf.short_total||0)+'T');txt('pf-swr',(pf.short_wr||0)+'%');$('pf-sb').style.width=(pf.short_wr||0)+'%';
    var se2=$('pf-streak');
    if(se2){if(st>0&&stype!=='NONE'){se2.textContent=st+' '+(stype==='WIN'?'Win':'Loss')+' berturut';se2.className=stype==='WIN'?'grn':'red';}else{se2.textContent='-';se2.className='';}}
    txt('pf-l5',(pf.last5||[]).join(' ')||'-');
    var bp=pf.be_progress||0;
    txt('pf-bep',bp.toFixed(1)+'%');$('pf-beb').style.width=Math.min(bp,100)+'%';
    txt('pf-awn','$'+(aw||0).toFixed(2));txt('pf-awt','$'+(pf.target_avg_win||0).toFixed(2));
    updateEquity(pf.equity, d.balance);
    // Analisa
    $('pair-selector').style.display = scanMode ? 'block' : 'none';
    if(!scanMode) showInd(d.ind||{}, d.signal||{}, htf, fg, fgLbl, d.symbol);
    // Log
    if(d.logs && d.logs.length){
      var lb=$('log-box');
      lb.innerHTML=d.logs.map(function(l){
        var c='';
        if(l.includes('ERROR')||l.includes('STOP_LOSS'))c='e';
        else if(l.includes('WARNING'))c='w';
        else if(l.includes('TAKE_PROFIT')||l.includes('Full size')||l.includes('Medium size'))c='s';
        else if(l.includes('DEBUG')||l.includes('WAIT'))c='d';
        return '<div class="ll '+c+'">'+l.replace(/</g,'&lt;')+'</div>';
      }).join('');
      lb.scrollTop=lb.scrollHeight;
    }
    txt('ts-upd', new Date().toLocaleTimeString('id-ID'));
  }catch(e){
    var dot=$('dot');if(dot)dot.className='dot off';
    txt('stxt','ERROR');
  }
}

// ── Trade history ─────────────────────────────────────────────────────────────
async function loadTrades(){
  try{
    var d = await (await fetch('/api/trades')).json();
    var tb = $('trade-body'); if(!tb) return;
    if(!d.trades||!d.trades.length){
      tb.innerHTML='<tr><td colspan="6" style="padding:16px;text-align:center;color:var(--mut)">Belum ada trade</td></tr>';
      return;
    }
    tb.innerHTML = d.trades.slice().reverse().slice(0,15).map(function(t){
      var pv=parseFloat(t.pnl)||0;
      var pc=pv>0?'var(--grn)':'var(--red)';
      var sc=t.side==='LONG'?'var(--grn)':'var(--red)';
      var rs=t.reason==='TAKE_PROFIT'?'TP':'SL';
      var dt=t.date?t.date.substring(5,16):'-';
      return '<tr>'
        +'<td style="color:var(--mut);font-size:10px">'+dt+'</td>'
        +'<td style="color:'+sc+';font-weight:700">'+t.side+'</td>'
        +'<td style="text-align:right">$'+parseFloat(t.entry).toFixed(2)+'</td>'
        +'<td style="text-align:right">$'+parseFloat(t.exit).toFixed(2)+'</td>'
        +'<td style="text-align:right;color:'+pc+';font-weight:700">'+(pv>=0?'+':'')+fmt(Math.abs(pv))+'</td>'
        +'<td style="text-align:center;color:var(--mut)">'+rs+'</td>'
        +'</tr>';
    }).join('');
  }catch(e){}
}

// ── Close position ────────────────────────────────────────────────────────────
function confirmClose(){
  if(!closingPos) return;
  txt('m-side', closingPos.side+' @ '+fmt(closingPos.entry));
  txt('m-pnl', 'uPnL: '+(closingPos.upnl>=0?'+':'')+fmt(closingPos.upnl));
  $('modal').style.display='flex';
  $('m-pin').value='';
  $('m-err').style.display='none';
  setTimeout(function(){$('m-pin').focus();}, 100);
}
function closeModal(){ $('modal').style.display='none'; }
async function doClose(){
  var pin=$('m-pin').value;
  if(!pin){$('m-err').style.display='block';txt('m-err','Masukkan PIN!');return;}
  try{
    var r=await fetch('/api/close_position',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin:pin})});
    var d=await r.json();
    if(d.ok){closeModal();alert(d.message);refreshLive();}
    else{$('m-err').style.display='block';txt('m-err',d.error||'Gagal!');}
  }catch(e){alert('Error: '+e.message);}
}

// ── Boot ──────────────────────────────────────────────────────────────────────
refresh();
refreshLive();
loadTrades();
setInterval(refresh,     10000);
setInterval(refreshLive, 15000);
setInterval(loadTrades,  30000);
setInterval(function(){ if(scanMode) loadPairs(); }, 90000);
</script>
</body>
</html>"""


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    from flask import make_response
    resp = make_response(render_template_string(HTML))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/api/status")
def api_status():
    try:
        logs   = read_logs()
        state  = extract_state(logs)
        trades = parse_trades()
        perf   = calc_perf(trades)
        from config import config
        return jsonify({
            **state,
            "total_pnl":    round(sum(float(t["pnl"]) for t in trades), 2),
            "perf":         perf,
            "strategy":     getattr(config.trading, "strategy", "trend_following"),
            "symbol":       config.trading.symbol,
            "scan_symbols": config.trading.scan_symbols,
            "scanner_mode": bool(config.trading.scan_symbols),
            "timeframe":    config.trading.timeframe,
        })
    except Exception as e:
        return jsonify({"error": str(e), "running": False})


@app.route("/api/live")
def api_live():
    try:
        return jsonify(get_live_data())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/trades")
def api_trades():
    try:
        return jsonify({"trades": parse_trades()})
    except Exception as e:
        return jsonify({"trades": [], "error": str(e)})


@app.route("/api/scan_pairs")
def api_scan_pairs():
    global _scan_cache
    now = time.time()
    if now - _scan_cache["ts"] < 90 and _scan_cache["data"]:
        return jsonify({"pairs": _scan_cache["data"], "cached": True})
    try:
        from config import config
        from core.indicators import IndicatorEngine
        from strategies import get_strategy
        syms     = config.trading.scan_symbols or [config.trading.symbol]
        client   = get_client()
        if not client or not client.is_connected():
            return jsonify({"pairs": [], "error": "Client tidak tersedia"})
        eng      = IndicatorEngine()
        strategy = get_strategy(config.trading.strategy)
        pairs    = []
        for sym in syms:
            try:
                df = client.get_klines(sym, config.trading.timeframe, 200)
                if df is None or len(df) < 60:
                    continue
                df  = df.iloc[:-1]
                ind = eng.calculate(df)
                if ind is None:
                    continue
                sig = strategy.generate_signal(ind)
                htf = "NEUTRAL"
                try:
                    df4 = client.get_klines(sym, "4h", 100)
                    if df4 is not None:
                        i4 = eng.calculate(df4.iloc[:-1])
                        if i4:
                            e4 = i4.ema_trend
                            m4 = getattr(i4, "macd_line", 0)
                            h4 = getattr(i4, "macd_hist", 0)
                            if e4 == "BEARISH":             htf = "BEARISH"
                            elif e4 == "BULLISH":           htf = "BULLISH"
                            elif m4 < -0.3 and h4 < -0.05: htf = "BEARISH"
                            elif m4 >  0.3 and h4 >  0.05: htf = "BULLISH"
                except Exception:
                    pass
                vr = getattr(ind, "volume_ratio", 1.0)
                pairs.append({
                    "symbol":    sym,
                    "price":     round(ind.close, 4),
                    "rsi":       round(ind.rsi, 1),
                    "ema_trend": ind.ema_trend,
                    "ema9":      round(ind.ema_9,  4),
                    "ema21":     round(ind.ema_21, 4),
                    "ema55":     round(ind.ema_55, 4),
                    "htf":       htf,
                    "signal":    sig.action,
                    "strength":  round(sig.strength, 2),
                    "reason":    sig.reason or "",
                    "macd":      round(getattr(ind, "macd_line", 0), 4),
                    "macd_hist": round(getattr(ind, "macd_hist",  0), 4),
                    "vol_ratio": round(vr, 2),
                    "vol_status":"HIGH" if vr >= 1.5 else "NORMAL" if vr >= 0.7 else "LOW",
                    "bb_lower":  round(ind.bb_lower,  4),
                    "bb_mid":    round(ind.bb_middle, 4),
                    "bb_upper":  round(ind.bb_upper,  4),
                    "squeeze":   bool(ind.bb_squeeze),
                })
            except Exception as ex:
                pairs.append({"symbol": sym, "error": str(ex)})
        pairs.sort(key=lambda x: (0 if x.get("signal") in ("LONG", "SHORT") else 1,
                                  -x.get("strength", 0)))
        _scan_cache = {"ts": now, "data": pairs}
        return jsonify({"pairs": pairs, "cached": False})
    except Exception as e:
        return jsonify({"pairs": [], "error": str(e)})


@app.route("/api/close_position", methods=["POST"])
def api_close_position():
    try:
        data = request.get_json()
        if not data or data.get("pin") != CLOSE_PIN:
            return jsonify({"ok": False, "error": "PIN salah"})
        client = get_client()
        if not client:
            return jsonify({"ok": False, "error": "Client tidak tersedia"})
        from config import config
        syms = config.trading.scan_symbols or [config.trading.symbol]
        for sym in syms:
            try:
                pos = client.get_open_positions(sym)
                if not pos:
                    continue
                amt = float(pos[0].get("positionAmt", 0))
                if amt == 0:
                    continue
                side = "SELL" if amt > 0 else "BUY"
                r    = client.place_market_order(sym, side, abs(amt))
                if r:
                    return jsonify({"ok": True, "message": "Posisi "+sym+" ditutup"})
            except Exception:
                continue
        return jsonify({"ok": False, "error": "Tidak ada posisi aktif"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
