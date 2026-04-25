"""
=======================================================
  CRYPTO FUTURES SCANNER v5.1 — FIXED + IMPROVED
  TOP-DOWN CASCADE: 4H → 1H → 30m → 15m → 5m
  SCAN INTERVAL: 30 MINUTES (FUTURES OPTIMIZED)
=======================================================
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
BLOCK_HOURS = 2  # Changed from 4 to 2 for faster trading
LOG_FILE    = "v5_signals_log.csv"
SENT_FILE   = "v5_sent.json"

# ─── DUPLICATE FILTER ─────────────────────────────────────
def load_sent():
    if os.path.exists(SENT_FILE):
        try:
            with open(SENT_FILE,"r") as f: 
                return json.load(f)
        except: 
            pass
    return {}

def save_sent(d):
    with open(SENT_FILE,"w") as f: 
        json.dump(d, f, indent=2)

def is_dup(sent, sym, direction):
    key = f"{sym}_{direction}"
    if key in sent:
        hrs = (time.time() - sent[key]) / 3600
        if hrs < BLOCK_HOURS: 
            return True, round(BLOCK_HOURS - hrs, 1)
    return False, 0

def mark_sent(sent, sym, direction):
    sent[f"{sym}_{direction}"] = time.time()
    cutoff = time.time() - 86400  # 24 hours old delete
    return {k: v for k, v in sent.items() if v > cutoff}

# ─── LOGGING ──────────────────────────────────────────────
def log_signal(r, fr, oi):
    exists = os.path.exists(LOG_FILE)
    fields = ["datetime", "symbol", "direction", "grade", "score", "entry",
              "sl", "tp1", "tp2", "tp3", "rr", "candle", "candle_str",
              "pd_zone", "h4_trend", "h1_trend", "mtf_agrees",
              "funding", "oi", "entry_zones", "confirmations"]
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
        "funding":      fr.get("rate", 0),
        "oi":           oi.get("signal", "?"),
        "entry_zones":  "|".join(r.get("entry_zones", [])),
        "confirmations": "|".join(r["confirmations"]),
    }
    with open(LOG_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not exists: 
            w.writeheader()
        w.writerow(row)

# ─── SIGNAL MESSAGE (NO GROQ - FASTER) ────────────────────
def make_signal_fast(r, fr, oi):
    """Template-based signal - faster than Groq API"""
    d = r["direction"]
    emoji = "🟢" if d == "LONG" else "🔴"
    
    grade_names = {"A+": "🔥 A+ PREMIUM", "B": "✅ B GOOD", "C": "⚠️ C CAUTION"}
    
    # Build confirmations string
    conf_lines = []
    for c in r["confirmations"][:5]:
        conf_lines.append(f"  • {c}")
    conf_text = "\n".join(conf_lines) if conf_lines else "  • Basic setup confirmed"
    
    # Entry zone info
    entry_zones_text = ""
    if r.get("entry_zones"):
        entry_zones_text = f"\n📍 Entry Trigger:\n  • {r['entry_zones'][0]}"
    
    # OI + Funding
    oi_symbol = "📈" if oi.get("signal") == "rising" else "📉" if oi.get("signal") == "falling" else "➖"
    oi_line = f"{oi_symbol} OI: {oi.get('signal', 'neutral').upper()}" if oi.get('signal', 'unknown') != 'unknown' else ""
    fr_line = f"💸 Funding: {fr.get('rate', 0)}%"
    fr_emoji = "🐂" if fr.get('rate', 0) < -0.03 else "🐻" if fr.get('rate', 0) > 0.03 else "⚖️"
    
    # Risk level based on score
    risk_level = "LOW" if r["score"] >= SCORE_A else "MEDIUM" if r["score"] >= SCORE_B else "HIGH"
    
    msg = f"""{emoji} <b>#{r['symbol']} – {d} SIGNAL ACTIVE</b>
━━━━━━━━━━━━━━━━━━━━━━━

