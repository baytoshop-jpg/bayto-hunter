"""
v5_engine.py — COMPLETE UPDATED VERSION
4H → 1H → 5m CASCADE with Self-Learning
"""
import requests, pandas as pd, numpy as np, time
import json, os
from datetime import datetime, timedelta

try:
    import ta
    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False

FAPI = "https://fapi.binance.com"

# ─── SCORING THRESHOLDS ──────────────────────────────────────
SCORE_A = 12
SCORE_B = 8
SCORE_C = 5
MIN_RR = 1.0

# ─── TIMEFRAME CASCADE ───────────────────────────────────────
HTF = [("4H", "4h"), ("1H", "1h")]

# ─── SELF-LEARNING MEMORY ───────────────────────────────────
MEMORY_FILE = "signal_memory.json"

def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {"successful_patterns": {}, "failed_patterns": {}}

def save_memory(memory):
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)

def get_pattern_score(pattern):
    memory = load_memory()
    wins = memory["successful_patterns"].get(pattern, 0)
    losses = memory["failed_patterns"].get(pattern, 0)
    total = wins + losses
    if total == 0:
        return 0.5
    return wins / total

def adjust_score_with_learning(score, pattern):
    success_rate = get_pattern_score(pattern)
    if success_rate > 0.7:
        return score + 3
    elif success_rate < 0.3:
        return score - 3
    return score

def learn_outcome(symbol, direction, pattern, outcome):
    memory = load_memory()
    if outcome == "win":
        memory["successful_patterns"][pattern] = memory["successful_patterns"].get(pattern, 0) + 1
    elif outcome == "loss":
        memory["failed_patterns"][pattern] = memory["failed_patterns"].get(pattern, 0) + 1
    save_memory(memory)

# ─── FETCH SYMBOLS ───────────────────────────────────────────
def get_futures_symbols():
    endpoints = [
        "https://fapi.binance.com/fapi/v1/exchangeInfo",
        "https://api.binance.com/api/v3/exchangeInfo",
    ]
    for endpoint in endpoints:
        try:
            r = requests.get(endpoint, timeout=30)
            if r.status_code == 200:
                data = r.json()
                symbols_data = data.get('symbols', [])
                if symbols_data:
                    syms = []
                    for s in symbols_data:
                        if (s.get('quoteAsset') == 'USDT' and 
                            s.get('status') == 'TRADING'):
                            if s.get('contractType') == 'PERPETUAL' or 'contractType' not in s:
                                syms.append(s['symbol'])
                    if len(syms) > 50:
                        return sorted(syms)
        except:
            continue
    
    # Fallback list
    return [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
        "ADAUSDT", "AVAXUSDT", "DOGEUSDT", "LINKUSDT", "DOTUSDT",
        "WIFUSDT", "PEPEUSDT", "SHIBUSDT", "BONKUSDT", "FLOKIUSDT",
        "APEUSDT", "KATUSDT", "ENAUSDT", "FETUSDT", "WLDUSDT",
        "SEIUSDT", "SUIUSDT", "ARBUSDT", "OPUSDT", "INJUSDT",
    ]

# ─── TOP GAINERS ─────────────────────────────────────────────
def get_top_gainers(all_syms):
    try:
        r = requests.get(f"{FAPI}/fapi/v1/ticker/24hr", timeout=15)
        if r.status_code != 200:
            return set()
        gainers = set()
        for t in r.json():
            sym = t.get('symbol')
            if sym in all_syms:
                try:
                    pct = float(t.get('priceChangePercent', 0))
                    if abs(pct) > 3:
                        gainers.add(sym)
                except:
                    pass
        return gainers
    except:
        return set()

def get_top_volume(all_syms, top_n=50):
    try:
        r = requests.get(f"{FAPI}/fapi/v1/ticker/24hr", timeout=15)
        if r.status_code != 200:
            return all_syms[:top_n]
        vmap = {}
        for t in r.json():
            sym = t.get('symbol')
            if sym in all_syms:
                try:
                    vmap[sym] = float(t.get('quoteVolume', 0))
                except:
                    pass
        if not vmap:
            return all_syms[:top_n]
        return sorted(vmap, key=vmap.get, reverse=True)[:top_n]
    except:
        return all_syms[:top_n]

