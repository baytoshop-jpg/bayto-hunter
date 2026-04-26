# scanner_core.py
import requests, pandas as pd, numpy as np, time, json, os
from datetime import datetime

FAPI = "https://fapi.binance.com"
TELEGRAM_TOKEN = "8669042447:AAEXQrILOCgj5S89baTL1eMo42rr7luu5M8"
CHAT_ID = "1255000050"
LEARNING_FILE = "strategy_learning.json"
SENT_FILE = "sent_signals.json"

# -------------------------------------------------
def safe_float(x):
    try:
        if isinstance(x, dict):
            return 0.0
        return float(x)
    except:
        return 0.0

def get_klines(symbol, interval, limit=150):
    try:
        url = f"{FAPI}/fapi/v1/klines"
        r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        df = pd.DataFrame(data, columns=["time","open","high","low","close","volume",
                                         "ct","qav","trades","tbbav","tbqav","ignore"])
        for col in ["open","high","low","close","volume"]:
            df[col] = df[col].apply(safe_float)
        return df
    except:
        return None

def get_top_gainers(limit=30):
    try:
        url = f"{FAPI}/fapi/v1/ticker/24hr"
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            print(f"  API status {r.status_code}")
            return []
        data = r.json()
        if not isinstance(data, list):
            print("  Unexpected response")
            return []
        gainers = []
        for t in data:
            sym = t.get('symbol')
            if sym and sym.endswith('USDT'):
                try:
                    pct = safe_float(t.get('priceChangePercent', 0))
                    vol = safe_float(t.get('quoteVolume', 0))
                    if vol > 100000:   # volume threshold low enough
                        gainers.append({'symbol': sym, 'change': pct})
                except:
                    continue
        gainers.sort(key=lambda x: abs(x['change']), reverse=True)
        if not gainers:
            # fallback – just top volume coins
            sorted_by_vol = sorted([t for t in data if t.get('symbol', '').endswith('USDT')],
                                   key=lambda x: safe_float(x.get('quoteVolume', 0)), reverse=True)
            for t in sorted_by_vol[:limit]:
                sym = t.get('symbol')
                if sym:
                    gainers.append({'symbol': sym, 'change': safe_float(t.get('priceChangePercent', 0))})
        return gainers[:limit]
    except Exception as e:
        print(f"  Error in get_top_gainers: {e}")
        return []

def calculate_ema(df, period):
    return df['close'].ewm(span=period, adjust=False).mean()

def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_atr(df, period=14):
    high = df['high']
    low = df['low']
    close = df['close']
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def find_sr_levels(df):
    price = df['close'].iloc[-1]
    levels = []
    for i in range(5, len(df)-5):
        h = df['high'].iloc[i]
        l = df['low'].iloc[i]
        if h == df['high'].iloc[i-5:i+6].max():
            levels.append({'level': h, 'type': 'resistance'})
        if l == df['low'].iloc[i-5:i+6].min():
            levels.append({'level': l, 'type': 'support'})
    return levels

def find_order_blocks(df):
    ob = {'bullish': None, 'bearish': None}
    for i in range(2, len(df)-2):
        if (df['close'].iloc[i-1] < df['open'].iloc[i-1] and
            df['close'].iloc[i] > df['open'].iloc[i] and
            df['close'].iloc[i] > df['high'].iloc[i-1]):
            ob['bullish'] = {'high': df['high'].iloc[i-1], 'low': df['low'].iloc[i-1]}
        if (df['close'].iloc[i-1] > df['open'].iloc[i-1] and
            df['close'].iloc[i] < df['open'].iloc[i] and
            df['close'].iloc[i] < df['low'].iloc[i-1]):
            ob['bearish'] = {'high': df['high'].iloc[i-1], 'low': df['low'].iloc[i-1]}
    return ob

def find_fvg(df):
    fvg = {'bullish': None, 'bearish': None}
    for i in range(2, len(df)-2):
        if df['low'].iloc[i] > df['high'].iloc[i-2]:
            fvg['bullish'] = {'top': df['low'].iloc[i], 'bottom': df['high'].iloc[i-2]}
        if df['high'].iloc[i] < df['low'].iloc[i-2]:
            fvg['bearish'] = {'top': df['high'].iloc[i-2], 'bottom': df['low'].iloc[i]}
    return fvg