📊 <b>Setup Summary:</b>
  • Pattern: {r['candle']}
  • Grade: {grade_names.get(r['grade'], r['grade'])} ({r['score']}/50)
  • Risk: {risk_level}
  • Trend Cascade: 4H({r['h4_trend']}) → 1H({r['h1_trend']}) → 5m Confirmed

🔧 <b>Confirmations:</b>
{conf_text}
{entry_zones_text}

💎 <b>Entry Zone:</b>
  ✅ {r['entry']}

🎯 <b>Take-Profit Targets:</b>
  • TP1: {r['tp1']}  (~1.5% 🎯)
  • TP2: {r['tp2']}  (~3% 🚀)
  • TP3: {r['tp3']}  (~4.5% 🌙)

🛡️ <b>Stop-Loss:</b>
  ❌ {r['sl']}  (Risk: {r['rr']:.1f}R)

📈 <b>Context:</b>
  {oi_line}
  {fr_emoji} {fr_line}

━━━━━━━━━━━━━━━━━━━━━━━
⚠️ Risk: 1-2% per trade | Use SL strictly
🤖 BaytoHunter Scanner v5.1 | 30min scan"""
    
    return msg

# ─── TELEGRAM SENDER ──────────────────────────────────────
def send_telegram_signal(message):
    # IMPORTANT: GitHub secrets mein daalo - HARDCODED MAT KARO!
    token = os.environ.get('TELEGRAM_TOKEN')
    chat_id = os.environ.get('CHAT_ID')
    
    if not token or not chat_id:
        print("  ⚠️ TELEGRAM_TOKEN or CHAT_ID not set in environment!")
        print("  Signal printed above but not sent to Telegram.")
        return False
    
    try:
        import requests
        resp = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'},
            timeout=10
        )
        if resp.status_code == 200:
            return True
        else:
            print(f"  Telegram error: {resp.text}")
            return False
    except Exception as e:
        print(f"  Telegram send failed: {e}")
        return False

# ─── MAIN SCANNER ─────────────────────────────────────────
def run_scanner():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sent = load_sent()

    print(f"\n{'#'*56}")
    print(f"  FUTURES SCANNER v5.1 — {now}")
    print(f"  CASCADE: 4H→1H→30m→15m→5m | Entry: 5m only")
    print(f"  Duplicate block: {BLOCK_HOURS}h | Fast mode (no AI)")
    print(f"{'#'*56}")

    print("\n  📡 Fetching futures coins...")
    all_syms = get_futures_symbols()
    print(f"  ✓ Total pairs: {len(all_syms)}")
    
    scan_list = get_top_volume(all_syms, TOP_COINS)
    gainers = get_top_gainers(all_syms)
    print(f"  ✓ Scanning: {len(scan_list)} coins | Top gainers: {len(gainers)}")
    print(f"\n  🔄 Scanning (5 TF per coin)...\n")

    results = []
    skipped_dup = 0
    skipped_api = 0
    done = 0
    total = len(scan_list)

    for sym in scan_list:
        done += 1
        pct = int(done/total*100)
        bar = "█"*(pct//5) + "░"*(20-pct//5)
        print(f"  [{bar}] {pct}% ({done}/{total}) — {sym:<12}   ", end="\r")

        # Check duplicates for both directions
        dup_l, _ = is_dup(sent, sym, "LONG")
        dup_s, _ = is_dup(sent, sym, "SHORT")
        if dup_l and dup_s:
            skipped_dup += 1
            continue

        try:
            r = analyze_cascade(sym, gainers)
        except Exception as e:
            skipped_api += 1
            continue

        if r is None:
            continue

        # Direction-specific duplicate check
        dup, hrs_left = is_dup(sent, sym, r["direction"])
        if dup:
            skipped_dup += 1
            continue

        results.append(r)

    print(f"\n\n  {'='*56}")
    print(f"  ✓ SCAN COMPLETE")
    print(f"  📊 New signals  : {len(results)}")
    print(f"  ⏭️  Skipped (dup) : {skipped_dup}")
    print(f"  ❌ API errors    : {skipped_api}")
    print(f"  {'='*56}\n")

    if not results:
        print("  ❌ No valid signals found!")
        print("     Possible reasons:")
        print("     • 4H + 1H trends don't match")
        print("     • No candlestick pattern on 5m")
        print("     • Risk/Reward below 1:2")
        print("     • Try again in 30 minutes\n")
        return []

    # Summary table
    print(f"  {'COIN':<12} {'DIR':<6} {'GR':<3} {'SC':>5}  {'ZONE':<14} {'CANDLE':<25}")
    print(f"  {'-'*75}")
    for r in results[:10]:
        g = "🔥" if r.get("is_gainer") else "  "
        fl = "↺" if r.get("flip", {}).get("retest") else " "
        sw = "⚡" if r.get("sweep", {}).get("swept") else " "
        print(f"  {r['symbol']:<12} {r['direction']:<6} {r['grade']:<3} "
              f"{r['score']:>3}/50  {r['pd_zone']:<14} {fl}{sw}{g} {r['candle']:<25}")

    # Send signals to Telegram
    print(f"\n{'='*56}")
    print("  📤 SENDING SIGNALS TO TELEGRAM:")
    print(f"{'='*56}")

    sent_count = 0
    for r in results[:5]:  # Max 5 signals per scan
        fr = get_funding_rate(r["symbol"])
        oi = get_open_interest(r["symbol"])
        
        msg = make_signal_fast(r, fr, oi)  # Fast template, no Groq
        
        # Print to console
        print(f"\n📡 {r['symbol']} - {r['direction']} (Score: {r['score']}/50)")
        
        # Send to Telegram
        if send_telegram_signal(msg):
            sent_count += 1
            print(f"  ✓ Sent to Telegram")
        else:
            print(f"  ⚠️ Failed to send (check TELEGRAM_TOKEN)")
            
        log_signal(r, fr, oi)
        sent = mark_sent(sent, r["symbol"], r["direction"])
        time.sleep(1)  # Rate limit for Telegram

    save_sent(sent)
    print(f"\n  📁 Log saved: {LOG_FILE}")
    print(f"  📁 Sent tracker: {SENT_FILE}")
    print(f"  ✓ {sent_count} signals sent to Telegram\n")
    return results

def run_continuous(mins):
    print(f"\n  🔄 AUTO MODE ACTIVE: Scan every {mins} minutes")
    print(f"  Press Ctrl+C to stop\n")
    scan_count = 0
    while True:
        try:
            scan_count += 1
            print(f"\n{'='*56}")
            print(f"  SCAN #{scan_count} - {datetime.now().strftime('%H:%M:%S')}")
            print(f"{'='*56}")
            run_scanner()
            print(f"  😴 Next scan in {mins} minutes...")
            time.sleep(mins * 60)
        except KeyboardInterrupt:
            print("\n\n  👋 Scanner stopped. Goodbye!\n")
            break
        except Exception as e:
            print(f"\n  ❌ Error: {e}")
            print(f"  Restarting scan in 60 seconds...")
            time.sleep(60)

if __name__ == "__main__":
    print("\n" + "="*56)
    print("  🤖 CRYPTO FUTURES SCANNER v5.1")
    print("  📊 TOP-DOWN: 4H→1H→30m→15m→5m CASCADE")
    print("  🕯️ 10+ Candlestick Patterns | ATR SL/TP")
    print("  ⚡ Optimized for futures | 30min scan")
    print("="*56)
    print("\n  📌 Select scan mode:")
    print("     1 = Single scan (one time)")
    print("     2 = Every 15 minutes (fast)")
    print("     3 = Every 30 minutes (recommended)")
    print("     4 = Custom interval")
    
    choice = input("\n  👉 Enter choice (1/2/3/4): ").strip()
    
    if choice == "2":
        run_continuous(15)
    elif choice == "3":
        run_continuous(30)
    elif choice == "4":
        mins = int(input("  👉 Enter minutes: "))
        run_continuous(mins)
    else:
        run_scanner()