# ─── KLINES ──────────────────────────────────────────────────
def get_klines(symbol, interval, limit=200):
    try:
        r = requests.get(f"{FAPI}/fapi/v1/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10)
        if r.status_code != 200:
            return None
        df = pd.DataFrame(r.json(), columns=[
            "time", "open", "high", "low", "close", "volume",
            "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"])
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = df[c].astype(float)
        df["time"] = pd.to_datetime(df["time"], unit="ms")
        return df
    except:
        return None

# ─── FUNDING RATE ────────────────────────────────────────────
def get_funding_rate(symbol):
    try:
        r = requests.get(f"{FAPI}/fapi/v1/premiumIndex",
               params={"symbol": symbol}, timeout=10)
        if r.status_code != 200:
            return {"rate": 0, "bias": "neutral"}
        rate = float(r.json().get("lastFundingRate", 0)) * 100
        return {"rate": round(rate, 4), "bias": "neutral"}
    except:
        return {"rate": 0, "bias": "neutral"}

def get_open_interest(symbol):
    try:
        r = requests.get(f"{FAPI}/futures/data/openInterestHist",
               params={"symbol": symbol, "period": "1h", "limit": 3}, timeout=10)
        if r.status_code != 200:
            return {"signal": "unknown"}
        data = r.json()
        if not data or len(data) < 2:
            return {"signal": "unknown"}
        rising = float(data[-1]["sumOpenInterest"]) > float(data[-2]["sumOpenInterest"])
        return {"signal": "rising" if rising else "falling"}
    except:
        return {"signal": "unknown"}

# ─── INDICATORS ──────────────────────────────────────────────
def add_indicators(df):
    c, h, l = df["close"], df["high"], df["low"]
    if TA_AVAILABLE:
        df["ema20"] = ta.trend.EMAIndicator(c, 20).ema_indicator()
        df["ema50"] = ta.trend.EMAIndicator(c, 50).ema_indicator()
        df["ema200"] = ta.trend.EMAIndicator(c, 200).ema_indicator()
        df["rsi"] = ta.momentum.RSIIndicator(c, 14).rsi()
        m = ta.trend.MACD(c)
        df["macd_h"] = m.macd_diff()
        df["atr"] = ta.volatility.AverageTrueRange(h, l, c, 14).average_true_range()
    else:
        df["ema20"] = c.ewm(span=20).mean()
        df["ema50"] = c.ewm(span=50).mean()
        df["ema200"] = c.ewm(span=200).mean()
        d = c.diff()
        g = d.clip(lower=0).rolling(14).mean()
        ls = (-d.clip(upper=0)).rolling(14).mean()
        df["rsi"] = 100 - (100 / (1 + g / ls))
        fast = c.ewm(span=12).mean() - c.ewm(span=26).mean()
        df["macd_h"] = fast - fast.ewm(span=9).mean()
        df["atr"] = (h - l).rolling(14).mean()
    return df

# ─── TREND ANALYSIS ──────────────────────────────────────────
def analyze_tf_trend(df):
    if df is None or len(df) < 50:
        return "neutral", 0, []

    df = add_indicators(df)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    price = last["close"]
    notes = []
    score = 0
    direction = "neutral"

    ema200 = last["ema200"]
    macd_h = last["macd_h"]
    pmh = prev["macd_h"]

    if price > ema200:
        direction = "bullish"
        score += 3
    else:
        direction = "bearish"
        score += 3

    if macd_h > 0 and pmh <= 0:
        score += 3
    elif macd_h < 0 and pmh >= 0:
        score += 3

    return direction, score, notes

# ─── CANDLESTICK PATTERNS ────────────────────────────────────
def detect_5m_candles(df):
    found = []
    if len(df) < 20:
        return found
    
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    
    high20 = max(h[-20:-1])
    low20 = min(l[-20:-1])
    price = c[-1]
    prev = c[-2]
    
    # Breakout + Retest
    if prev > high20 * 0.998:
        if abs(price - high20) / price < 0.015 and c[-1] > o[-1]:
            found.append(("Breakout Retest Bullish", "LONG", 4))
    
    if prev < low20 * 1.002:
        if abs(price - low20) / price < 0.015 and c[-1] < o[-1]:
            found.append(("Breakdown Retest Bearish", "SHORT", 4))
    
    # Engulfing
    body3 = abs(c[-1] - o[-1])
    body2 = abs(c[-2] - o[-2])
    if (c[-2] < o[-2] and c[-1] > o[-1] and
            c[-1] > o[-2] and o[-1] < c[-2] and body3 > body2):
        found.append(("Bullish Engulfing", "LONG", 3))
    if (c[-2] > o[-2] and c[-1] < o[-1] and
            c[-1] < o[-2] and o[-1] > c[-2] and body3 > body2):
        found.append(("Bearish Engulfing", "SHORT", 3))
    
    # Hammer / Shooting Star
    uw = h[-1] - max(c[-1], o[-1])
    lw = min(c[-1], o[-1]) - l[-1]
    tot = h[-1] - l[-1]
    if tot > 0:
        if lw > body3 * 2 and lw > uw * 2 and c[-2] < o[-2]:
            found.append(("Hammer", "LONG", 3))
        if uw > body3 * 2 and uw > lw * 2 and c[-2] > o[-2]:
            found.append(("Shooting Star", "SHORT", 3))
    
    return found

def calc_sl_tp(price, direction, atr):
    if direction == "LONG":
        sl = round(price - atr * 2.0, 6)
        tp1 = round(price + atr * 1.5, 6)
        tp2 = round(price + atr * 3.0, 6)
        tp3 = round(price + atr * 4.5, 6)
    else:
        sl = round(price + atr * 2.0, 6)
        tp1 = round(price - atr * 1.5, 6)
        tp2 = round(price - atr * 3.0, 6)
        tp3 = round(price - atr * 4.5, 6)
    risk = abs(price - sl)
    rr = round(abs(tp2 - price) / risk, 2) if risk > 0 else 0
    return sl, tp1, tp2, tp3, rr

# ─── MAIN ANALYSIS ───────────────────────────────────────────
def analyze_cascade(symbol, gainers_set=None):
    """4H → 1H → 5m cascade analysis"""
    
    # HTF: 4H + 1H
    htf_dirs = {}
    htf_scores = {}
    
    for tf_label, tf_code in [("4H", "4h"), ("1H", "1h")]:
        df = get_klines(symbol, tf_code, 150)
        if df is None:
            return None
        d, s, _ = analyze_tf_trend(df)
        htf_dirs[tf_label] = d
        htf_scores[tf_label] = s
        time.sleep(0.08)
    
    h4_dir = htf_dirs.get("4H", "neutral")
    h1_dir = htf_dirs.get("1H", "neutral")
    
    if h4_dir == "neutral" and h1_dir == "neutral":
        return None
    
    direction = "LONG" if (h4_dir == "bullish" or h1_dir == "bullish") else "SHORT"
    htf_score = sum(htf_scores.values())
    
    # 5m Entry
    df5 = get_klines(symbol, "5m", 200)
    if df5 is None or len(df5) < 50:
        return None
    df5 = add_indicators(df5)
    
    price = df5["close"].iloc[-1]
    atr = df5["atr"].iloc[-1] if "atr" in df5.columns else price * 0.005
    
    d5, s5, _ = analyze_tf_trend(df5)
    if d5 not in ["neutral", h4_dir]:
        return None
    
    # Candlestick pattern
    candles = detect_5m_candles(df5)
    matching = [c for c in candles if c[1] == direction]
    
    if not matching:
        return None
    
    best_candle = max(matching, key=lambda x: x[2])
    pattern_name = best_candle[0]
    
    # Score calculation
    score = min(htf_score, 12)
    score += min(best_candle[2] * 2, 8)
    
    # Learning adjustment
    score = adjust_score_with_learning(score, pattern_name)
    
    # Gainer bonus
    is_gainer = bool(gainers_set and symbol in gainers_set)
    if is_gainer:
        score += 3
    
    if score < SCORE_C:
        return None
    
    # SL/TP
    sl, tp1, tp2, tp3, rr = calc_sl_tp(price, direction, atr)
    
    if rr < MIN_RR:
        return None
    
    # Grade
    if score >= SCORE_A:
        grade = "A+"
    elif score >= SCORE_B:
        grade = "B"
    else:
        grade = "C"
    
    confirmations = [
        f"4H {h4_dir} + 1H {h1_dir} aligned",
        f"5m: {pattern_name}",
    ]
    if is_gainer:
        confirmations.append("Top gainer momentum")
    
    return {
        "symbol": symbol,
        "direction": direction,
        "grade": grade,
        "score": score,
        "price": round(price, 6),
        "entry": round(price, 6),
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr": rr,
        "candle": pattern_name,
        "confirmations": confirmations,
        "h4_trend": h4_dir,
        "h1_trend": h1_dir,
        "is_gainer": is_gainer,
    }
