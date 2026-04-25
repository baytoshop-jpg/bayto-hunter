"""
CRYPTO FUTURES SCANNER v5.3 — DEBUG MODE
Har coin ka status dikhayega - kyun signal nahi mil raha
"""
import time, json, csv, os
import requests
from datetime import datetime
from v5_engine import (
    get_futures_symbols, get_top_volume, get_top_gainers,
    get_funding_rate, get_open_interest, analyze_cascade,
    SCORE_A, SCORE_B, SCORE_C
)

TOP_COINS = 30  # Kam kiya for faster debug
GAINER_THRESHOLD = 5  # Kam kiya 5% se
BLOCK_HOURS = 2
LOG_FILE = "v5_signals_log.csv"
SENT_FILE = "v5_sent.json"
FAPI = "https://fapi.binance.com"

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

def get_all_gainers_with_pct(all_syms):
    """Sab gainers fetch karo with percentage"""
    endpoints = [
        "https://fapi.binance.com/fapi/v1/ticker/24hr",
        "https://api.binance.com/api/v3/ticker/24hr",
    ]
    
    for url in endpoints:
        try:
            print(f"    Fetching from: {url[:50]}...")
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
    return []

def make_signal_fast(r, fr, oi):
    d = r["direction"]
    emoji = "🟢" if d == "LONG" else "🔴"
    grade_names = {"A+": "🔥 A+", "B": "✅ B", "C": "⚠️ C"}
    
    msg = f"""{emoji} <b>#{r['symbol']} – {d}</b>
━━━━━━━━━━━━━━━━━━━━━━━
📊 <b>Grade: {grade_names.get(r['grade'], r['grade'])} ({r['score']}/50)</b>
📐 Pattern: {r['candle']}
🎯 Entry: {r['entry']}
🛡️ SL: {r['sl']}
📍 TP1: {r['tp1']} | TP2: {r['tp2']}
📈 RR: {r['rr']}

✅ {r['confirmations'][0]}
✅ {r['confirmations'][1]}

━━━━━━━━━━━━━━━━━━━━━━━
🤖 BaytoHunter v5.3"""
    return msg

def send_telegram_signal(message):
    token = os.environ.get('TELEGRAM_TOKEN')
    chat_id = os.environ.get('CHAT_ID')
    if not token or not chat_id:
        return False
    try:
        requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'},
            timeout=10
        )
        return True
    except:
        return False

def log_debug(symbol, status, reason=""):
    """Debug log - kyun signal nahi mila"""
    with open("debug_log.txt", "a") as f:
        f.write(f"{datetime.now().strftime('%H:%M:%S')} | {symbol} | {status} | {reason}\n")

