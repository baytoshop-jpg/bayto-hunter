"""
CRYPTO FUTURES SCANNER v5.3 — DEBUG MODE
Har coin ka status dikhayega
"""
import time, json, csv, os
import requests
from datetime import datetime
from v5_engine import (
    get_futures_symbols, get_top_volume, get_top_gainers,
    get_funding_rate, get_open_interest, analyze_cascade,
    SCORE_A, SCORE_B, SCORE_C
)

TOP_COINS = 50
GAINER_THRESHOLD = 3
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
    """Direct fetch top gainers"""
    try:
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            gainers = []
            for ticker in data:
                sym = ticker.get('symbol')
                if sym and sym in all_syms and sym.endswith('USDT'):
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
                return gainers
    except Exception as e:
        print(f"    Gainers fetch failed: {e}")
    return []

def make_signal_fast(r, fr, oi):
    d = r["direction"]
    emoji = "🟢" if d == "LONG" else "🔴"
    
    msg = f"""{emoji} <b>#{r['symbol']} – {d}</b>
━━━━━━━━━━━━━━━━━━━━━━━
📊 <b>Grade: {r['grade']} ({r['score']}/50)</b>
📐 Pattern: {r['candle']}
🎯 Entry: {r['entry']}
🛡️ SL: {r['sl']}
📍 TP1: {r['tp1']} | TP2: {r['tp2']}
📈 RR: {r['rr']}

✅ {r['confirmations'][0]}
✅ {r['confirmations'][1]}

━━━━━━━━━━━━━━━━━━━━━━━
🤖 BaytoHunter Scanner"""
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
    with open("debug_log.txt", "a") as f:
        f.write(f"{datetime.now().strftime('%H:%M:%S')} | {symbol} | {status} | {reason}\n")

def get_top_gainers_direct(limit=30):
    """Directly fetch top gainers without any symbol list"""
    try:
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            usdt_pairs = [t for t in data if t['symbol'].endswith('USDT')]
            usdt_pairs.sort(key=lambda x: float(x['priceChangePercent']), reverse=True)
            
            top_gainers = []
            for t in usdt_pairs[:limit]:
                top_gainers.append({
                    'symbol': t['symbol'],
                    'change': float(t['priceChangePercent']),
                    'volume': float(t['quoteVolume'])
                })
            return top_gainers
    except Exception as e:
        print(f"Direct fetch failed: {e}")
    return []

def run_scanner():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sent = load_sent()

    print(f"\n{'#'*56}")
    print(f"  SCANNER v5.3 — {now}")
    print(f"{'#'*56}")

    # DIRECT FETCH - Binance se seedha top gainers le lo
    print("\n  📡 Fetching TOP GAINERS directly from Binance...")
    direct_gainers = get_top_gainers_direct(30)
    
    if direct_gainers:
        print(f"\n  📊 TODAY'S TOP GAINERS:")
        for i, g in enumerate(direct_gainers[:15], 1):
            arrow = "🚀" if g['change'] > 15 else "📈" if g['change'] > 5 else "📊"
            print(f"     {i}. {arrow} {g['symbol']}: {g['change']:+.2f}%")
        
        # Inhi gainers ko scan karo
        scan_list = [g['symbol'] for g in direct_gainers[:20]]
        gainers_set = {g['symbol'] for g in direct_gainers}
    else:
        # Fallback
        print("  Direct fetch failed, using volume method...")
        all_syms = get_futures_symbols()
        scan_list = get_top_volume(all_syms, 30)
        gainers_set = set()
    
    print(f"\n  🔄 Scanning {len(scan_list)} coins...\n")
    
    results = []
    stats = {"total": 0, "failed": 0, "dup": 0, "low_score": 0}
    
    for i, sym in enumerate(scan_list[:20], 1):
        stats["total"] += 1
        print(f"  [{i:2}/20] {sym:<12}... ", end="")
        
        dup_l, _ = is_dup(sent, sym, "LONG")
        dup_s, _ = is_dup(sent, sym, "SHORT")
        if dup_l and dup_s:
            print("⏭️ DUPLICATE")
            stats["dup"] += 1
            continue
        
        try:
            r = analyze_cascade(sym, gainers_set)
            if r is None:
                print("❌ NO")
                stats["failed"] += 1
                continue
            
            if r['score'] < SCORE_C:
                print(f"⚠️ LOW ({r['score']}/5)")
                stats["low_score"] += 1
                continue
            
            results.append(r)
            print(f"✅ {r['direction']} | {r['score']}/50")
            
        except Exception as e:
            print(f"❌ ERR")
            stats["failed"] += 1
    
    print(f"\n{'='*56}")
    print(f"  RESULTS: {len(results)} signals found")
    print(f"  Scanned: {stats['total']} | Failed: {stats['failed']} | Dup: {stats['dup']}")
    print(f"{'='*56}\n")
    
    if results:
        for r in results[:3]:
            fr = get_funding_rate(r["symbol"])
            oi = get_open_interest(r["symbol"])
            msg = make_signal_fast(r, fr, oi)
            send_telegram_signal(msg)
            print(f"  📤 Sent {r['symbol']} to Telegram")
            log_debug(r['symbol'], "SENT", f"{r['direction']} score={r['score']}")
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
    print("  CRYPTO FUTURES SCANNER v5.3")
    print("  Direct Binance Top Gainers Fetch")
    print("="*56)
    
    print("\n  Select mode:")
    print("    1 = Single scan")
    print("    2 = Every 15 min")
    print("    3 = Every 30 min")
    
    choice = input("\n  👉 Choice (1/2/3): ").strip()
    
    if choice == "2":
        run_continuous(15)
    elif choice == "3":
        run_continuous(30)
    else:
        run_scanner()