def check_candle(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    body = abs(last['close'] - last['open'])
    lw = min(last['close'], last['open']) - last['low']
    uw = last['high'] - max(last['close'], last['open'])
    total = last['high'] - last['low']
    if total == 0:
        return None
    if lw > body*2 and uw < body*0.5:
        return "Hammer"
    if uw > body*2 and lw < body*0.5:
        return "Shooting Star"
    if prev['close'] < prev['open'] and last['close'] > last['open'] and last['close'] > prev['open'] and last['open'] < prev['close']:
        return "Bullish Engulfing"
    if prev['close'] > prev['open'] and last['close'] < last['open'] and last['close'] < prev['open'] and last['open'] > prev['close']:
        return "Bearish Engulfing"
    return None

# ------------------- strategy checks -------------------
def check_sr(df, price, direction):
    price = float(price)
    for lv in find_sr_levels(df):
        lvl = float(lv['level'])
        if abs(price-lvl)/price < 0.005:
            if direction=="LONG" and lv['type']=='support':
                return True, f"S/R Support {lvl:.4f}"
            if direction=="SHORT" and lv['type']=='resistance':
                return True, f"S/R Resistance {lvl:.4f}"
    return False, None

def check_ob(df, price, direction):
    price = float(price)
    ob = find_order_blocks(df)
    if direction=="LONG" and ob['bullish']:
        lvl = float(ob['bullish']['high'])
        if abs(price-lvl)/price < 0.005:
            return True, f"Bullish OB {lvl:.4f}"
    if direction=="SHORT" and ob['bearish']:
        lvl = float(ob['bearish']['low'])
        if abs(price-lvl)/price < 0.005:
            return True, f"Bearish OB {lvl:.4f}"
    return False, None

def check_fvg(df, price, direction):
    price = float(price)
    fvg = find_fvg(df)
    if direction=="LONG" and fvg['bullish']:
        if price <= float(fvg['bullish']['top']):
            return True, "Bullish FVG"
    if direction=="SHORT" and fvg['bearish']:
        if price >= float(fvg['bearish']['bottom']):
            return True, "Bearish FVG"
    return False, None

def check_ema(df, direction):
    ema20 = calculate_ema(df,20).iloc[-1]
    ema50 = calculate_ema(df,50).iloc[-1]
    ema200 = calculate_ema(df,200).iloc[-1]
    price = df['close'].iloc[-1]
    if direction=="LONG":
        if price > ema20 > ema50 > ema200:
            return True, "EMA Golden Stack"
        if abs(price-ema20)/price < 0.01:
            return True, "EMA20 Support"
    else:
        if price < ema20 < ema50 < ema200:
            return True, "EMA Death Stack"
        if abs(price-ema20)/price < 0.01:
            return True, "EMA20 Resistance"
    return False, None

def check_breakout(df, price, direction):
    price = float(price)
    high20 = float(df['high'].iloc[-20:-1].max())
    low20 = float(df['low'].iloc[-20:-1].min())
    prev_close = float(df['close'].iloc[-2])
    if direction=="LONG" and prev_close > high20*0.998 and abs(price-high20)/price < 0.015:
        return True, "Breakout + Retest"
    if direction=="SHORT" and prev_close < low20*1.002 and abs(price-low20)/price < 0.015:
        return True, "Breakdown + Retest"
    return False, None

def check_pattern(df, direction):
    c = check_candle(df)
    if direction=="LONG" and c in ["Hammer","Bullish Engulfing"]:
        return True, f"Pattern: {c}"
    if direction=="SHORT" and c in ["Shooting Star","Bearish Engulfing"]:
        return True, f"Pattern: {c}"
    return False, None

def check_rsi(df, direction):
    rsi = calculate_rsi(df).iloc[-1]
    if direction=="LONG" and 30 <= rsi <= 50:
        return True, f"RSI {rsi:.1f} (Pullback)"
    if direction=="LONG" and rsi < 30:
        return True, f"RSI {rsi:.1f} (Oversold)"
    if direction=="SHORT" and 50 <= rsi <= 70:
        return True, f"RSI {rsi:.1f} (Overbought)"
    if direction=="SHORT" and rsi > 70:
        return True, f"RSI {rsi:.1f} (Overbought)"
    return False, None

# ------------------- main analysis -------------------
def analyze_symbol(symbol):
    try:
        df4 = get_klines(symbol, "4h", 150)
        df1 = get_klines(symbol, "1h", 150)
        df15 = get_klines(symbol, "15m", 100)
        if df4 is None or df1 is None or df15 is None:
            return None

        ema20_4 = calculate_ema(df4,20).iloc[-1]
        ema50_4 = calculate_ema(df4,50).iloc[-1]
        price4 = df4['close'].iloc[-1]
        ema20_1 = calculate_ema(df1,20).iloc[-1]
        ema50_1 = calculate_ema(df1,50).iloc[-1]
        price1 = df1['close'].iloc[-1]

        trend4 = "bullish" if price4 > ema20_4 > ema50_4 else "bearish" if price4 < ema20_4 < ema50_4 else "neutral"
        trend1 = "bullish" if price1 > ema20_1 > ema50_1 else "bearish" if price1 < ema20_1 < ema50_1 else "neutral"

        if trend4 == "neutral" or trend1 == "neutral" or trend4 != trend1:
            return None

        direction = "LONG" if trend4 == "bullish" else "SHORT"
        price = float(df15['close'].iloc[-1])

        strategies = []
        sr_ok, _ = check_sr(df15, price, direction)
        if sr_ok: strategies.append("S/R Level")
        ob_ok, _ = check_ob(df15, price, direction)
        if ob_ok: strategies.append("Order Block")
        fvg_ok, _ = check_fvg(df15, price, direction)
        if fvg_ok: strategies.append("FVG")
        ema_ok, _ = check_ema(df15, direction)
        if ema_ok: strategies.append("EMA")
        bo_ok, _ = check_breakout(df15, price, direction)
        if bo_ok: strategies.append("Breakout")
        pat_ok, _ = check_pattern(df15, direction)
        if pat_ok: strategies.append("Pattern")
        rsi_ok, _ = check_rsi(df15, direction)
        if rsi_ok: strategies.append("RSI")

        if len(strategies) < 3:
            return None

        atr_val = calculate_atr(df15).iloc[-1]
        if pd.isna(atr_val) or atr_val == 0:
            atr_val = price * 0.01
        atr_val = float(atr_val)

        if direction == "LONG":
            sl = round(price - atr_val * 1.5, 6)
            tp = round(price + atr_val * 3, 6)
        else:
            sl = round(price + atr_val * 1.5, 6)
            tp = round(price - atr_val * 3, 6)

        rr = round(abs(tp - price) / abs(price - sl), 2)
        grade = "A+ 🔥" if len(strategies) >= 5 else "A ✅" if len(strategies) >= 4 else "B 📊"

        return {
            "symbol": symbol,
            "direction": direction,
            "grade": grade,
            "score": len(strategies),
            "strategies": strategies,
            "entry": round(price,6),
            "sl": sl,
            "tp": tp,
            "rr": rr
        }
    except Exception:
        return None

# ------------------- telegram helpers -------------------
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'HTML'}, timeout=15)
    except:
        pass

def is_dup(symbol, direction):
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE,'r') as f:
            d = json.load(f)
        key = f"{symbol}_{direction}"
        if key in d and (time.time() - d[key]) / 3600 < 4:
            return True
    return False

def mark_sent(symbol, direction):
    d = {}
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE,'r') as f:
            d = json.load(f)
    d[f"{symbol}_{direction}"] = time.time()
    with open(SENT_FILE,'w') as f:
        json.dump(d, f)

def learn_outcome(symbol, direction, strategies, outcome):
    # placeholder
    pass
