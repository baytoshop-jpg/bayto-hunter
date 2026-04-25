"""
CRYPTO FUTURES SCANNER v5.4 - RENDER DEPLOYMENT
"""
import time, json, os, requests
from datetime import datetime
from v5_engine import analyze_cascade, get_funding_rate, get_open_interest, SCORE_C

# Telegram settings (Render ENV se lega)
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')

def send_telegram(message):
    if TELEGRAM_TOKEN and CHAT_ID:
        try:
            requests.post(f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
                         json={'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'HTML'})
        except:
            pass

def get_top_gainers():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return []
    data = r.json()
    gainers = []
    for t in data:
        sym = t['symbol']
        if sym.endswith('USDT'):
            pct = float(t['priceChangePercent'])
            if abs(pct) > 3:
                gainers.append({'symbol': sym, 'change': pct})
    gainers.sort(key=lambda x: abs(x['change']), reverse=True)
    return gainers[:30]

def run():
    print(f"Scan at {datetime.now()}")
    gainers = get_top_gainers()
    if not gainers:
        print("No gainers")
        return
    
    gainers_set = {g['symbol'] for g in gainers}
    signals = []
    
    for g in gainers[:20]:
        r = analyze_cascade(g['symbol'], gainers_set)
        if r and r['score'] >= SCORE_C:
            signals.append(r)
    
    for s in signals[:3]:
        msg = f"""🟢 <b>{s['symbol']} - {s['direction']}</b>
🎯 Entry: {s['entry']}
🛡️ SL: {s['sl']}
📍 TP: {s['tp2']}
📊 Score: {s['score']}/50
🤖 BaytoHunter"""
        send_telegram(msg)

if __name__ == "__main__":
    print("Scanner Started on Render")
    while True:
        run()
        time.sleep(30 * 60)