def run_scanner():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sent = load_sent()

    print(f"\n{'#'*56}")
    print(f"  🔍 DEBUG SCANNER v5.3 — {now}")
    print(f"{'#'*56}")

    print("\n  📡 Fetching futures coins...")
    all_syms = get_futures_symbols()
    print(f"  ✓ Total pairs: {len(all_syms)}")
    
    # Get gainers
    print(f"\n  🔍 Finding gainers > {GAINER_THRESHOLD}%...")
    gainers_list = get_all_gainers_with_pct(all_syms)
    gainer_symbols = [g["symbol"] for g in gainers_list]
    
    # Show top gainers
    if gainers_list:
        print(f"\n  📊 TOP 10 GAINERS TODAY:")
        for i, g in enumerate(gainers_list[:10], 1):
            arrow = "🚀" if g['change'] > 15 else "📈" if g['change'] > 5 else "📊"
            print(f"     {i}. {arrow} {g['symbol']}: {g['change']:+.2f}%")
    else:
        print(f"  ⚠️ No gainers > {GAINER_THRESHOLD}% found!")
    
    # Scan list - gainers first
    scan_list = gainer_symbols[:20]  # Sirf top 20 gainers scan karo pehle
    if len(scan_list) < 10:
        scan_list = get_top_volume(all_syms, 30)
    
    print(f"\n  🔄 Scanning {len(scan_list)} coins...\n")
    
    results = []
    stats = {
        "total": 0,
        "htf_fail": 0,
        "no_5m_pattern": 0,
        "low_score": 0,
        "low_rr": 0,
        "dup": 0
    }
    
    for i, sym in enumerate(scan_list[:20], 1):
        stats["total"] += 1
        print(f"  [{i:2}/20] Analyzing {sym:<12}... ", end="")
        
        # Duplicate check
        dup_l, _ = is_dup(sent, sym, "LONG")
        dup_s, _ = is_dup(sent, sym, "SHORT")
        if dup_l and dup_s:
            print("⏭️ DUPLICATE")
            stats["dup"] += 1
            log_debug(sym, "DUPLICATE", "Already sent recently")
            continue
        
        try:
            gainers_set = {g["symbol"] for g in gainers_list}
            r = analyze_cascade(sym, gainers_set)
            
            if r is None:
                print("❌ NO SIGNAL")
                stats["no_5m_pattern"] += 1
                log_debug(sym, "NO_SIGNAL", "No 5m pattern or trend mismatch")
                continue
            
            # Check if score is good
            if r['score'] < SCORE_C:
                print(f"⚠️ LOW SCORE ({r['score']}/{SCORE_C})")
                stats["low_score"] += 1
                log_debug(sym, f"LOW_SCORE", f"{r['score']}/{SCORE_C}")
                continue
            
            results.append(r)
            print(f"✅ {r['direction']} | SCORE: {r['score']}/50 | {r['candle'][:15]}")
            log_debug(sym, "SIGNAL", f"{r['direction']} score={r['score']}")
            
        except Exception as e:
            print(f"❌ ERROR: {str(e)[:30]}")
            log_debug(sym, "ERROR", str(e)[:50])
    
    # Print statistics
    print(f"\n{'='*56}")
    print(f"  📊 SCAN STATISTICS:")
    print(f"  {'='*56}")
    print(f"     Total coins scanned: {stats['total']}")
    print(f"     ❌ HTF/5m pattern fail: {stats['no_5m_pattern']}")
    print(f"     ⚠️ Low score (<{SCORE_C}): {stats['low_score']}")
    print(f"     ⏭️ Duplicate blocked: {stats['dup']}")
    print(f"     ✅ SIGNALS FOUND: {len(results)}")
    print(f"  {'='*56}\n")
    
    # Check debug log
    if os.path.exists("debug_log.txt"):
        print(f"  📁 Debug log saved: debug_log.txt")
        print(f"     Check karo kin coins mein kya issue hai\n")
    
    # Send signals
    if results:
        print(f"  📤 Sending {len(results)} signals to Telegram...")
        for r in results[:3]:
            fr = get_funding_rate(r["symbol"])
            oi = get_open_interest(r["symbol"])
            msg = make_signal_fast(r, fr, oi)
            send_telegram_signal(msg)
            print(f"     ✓ {r['symbol']} sent")
            time.sleep(1)
    
    return results

def run_continuous(mins):
    print(f"\n  🔄 Auto scan every {mins} minutes\n")
    while True:
        try:
            run_scanner()
            print(f"\n  😴 Next scan in {mins} minutes...\n")
            time.sleep(mins * 60)
        except KeyboardInterrupt:
            print("\n  👋 Stopped.\n")
            break

if __name__ == "__main__":
    print("\n" + "="*56)
    print("  🔍 DEBUG MODE SCANNER v5.3")
    print("  📊 Shows WHY signals are/aren't generated")
    print("="*56)
    
    print("\n  Select mode:")
    print("    1 = Single scan (with debug)")
    print("    2 = Every 15 min")
    print("    3 = Every 30 min")
    
    choice = input("\n  👉 Choice (1/2/3): ").strip()
    
    if choice == "2":
        run_continuous(15)
    elif choice == "3":
        run_continuous(30)
    else:
        run_scanner()
