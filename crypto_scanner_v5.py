"""
CRYPTO FUTURES SCANNER v5.2 — GAINERS FIRST
Har 30 min mein top gainers scan karta hai aur signal bhejta hai
"""
import time, json, csv, os
import requests  # <-- IMPORTANT: requests import karna hai
from datetime import datetime
from v5_engine import (
    get_futures_symbols, get_top_volume, get_top_gainers,
    get_funding_rate, get_open_interest, analyze_cascade,
    SCORE_A, SCORE_B, SCORE_C
)

# ─── SETTINGS ─────────────────────────────────────────────
TOP_COINS = 50
GAINER_THRESHOLD = 8    # 8%+ gainers ko priority (change kar sakte ho)
BLOCK_HOURS = 2         # Same coin ka signal 2 ghante baad
LOG_FILE = "v5_signals_log.csv"
SENT_FILE = "v5_sent.json"
FAPI = "https://fapi.binance.com"

# ─── DUPLICATE FILTER ─────────────────────────────────────
def load_sent():
    if os.path.exists(SENT_FILE):
        try:
            with open(SENT_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_sent(d):
    with open(SENT_FILE, "w") as f:
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
    cutoff = time.time() - 86400
    return {k: v for k, v in sent.items() if v > cutoff}

def log_signal(r, fr, oi):
    exists = os.path.exists(LOG_FILE)
    fields = ["datetime", "symbol", "direction", "grade", "score", "entry",
              "sl", "tp1", "tp2", "tp3", "rr", "candle", "candle_str",
              "pd_zone", "h4_trend", "h1_trend", "mtf_agrees",
              "funding", "oi", "entry_zones", "confirmations", "price_change"]
    row = {
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": r["symbol"],
        "direction": r["direction"],
        "grade": r["grade"],
        "score": r["score"],
        "entry": r["entry"],
        "sl": r["sl"],
        "tp1": r["tp1"],
        "tp2": r["tp2"],
        "tp3": r["tp3"],
        "rr": r["rr"],
        "candle": r["candle"],
        "candle_str": r["candle_str"],
        "pd_zone": r["pd_zone"],
        "h4_trend": r["h4_trend"],
        "h1_trend": r["h1_trend"],
        "mtf_agrees": r["mtf_agrees"],
        "funding": fr.get("rate", 0),
        "oi": oi.get("signal", "?"),
        "entry_zones": "|".join(r.get("entry_zones", [])),
        "confirmations": "|".join(r["confirmations"]),
        "price_change": r.get("price_change", 0),
    }
    with open(LOG_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            w.writeheader()
        w.writerow(row)

def get_all_gainers_with_pct(all_syms):
    """Sab gainers fetch karo with percentage - RELIABLE VERSION"""
    
    # Multiple endpoints try karega
    endpoints = [
        "https://fapi.binance.com/fapi/v1/ticker/24hr",
        "https://api.binance.com/api/v3/ticker/24hr",
    ]
    
    for url in endpoints:
        try:
            print(f"    Fetching gainers from: {url[:50]}...")
            r = requests.get(url, timeout=15)
            
            if r.status_code == 200:
                data = r.json()
                gainers = []
                
                for ticker in data:
                    sym = ticker.get('symbol')
                    if sym and sym in all_syms:
                        try:
                            pct = float(ticker.get('priceChangePercent', 0))
                            if abs(pct) >= GAINER_THRESHOLD:
                                gainers.append({
                                    'symbol': sym,
                                    'change': pct,
                                    'volume': float(ticker.get('quoteVolume', 0))
                                })
                        except:
                            continue
                
                gainers.sort(key=lambda x: abs(x['change']), reverse=True)
                if gainers:
                    print(f"    ✓ Found {len(gainers)} gainers >{GAINER_THRESHOLD}%")
                    return gainers
                    
        except Exception as e:
            print(f"    Failed: {e}")
            continue
    
    print("    ⚠️ No gainers found - will use volume coins only")
    return []

def get_price_change(symbol):
    """24h price change percentage fetch karo"""
    try:
        r = requests.get(f"{FAPI}/fapi/v1/ticker/24hr", params={"symbol": symbol}, timeout=10)
        return float(r.json()["priceChangePercent"])
    except:
        return 0

def make_signal_fast(r, fr, oi):
    """Telegram signal message banaye - without Groq (fast)"""
    d = r["direction"]
    emoji = "🟢" if d == "LONG" else "🔴"
    grade_names = {"A+": "🔥 A+ PREMIUM", "B": "✅ B GOOD", "C": "⚠️ C CAUTION"}
    
    conf_lines = [f"  • {c}" for c in r["confirmations"][:5]]
    conf_text = "\n".join(conf_lines) if conf_lines else "  • Basic setup confirmed"
    
    entry_zones_text = ""
    if r.get("entry_zones"):
        entry_zones_text = f"\n📍 Entry Zone:\n  • {r['entry_zones'][0]}"
    
    oi_symbol = "📈" if oi.get("signal") == "rising" else "📉" if oi.get("signal") == "falling" else "➖"
    oi_line = f"{oi_symbol} OI: {oi.get('signal', 'neutral').upper()}" if oi.get('signal', 'unknown') != 'unknown' else ""
    fr_line = f"💰 Funding: {fr.get('rate', 0)}%"
    
    price_change_line = ""
    if r.get("price_change"):
        change_emoji = "🚀" if r["price_change"] > 15 else "📈" if r["price_change"] > 5 else "📊"
        price_change_line = f"\n{change_emoji} <b>24h Move: {r['price_change']:+.2f}%</b>"
    
    msg = f"""{emoji} <b>#{r['symbol']} – {d} SIGNAL ACTIVE</b>
━━━━━━━━━━━━━━━━━━━━━━━{price_change_line}

📊 <b>Setup:</b>
  • Pattern: {r['candle']}
  • Grade: {grade_names.get(r['grade'], r['grade'])} ({r['score']}/50)
  • Trend: 4H({r['h4_trend']}) → 1H({r['h1_trend']}) → 5m

🔧 <b>Confirmations:</b>
{conf_text}{entry_zones_text}

🎯 <b>Entry: {r['entry']}</b>
🛡️ <b>SL: {r['sl']}</b>  |  📍 <b>TP1: {r['tp1']}</b>  |  🚀 <b>TP2: {r['tp2']}</b>

📈 <b>Data:</b>  {oi_line}  |  {fr_line}

━━━━━━━━━━━━━━━━━━━━━━━
⚠️ Risk 1-2% only | 🕐 {datetime.now().strftime('%H:%M')}
🤖 BaytoHunter v5.2 | +{GAINER_THRESHOLD}% gainers priority"""
    return msg

def send_telegram_signal(message):
    """Telegram par signal bheje"""
    token = os.environ.get('TELEGRAM_TOKEN')
    chat_id = os.environ.get('CHAT_ID')
    
    if not token or not chat_id:
        print("  ⚠️ TELEGRAM_TOKEN or CHAT_ID not set!")
        print("  GitHub Secrets mein daalna hai: TELEGRAM_TOKEN aur CHAT_ID")
        return False
    
    try:
        resp = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'},
            timeout=10
        )
        if resp.status_code == 200:
            print("    ✓ Telegram sent!")
            return True
        else:
            print(f"    ✗ Telegram error: {resp.text}")
            return False
    except Exception as e:
        print(f"    ✗ Telegram exception: {e}")
        return False

# ─── MAIN SCANNER ─────────────────────────────────────────
def run_scanner():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sent = load_sent()

    print(f"\n{'#'*56}")
    print(f"  🚀 GAINERS-FIRST SCANNER v5.2 — {now}")
    print(f"  Priority: >{GAINER_THRESHOLD}% movers")
    print(f"{'#'*56}")

    print("\n  📡 Fetching futures coins...")
    all_syms = get_futures_symbols()
    print(f"  ✓ Total pairs: {len(all_syms)}")
    
    # STEP 1: Gainers fetch karo
    print(f"\n  🔍 Finding gainers > {GAINER_THRESHOLD}%...")
    gainers_list = get_all_gainers_with_pct(all_syms)
    
    # STEP 2: Scan list banaye
    gainer_symbols = [g["symbol"] for g in gainers_list]
    volume_coins = get_top_volume(all_syms, TOP_COINS)
    
    scan_list = []
    seen = set()
    
    # Gainers pehle
    for sym in gainer_symbols:
        if sym not in seen:
            scan_list.append(sym)
            seen.add(sym)
    
    # Phir volume coins
    for sym in volume_coins:
        if sym not in seen and len(scan_list) < TOP_COINS:
            scan_list.append(sym)
            seen.add(sym)
    
    print(f"\n  ✓ Scan list: {len(scan_list)} coins ({len(gainer_symbols)} gainers)")
    
    if gainers_list:
        print(f"\n  📊 TODAY'S TOP MOVERS:")
        for g in gainers_list[:8]:
            arrow = "🔥" if abs(g['change']) > 20 else "📈" if g['change'] > 0 else "📉"
            print(f"     {arrow} {g['symbol']}: {g['change']:+.2f}%")
    
    print(f"\n  🔄 Scanning (5 TF per coin)...\n")

    results = []
    done = 0
    total = len(scan_list)

    for sym in scan_list:
        done += 1
        pct = int(done/total*100)
        bar = "█"*(pct//5) + "░"*(20-pct//5)
        print(f"  [{bar}] {pct}% ({done}/{total}) — {sym:<12}   ", end="\r")

        # Duplicate check
        dup_l, _ = is_dup(sent, sym, "LONG")
        dup_s, _ = is_dup(sent, sym, "SHORT")
        if dup_l and dup_s:
            continue

        try:
            gainers_set = {g["symbol"] for g in gainers_list}
            r = analyze_cascade(sym, gainers_set)
            
            if r:
                # Price change add karo
                pc = next((g["change"] for g in gainers_list if g["symbol"] == sym), 0)
                r["price_change"] = pc
                results.append(r)
        except Exception as e:
            continue

    print(f"\n\n  {'='*56}")
    print(f"  ✓ SCAN COMPLETE - {len(results)} NEW SIGNALS")
    print(f"  {'='*56}\n")

    if results:
        print(f"  📡 SIGNALS FOUND:")
        for r in results:
            print(f"     🎯 {r['symbol']} {r['direction']} | Score: {r['score']}/50 | Pattern: {r['candle']}")
        
        print(f"\n  📤 SENDING TO TELEGRAM...")
        for r in results[:5]:
            fr = get_funding_rate(r["symbol"])
            oi = get_open_interest(r["symbol"])
            msg = make_signal_fast(r, fr, oi)
            send_telegram_signal(msg)
            log_signal(r, fr, oi)
            sent = mark_sent(sent, r["symbol"], r["direction"])
            time.sleep(1)
        
        save_sent(sent)
        print(f"\n  📁 Log saved: {LOG_FILE}")
    else:
        print("  ❌ No signals found.")
        print("     Gainers move fast - need confirmation setup")
        print("     Scanner will check again in 30 mins")

    return results

def run_continuous(mins):
    """Har X minute mein scan karega"""
    print(f"\n  🔄 AUTO SCAN MODE: Every {mins} minutes")
    print(f"  Press Ctrl+C to stop\n")
    
    scan_count = 0
    while True:
        try:
            scan_count += 1
            print(f"\n{'='*56}")
            print(f"  SCAN #{scan_count} - {datetime.now().strftime('%H:%M:%S')}")
            print(f"{'='*56}")
            run_scanner()
            print(f"\n  😴 Next scan in {mins} minutes...")
            time.sleep(mins * 60)
        except KeyboardInterrupt:
            print("\n  👋 Scanner stopped. Goodbye!\n")
            break
        except Exception as e:
            print(f"\n  ❌ Error: {e}")
            print(f"  Restarting in 60 seconds...")
            time.sleep(60)

# ─── MAIN ─────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "="*56)
    print("  🤖 CRYPTO FUTURES SCANNER v5.2")
    print("  📊 TOP-DOWN: 4H→1H→30m→15m→5m")
    print("  🎯 PRIORITY: Top Gainers First")
    print("="*56)
    
    print("\n  Select mode:")
    print("    1 = Single scan")
    print("    2 = Every 15 min (fast)")
    print("    3 = Every 30 min (recommended)")
    print("    4 = Custom")
    
    choice = input("\n  👉 Choice (1/2/3/4): ").strip()
    
    if choice == "2":
        run_continuous(15)
    elif choice == "3":
        run_continuous(30)
    elif choice == "4":
        mins = int(input("  Minutes: "))
        run_continuous(mins)
    else:
        run_scanner()
