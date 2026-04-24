"""
=======================================================
  CRYPTO FUTURES SCANNER v5.0 — 100% FREE
  TOP-DOWN CASCADE: 4H → 1H → 30m → 15m → 5m
  ENTRY: Sirf 5m candlestick pattern confirm hone par
  SINGLE SIGNAL PER COIN — No duplicate TF spam
=======================================================
CHALANE KA TARIKA:
  py -3 crypto_scanner_v5.py

ZAROORI: dono files ek hi folder mein:
  v5_engine.py
  crypto_scanner_v5.py

FILES JO BANEGI:
  v5_signals_log.csv   — har signal ka record
  v5_sent.json         — duplicate filter
"""

import time, json, csv, os
from datetime import datetime
from v5_engine import (
    get_futures_symbols, get_top_volume, get_top_gainers,
    get_funding_rate, get_open_interest, analyze_cascade,
    SCORE_A, SCORE_B, SCORE_C
)

# ─── SETTINGS ─────────────────────────────────────────────
TOP_COINS   = 50
BLOCK_HOURS = 4
LOG_FILE    = "v5_signals_log.csv"
SENT_FILE   = "v5_sent.json"

# ─── DUPLICATE FILTER ─────────────────────────────────────
def load_sent():
    if os.path.exists(SENT_FILE):
        try:
            with open(SENT_FILE,"r") as f: return json.load(f)
        except: pass
    return {}

def save_sent(d):
    with open(SENT_FILE,"w") as f: json.dump(d,f,indent=2)

def is_dup(sent, sym, direction):
    key = f"{sym}_{direction}"
    if key in sent:
        hrs = (time.time()-sent[key])/3600
        if hrs < BLOCK_HOURS: return True, round(BLOCK_HOURS-hrs,1)
    return False, 0

def mark_sent(sent, sym, direction):
    sent[f"{sym}_{direction}"] = time.time()
    cutoff = time.time()-86400
    return {k:v for k,v in sent.items() if v>cutoff}

# ─── LOGGING ──────────────────────────────────────────────
def log_signal(r, fr, oi):
    exists = os.path.exists(LOG_FILE)
    fields = ["datetime","symbol","direction","grade","score","entry",
              "sl","tp1","tp2","tp3","rr","candle","candle_str",
              "pd_zone","h4_trend","h1_trend","mtf_agrees",
              "funding","oi","entry_zones","confirmations"]
    row = {
        "datetime":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol":       r["symbol"],
        "direction":    r["direction"],
        "grade":        r["grade"],
        "score":        r["score"],
        "entry":        r["entry"],
        "sl":           r["sl"],
        "tp1":          r["tp1"],
        "tp2":          r["tp2"],
        "tp3":          r["tp3"],
        "rr":           r["rr"],
        "candle":       r["candle"],
        "candle_str":   r["candle_str"],
        "pd_zone":      r["pd_zone"],
        "h4_trend":     r["h4_trend"],
        "h1_trend":     r["h1_trend"],
        "mtf_agrees":   r["mtf_agrees"],
        "funding":      fr.get("rate",0),
        "oi":           oi.get("signal","?"),
        "entry_zones":  "|".join(r.get("entry_zones",[])),
        "confirmations":"|".join(r["confirmations"]),
    }
    with open(LOG_FILE,"a",newline="") as f:
        w = csv.DictWriter(f,fieldnames=fields)
        if not exists: w.writeheader()
        w.writerow(row)

# ─── SIGNAL MESSAGE ───────────────────────────────────────
def make_signal(r, fr, oi):
    import os, requests as req

    groq_key = os.environ.get('GROQ_API_KEY','')
    d        = r["direction"]
    emoji    = "📈" if d=="LONG" else "📉"
    g_tag    = " 🔥" if r.get("is_gainer") else ""
    conf_txt = "\n".join([f"✅ {c}" for c in r["confirmations"][:5]])

    # Groq AI analysis
    ai_analysis = ""
    if groq_key:
        try:
            prompt = f"""You are a crypto trading analyst. Write a brief 2-3 sentence market analysis for this signal.
Symbol: {r['symbol']}
Direction: {d}
Timeframe: 5m entry, confirmed on 4H+1H
Score: {r['score']}/50
Key confirmations: {', '.join(r['confirmations'][:3])}
Candle pattern: {r['candle']}
Zone: {r['pd_zone']}

Rules:
- English only
- Maximum 3 sentences
- Mention why this is a good entry
- Mention key risk
- Be concise and professional"""

            resp = req.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}",
                         "Content-Type": "application/json"},
                json={"model": "llama3-8b-8192",
                      "max_tokens": 150,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=10
            )
            ai_analysis = resp.json()["choices"][0]["message"]["content"].strip()
        except:
            ai_analysis = ""

    grade_tag = {"A+":"🏆 A+ SETUP","B":"⚡ B SETUP","C":"📌 C SETUP"}[r["grade"]]
    pd_names  = {"discount":"🟢 Discount","premium":"🔴 Premium","equilibrium":"⚪ Equilibrium"}

    msg = f"""{'='*48}
{emoji} <b>{r['symbol']}</b> | 5m | <b>{d}</b>{g_tag}
{grade_tag} | Score: {r['score']}/50
{'='*48}
🕯 Candle  : {r['candle']}
🌍 Zone    : {pd_names[r['pd_zone']]}
📊 4H      : {r['h4_trend'].upper()}
📊 1H      : {r['h1_trend'].upper()}
📊 MTF     : {'30m+15m ✅' if r['mtf_agrees']==2 else '1 TF ✅'}

💰 Entry   : {r['entry']}
🛑 SL      : {r['sl']}
🎯 TP1     : {r['tp1']} (+2%)
🎯 TP2     : {r['tp2']} (+5%)
🎯 TP3     : {r['tp3']} (+7%)
📐 R:R     : 1:{r['rr']}
💼 Size    : {r['pos_size']}

🔍 Confirmations:
{conf_txt}"""

    if ai_analysis:
        msg += f"\n\n🤖 AI Analysis:\n{ai_analysis}"

    msg += f"\n\n⚠️ TradingView pe confirm karo!\n{'='*48}"
    return msg

# ─── MAIN SCANNER ─────────────────────────────────────────
import os

def send_telegram_signal(message):
    token   = os.environ.get('TELEGRAM_TOKEN', '8669042447:AAEXQrILOCgj5S89baTL1eMo42rr7luu5M8')
    chat_id = os.environ.get('CHAT_ID', '1255000050')
    try:
        import requests
        requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'},
            timeout=10
        )
    except:
        pass
def run_scanner():
    now  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sent = load_sent()

    print(f"\n{'#'*56}")
    print(f"  FUTURES SCANNER v5.0 — {now}")
    print(f"  CASCADE: 4H→1H→30m→15m→5m | Entry: 5m only")
    print(f"  Single signal per coin | Dup block: {BLOCK_HOURS}h")
    print(f"{'#'*56}")

    print("\n  Futures coins fetch ho rahe hain...")
    all_syms  = get_futures_symbols()
    print(f"  Total: {len(all_syms)} pairs")
    scan_list = get_top_volume(all_syms, TOP_COINS)
    gainers   = get_top_gainers(all_syms)
    print(f"  Scanning: {len(scan_list)} coins | Gainers: {len(gainers)}")
    print(f"\n  [Note: Har coin ke liye 5 TF fetch hoga — thoda waqt lagega]\n")

    results = []; skipped = 0; done = 0
    total   = len(scan_list)

    for sym in scan_list:
        done += 1
        pct  = int(done/total*100)
        bar  = "█"*(pct//5)+"░"*(20-pct//5)
        print(f"  [{bar}] {pct}% ({done}/{total}) — {sym}          ",end="\r")

        # Duplicate check (direction pata nahi abhi — check LONG aur SHORT dono)
        dup_l,_ = is_dup(sent, sym, "LONG")
        dup_s,_ = is_dup(sent, sym, "SHORT")
        if dup_l and dup_s:
            skipped += 1
            continue

        r = analyze_cascade(sym, gainers)

        if r is None:
            continue

        # Direction-specific dup check
        dup, hrs = is_dup(sent, sym, r["direction"])
        if dup:
            skipped += 1
            continue

        results.append(r)

    results.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n\n  {'='*56}")
    print(f"  SCAN COMPLETE")
    print(f"  New signals  : {len(results)}")
    print(f"  Skipped (dup): {skipped}")
    print(f"  {'='*56}\n")

    if not results:
        print("  Koi valid cascade signal nahi mila!")
        print("  Reasons:")
        print("  - 4H + 1H trend match nahi kar raha")
        print("  - 5m pe koi candlestick pattern nahi")
        print("  - R:R 1:2 se kam hai")
        print("  Thodi der baad scan karo\n")
        return []

    # Summary table
    print(f"  {'COIN':<12} {'DIR':<6} {'GR':<3} {'SC':>5}  {'ZONE':<14} {'CANDLE'}")
    print(f"  {'-'*70}")
    for r in results:
        g  = "🔥" if r.get("is_gainer") else "  "
        fl = "★" if r["flip"].get("retest") else " "
        sw = "⚡" if r["sweep"].get("swept") else " "
        print(f"  {r['symbol']:<12} {r['direction']:<6} {r['grade']:<3} "
              f"{r['score']:>3}/50  {r['pd_zone']:<14} {fl}{sw}{g} {r['candle']}")

    # Signal messages + logging
    print(f"\n{'='*56}")
    print("  TELEGRAM SIGNALS:")
    print(f"{'='*56}")

    for r in results[:5]:
            fr = get_funding_rate(r["symbol"])
            oi = get_open_interest(r["symbol"])
            print(make_signal(r, fr, oi))
            send_telegram_signal(make_signal(r, fr, oi))
            log_signal(r, fr, oi)
            sent = mark_sent(sent, r["symbol"], r["direction"])
            time.sleep(0.1)

    save_sent(sent)
    print(f"\n  Log: {LOG_FILE}")
    print(f"  Sent tracker: {SENT_FILE}\n")
    return results

def run_continuous(mins):
    print(f"\n  AUTO MODE: Har {mins} min — Ctrl+C se band karo\n")
    while True:
        try:
            run_scanner()
            print(f"  Next scan {mins} min mein...")
            time.sleep(mins*60)
        except KeyboardInterrupt:
            print("\n  Band. Allah Hafiz!"); break

if __name__ == "__main__":
    print("\n"+"="*56)
    print("  CRYPTO FUTURES SCANNER v5.0")
    print("  TOP-DOWN: 4H→1H→30m→15m→5m CASCADE")
    print("  10 Candlestick Patterns | ATR SL/TP | 0-50 Score")
    print("="*56)
    print("\n  1 = Ek baar scan karo")
    print("  2 = Har 15 min auto scan")
    print("  3 = Har 30 min auto scan")
    print("  4 = Custom interval")
    c = input("\n  Choice (1/2/3/4): ").strip()
    if   c=="2": run_continuous(15)
    elif c=="3": run_continuous(30)
    elif c=="4": run_continuous(int(input("  Kitne minute: ")))
    else:        run_scanner()
