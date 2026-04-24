"""
v5_engine.py — Full Top-Down Analysis Engine
4H → 1H → 30m → 15m → 5m CASCADE
Sirf 5m pe entry — baaki sab confirmation
"""
import requests, pandas as pd, numpy as np, time

try:
    import ta
    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False

FAPI = "https://fapi.binance.com"

# ─── SCORING THRESHOLDS ──────────────────────────────────────
SCORE_A  = 20   # A+ setup  → 2-3% position
SCORE_B  = 15   # B  setup  → 1-2% position
SCORE_C  = 10   # C  setup  → 0.5-1%
MIN_RR   = 1.3  # Minimum Risk:Reward

# ─── TIMEFRAME CASCADE ───────────────────────────────────────
HTF   = [("4H","4h"), ("1H","1h")]          # Trend direction
MTF   = [("30m","30m"), ("15m","15m")]       # Confirmation
ENTRY = ("5m","5m")                          # Entry only

# ─── CANDLESTICK PATTERN STRENGTHS ───────────────────────────
PATTERN_STRENGTH = {
    "Morning Star":        4,
    "Evening Star":        4,
    "Hammer":              3,
    "Inverted Hammer":     3,
    "Bullish Engulfing":   3,
    "Bearish Engulfing":   3,
    "Shooting Star":       3,
    "Hanging Man":         3,
    "Piercing Line":       2,
    "Dark Cloud Cover":    2,
    "Doji":                2,
    "Dragonfly Doji":      2,
    "Gravestone Doji":     2,
    "Tweezer Bottom":      2,
    "Tweezer Top":         2,
}

# ─── BINANCE API ─────────────────────────────────────────────
def get_futures_symbols():
    try:
        r = requests.get(f"{FAPI}/fapi/v1/exchangeInfo", timeout=15)
        return sorted([s["symbol"] for s in r.json()["symbols"]
            if s["quoteAsset"]=="USDT"
            and s["status"]=="TRADING"
            and s["contractType"]=="PERPETUAL"])
    except:
        return ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
                "ADAUSDT","AVAXUSDT","DOGEUSDT","LINKUSDT","DOTUSDT"]

def get_top_volume(all_syms, top_n=50):
    try:
        r    = requests.get(f"{FAPI}/fapi/v1/ticker/24hr", timeout=15)
        vmap = {t["symbol"]:float(t["quoteVolume"])
                for t in r.json() if t["symbol"] in all_syms}
        return sorted(vmap, key=vmap.get, reverse=True)[:top_n]
    except:
        return all_syms[:top_n]

def get_top_gainers(all_syms):
    try:
        r = requests.get(f"{FAPI}/fapi/v1/ticker/24hr", timeout=15)
        return {t["symbol"] for t in r.json()
                if t["symbol"] in all_syms
                and abs(float(t["priceChangePercent"])) > 3}
    except:
        return set()

def get_klines(symbol, interval, limit=200):
    try:
        r = requests.get(f"{FAPI}/fapi/v1/klines",
            params={"symbol":symbol,"interval":interval,"limit":limit},
            timeout=10)
        r.raise_for_status()
        df = pd.DataFrame(r.json(), columns=[
            "time","open","high","low","close","volume",
            "close_time","qav","trades","tbbav","tbqav","ignore"])
        for c in ["open","high","low","close","volume"]:
            df[c] = df[c].astype(float)
        df["time"] = pd.to_datetime(df["time"], unit="ms")
        return df
    except:
        return None

def get_funding_rate(symbol):
    try:
        r    = requests.get(f"{FAPI}/fapi/v1/premiumIndex",
               params={"symbol":symbol}, timeout=10)
        rate = float(r.json().get("lastFundingRate",0))*100
        bias = "long_favored" if rate<-0.05 else ("short_favored" if rate>0.05 else "neutral")
        return {"rate":round(rate,4),"bias":bias}
    except:
        return {"rate":0,"bias":"neutral"}

def get_open_interest(symbol):
    try:
        r    = requests.get(f"{FAPI}/futures/data/openInterestHist",
               params={"symbol":symbol,"period":"1h","limit":3}, timeout=10)
        data = r.json()
        if not data or len(data)<2:
            return {"rising":None,"signal":"unknown"}
        rising = float(data[-1]["sumOpenInterest"]) > float(data[-2]["sumOpenInterest"])
        return {"rising":rising,"signal":"rising" if rising else "falling"}
    except:
        return {"rising":None,"signal":"unknown"}

# ─── INDICATORS ──────────────────────────────────────────────
def add_indicators(df):
    c,h,l,v = df["close"],df["high"],df["low"],df["volume"]
    if TA_AVAILABLE:
        df["ema20"]  = ta.trend.EMAIndicator(c,20).ema_indicator()
        df["ema50"]  = ta.trend.EMAIndicator(c,50).ema_indicator()
        df["ema200"] = ta.trend.EMAIndicator(c,200).ema_indicator()
        df["rsi"]    = ta.momentum.RSIIndicator(c,14).rsi()
        m=ta.trend.MACD(c)
        df["macd"]   = m.macd()
        df["macd_s"] = m.macd_signal()
        df["macd_h"] = m.macd_diff()
        df["atr"]    = ta.volatility.AverageTrueRange(h,l,c,14).average_true_range()
    else:
        df["ema20"]  = c.ewm(span=20).mean()
        df["ema50"]  = c.ewm(span=50).mean()
        df["ema200"] = c.ewm(span=200).mean()
        d=c.diff(); g=d.clip(lower=0).rolling(14).mean()
        ls=(-d.clip(upper=0)).rolling(14).mean()
        df["rsi"]    = 100-(100/(1+g/ls))
        fast=c.ewm(span=12).mean()-c.ewm(span=26).mean()
        df["macd_h"] = fast-fast.ewm(span=9).mean()
        df["atr"]    = (h-l).rolling(14).mean()
    df["vol_ma"] = v.rolling(20).mean()
    return df

# ─── HTF/MTF TREND ANALYSIS ──────────────────────────────────
def analyze_tf_trend(df):
    """
    Ek timeframe ka trend analyze karo
    Returns: direction, score_contribution, notes
    """
    if df is None or len(df)<50:
        return "neutral", 0, []

    df    = add_indicators(df)
    last  = df.iloc[-1]
    prev  = df.iloc[-2]
    price = last["close"]
    notes = []
    score = 0
    direction = "neutral"

    ema20  = last["ema20"]
    ema50  = last["ema50"]
    ema200 = last["ema200"]
    rsi    = last["rsi"]
    macd_h = last["macd_h"]
    pmh    = prev["macd_h"]

    # EMA trend
    if price > ema200:
        direction = "bullish"; score += 3; notes.append("Above EMA200")
    else:
        direction = "bearish"; score += 3; notes.append("Below EMA200")

    if ema20>ema50>ema200:
        score+=4; notes.append("EMA stack bullish")
    elif ema20<ema50<ema200:
        score+=4; notes.append("EMA stack bearish")

    # EMA bounce
    if direction=="bullish" and abs(price-ema20)/price<0.01:
        score+=2; notes.append("EMA20 bounce")
    elif direction=="bullish" and abs(price-ema50)/price<0.015:
        score+=2; notes.append("EMA50 support")

    # RSI
    if direction=="bullish":
        if 35<=rsi<=60: score+=2; notes.append(f"RSI {rsi:.0f} pullback")
        elif rsi<35:    score+=1; notes.append(f"RSI {rsi:.0f} oversold")
    else:
        if 55<=rsi<=75: score+=2; notes.append(f"RSI {rsi:.0f} overbought")
        elif rsi>75:    score+=1; notes.append(f"RSI {rsi:.0f} extreme OB")

    # MACD
    if macd_h>0 and pmh<=0:   score+=3; notes.append("MACD bull cross")
    elif macd_h<0 and pmh>=0: score+=3; notes.append("MACD bear cross")
    elif macd_h>0 and direction=="bullish": score+=1
    elif macd_h<0 and direction=="bearish": score+=1

    return direction, score, notes

# ─── SWING STRUCTURE ─────────────────────────────────────────
def get_swing_points(df, lb=5):
    hi, li = [], []
    n = len(df)
    for i in range(lb, n-lb):
        if df["high"].iloc[i]==df["high"].iloc[i-lb:i+lb+1].max(): hi.append(i)
        if df["low"].iloc[i] ==df["low"].iloc[i-lb:i+lb+1].min():  li.append(i)
    sh = [(i,df["high"].iloc[i]) for i in hi[-4:]]
    sl = [(i,df["low"].iloc[i])  for i in li[-4:]]

    s = {"HH":False,"HL":False,"LH":False,"LL":False,
         "last_sh":None,"last_sl":None,
         "strong_low":None,"strong_high":None}

    if len(sh)>=2:
        s["last_sh"] = sh[-1][1]
        s["HH"] = sh[-1][1]>sh[-2][1]
        s["LH"] = sh[-1][1]<=sh[-2][1]
        s["strong_high"] = sh[-2][1] if s["HH"] else sh[-1][1]

    if len(sl)>=2:
        s["last_sl"] = sl[-1][1]
        s["HL"] = sl[-1][1]>sl[-2][1]
        s["LL"] = sl[-1][1]<=sl[-2][1]
        s["strong_low"] = sl[-1][1] if s["HL"] else sl[-2][1]

    return s

# ─── S/R ZONES ───────────────────────────────────────────────
def find_sr_zones(df, lb=100, zone_pct=0.008, min_touches=2):
    rc   = df.tail(lb)
    price= df["close"].iloc[-1]
    ha,la= rc["high"].values, rc["low"].values
    cands= []

    for i in range(2,len(ha)-2):
        if ha[i]==max(ha[i-2:i+3]): cands.append(ha[i])
        if la[i]==min(la[i-2:i+3]): cands.append(la[i])

    zones=[]
    for lv in cands:
        zlo,zhi=lv*(1-zone_pct),lv*(1+zone_pct)
        t=sum(1 for i in range(len(rc))
              if zlo<=rc["high"].iloc[i]>=lv*0.999
              or zlo<=rc["low"].iloc[i]<=zhi)
        if t>=min_touches:
            zones.append({"level":round(lv,6),"touches":t,
                          "type":"resistance" if lv>price else "support"})

    merged=[]
    for z in sorted(zones,key=lambda x:x["level"]):
        if merged and abs(z["level"]-merged[-1]["level"])/merged[-1]["level"]<zone_pct:
            if z["touches"]>merged[-1]["touches"]: merged[-1]=z
        else: merged.append(z)
    return merged

# ─── ORDER BLOCKS ────────────────────────────────────────────
def find_order_blocks(df):
    res={"bull_ob":None,"bear_ob":None}
    rc=df.tail(30).reset_index(drop=True)
    for i in range(1,len(rc)-1):
        p=rc.iloc[i-1]; cur=rc.iloc[i]
        atr=rc["atr"].iloc[i] if "atr" in rc.columns else abs(cur["close"]-cur["open"])
        sz=abs(cur["close"]-cur["open"])
        if p["close"]<p["open"] and cur["close"]>cur["open"] and cur["close"]>p["high"] and sz>atr*0.7:
            res["bull_ob"]={"high":round(p["high"],6),"low":round(p["low"],6)}
        if p["close"]>p["open"] and cur["close"]<cur["open"] and cur["close"]<p["low"] and sz>atr*0.7:
            res["bear_ob"]={"high":round(p["high"],6),"low":round(p["low"],6)}
    return res

# ─── FVG ─────────────────────────────────────────────────────
def find_fvg(df):
    res={"bull_fvg":None,"bear_fvg":None}
    last=df.tail(8).reset_index(drop=True)
    for i in range(2,len(last)):
        c1,c3=last.iloc[i-2],last.iloc[i]
        if c1["high"]<c3["low"]:
            res["bull_fvg"]={"top":round(c3["low"],6),"bot":round(c1["high"],6)}
        if c1["low"]>c3["high"]:
            res["bear_fvg"]={"top":round(c1["low"],6),"bot":round(c3["high"],6)}
    return res

# ─── S/R FLIP ────────────────────────────────────────────────
def check_sr_flip(df, sr_zones):
    price  = df["close"].iloc[-1]
    prev3  = df["close"].iloc[-5] if len(df)>5 else price
    candle = df.iloc[-1]
    result = {"flipped":False,"level":None,"type":None,"retest":False}

    for z in sr_zones:
        lv  = z["level"]
        zlo = lv*0.9915; zhi = lv*1.0085

        if z["type"]=="resistance" and prev3<lv and price>lv*1.003:
            result={"flipped":True,"level":lv,"type":"r_to_s","retest":False}
            if zlo<=price<=zhi and candle["close"]>candle["open"]:
                result["retest"]=True

        elif z["type"]=="support" and prev3>lv and price<lv*0.997:
            result={"flipped":True,"level":lv,"type":"s_to_r","retest":False}
            if zlo<=price<=zhi and candle["close"]<candle["open"]:
                result["retest"]=True
    return result

# ─── LIQUIDITY SWEEP ─────────────────────────────────────────
def check_sweep(df):
    if len(df)<20: return {"swept":False}
    rc=df.tail(20); last=df.iloc[-1]
    h20=rc["high"].iloc[:-1].max(); l20=rc["low"].iloc[:-1].min()
    if last["low"]<l20 and last["close"]>l20 and last["close"]>last["open"]:
        return {"swept":True,"type":"bull","level":round(l20,6)}
    if last["high"]>h20 and last["close"]<h20 and last["close"]<last["open"]:
        return {"swept":True,"type":"bear","level":round(h20,6)}
    return {"swept":False}

# ─── PREMIUM/DISCOUNT ────────────────────────────────────────
def get_pd_zone(df, lb=100):
    rc=df.tail(lb); sh=rc["high"].max(); sl=rc["low"].min()
    p=df["close"].iloc[-1]; rng=sh-sl
    if rng==0: return "equilibrium",50
    pct=(p-sl)/rng*100
    return ("discount" if pct<37 else "premium" if pct>63 else "equilibrium"), round(pct,1)

# ─── EQH/EQL ─────────────────────────────────────────────────
def check_eqhl(df, lb=50, thresh=0.003):
    rc=df.tail(lb); hs=rc["high"].values; ls=rc["low"].values
    eqh=eql=None
    for i in range(len(hs)-1):
        for j in range(i+3,len(hs)):
            if abs(hs[i]-hs[j])/hs[i]<thresh: eqh=round((hs[i]+hs[j])/2,6)
    for i in range(len(ls)-1):
        for j in range(i+3,len(ls)):
            if abs(ls[i]-ls[j])/ls[i]<thresh: eql=round((ls[i]+ls[j])/2,6)
    return {"eqh":eqh,"eql":eql}

# ─── 5m CANDLESTICK PATTERNS ─────────────────────────────────
def detect_5m_candles(df):
    """
    10 candlestick patterns — sirf 5m ke liye
    Returns: list of (pattern_name, direction, strength)
    """
    found = []
    if len(df) < 4: return found

    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    atr = df["atr"].iloc[-1] if "atr" in df.columns else abs(c[-1]-o[-1])

    # Helper values — last 3 candles
    c1,o1,h1,l1 = c[-3],o[-3],h[-3],l[-3]   # 3 candles ago
    c2,o2,h2,l2 = c[-2],o[-2],h[-2],l[-2]   # 2 candles ago (prev)
    c3,o3,h3,l3 = c[-1],o[-1],h[-1],l[-1]   # Last (current)

    body3   = abs(c3-o3)
    body2   = abs(c2-o2)
    uw3     = h3 - max(c3,o3)
    lw3     = min(c3,o3) - l3
    total3  = h3-l3

    # ── 1. HAMMER (Bullish) ──────────────────────────────────
    # Long lower wick, small body at top, prev trend down
    if (lw3 > body3*2 and lw3 > uw3*2 and
            total3 > atr*0.5 and c2 < o2):
        found.append(("Hammer", "LONG", 3))

    # ── 2. INVERTED HAMMER / SHOOTING STAR ──────────────────
    if uw3 > body3*2 and uw3 > lw3*2 and total3 > atr*0.5:
        if c2 < o2:   # After downtrend = inverted hammer (bullish)
            found.append(("Inverted Hammer","LONG",3))
        elif c2 > o2: # After uptrend = shooting star (bearish)
            found.append(("Shooting Star","SHORT",3))

    # ── 3. HANGING MAN (Bearish — hammer shape in uptrend) ──
    if (lw3 > body3*2 and lw3 > uw3*2 and
            total3 > atr*0.5 and c2 > o2):
        found.append(("Hanging Man","SHORT",3))

    # ── 4. BULLISH ENGULFING ─────────────────────────────────
    if (c2<o2 and c3>o3 and
            o3<=c2 and c3>=o2 and
            body3 > body2*1.1):
        found.append(("Bullish Engulfing","LONG",3))

    # ── 5. BEARISH ENGULFING ─────────────────────────────────
    if (c2>o2 and c3<o3 and
            o3>=c2 and c3<=o2 and
            body3 > body2*1.1):
        found.append(("Bearish Engulfing","SHORT",3))

    # ── 6. DOJI ──────────────────────────────────────────────
    if body3 < total3*0.1 and total3 > atr*0.3:
        found.append(("Doji","reversal",2))

    # ── 7. DRAGONFLY DOJI (Bullish) ──────────────────────────
    if (body3 < total3*0.1 and lw3 > total3*0.6 and
            uw3 < total3*0.1):
        found.append(("Dragonfly Doji","LONG",2))

    # ── 8. GRAVESTONE DOJI (Bearish) ─────────────────────────
    if (body3 < total3*0.1 and uw3 > total3*0.6 and
            lw3 < total3*0.1):
        found.append(("Gravestone Doji","SHORT",2))

    # ── 9. MORNING STAR (3-candle, Bullish) ──────────────────
    # c1 bearish, c2 small body (indecision), c3 bullish
    if (c1<o1 and                              # Candle 1 bearish
            abs(c2-o2) < abs(c1-o1)*0.5 and   # Candle 2 small
            c3>o3 and                          # Candle 3 bullish
            c3 > (c1+o1)/2):                   # Close above midpoint
        found.append(("Morning Star","LONG",4))

    # ── 10. EVENING STAR (3-candle, Bearish) ─────────────────
    if (c1>o1 and
            abs(c2-o2) < abs(c1-o1)*0.5 and
            c3<o3 and
            c3 < (c1+o1)/2):
        found.append(("Evening Star","SHORT",4))

    # ── 11. PIERCING LINE (Bullish) ──────────────────────────
    if (c2<o2 and c3>o3 and
            o3<c2 and c3>(o2+c2)/2 and c3<o2):
        found.append(("Piercing Line","LONG",2))

    # ── 12. DARK CLOUD COVER (Bearish) ───────────────────────
    if (c2>o2 and c3<o3 and
            o3>c2 and c3<(o2+c2)/2 and c3>o2):
        found.append(("Dark Cloud Cover","SHORT",2))

    # ── 13. TWEEZER BOTTOM (Bullish) ─────────────────────────
    if (c2<o2 and c3>o3 and
            abs(l2-l3)/max(l2,l3,0.0001)<0.002):
        found.append(("Tweezer Bottom","LONG",2))

    # ── 14. TWEEZER TOP (Bearish) ────────────────────────────
    if (c2>o2 and c3<o3 and
            abs(h2-h3)/max(h2,h3,0.0001)<0.002):
        found.append(("Tweezer Top","SHORT",2))

    return found

# ─── 5m ENTRY ZONE CHECK ─────────────────────────────────────
def check_entry_zone(df, direction, sr_zones, ob, fvg):
    """
    Kya price S/R, OB, ya FVG ke paas hai?
    Entry zone mein hona zaroori hai
    """
    price = df["close"].iloc[-1]
    atr   = df["atr"].iloc[-1] if "atr" in df.columns else price*0.005
    zone  = atr * 1.5   # How close to a level

    zones_found = []

    # S/R check
    for z in sr_zones:
        if abs(price - z["level"]) <= zone:
            zones_found.append(f"S/R {z['type']} at {z['level']}")

    # OB check
    if direction=="LONG" and ob["bull_ob"]:
        ob_mid = (ob["bull_ob"]["high"]+ob["bull_ob"]["low"])/2
        if abs(price-ob_mid) <= zone*2:
            zones_found.append(f"Bullish OB {ob['bull_ob']['low']}-{ob['bull_ob']['high']}")

    if direction=="SHORT" and ob["bear_ob"]:
        ob_mid = (ob["bear_ob"]["high"]+ob["bear_ob"]["low"])/2
        if abs(price-ob_mid) <= zone*2:
            zones_found.append(f"Bearish OB {ob['bear_ob']['low']}-{ob['bear_ob']['high']}")

    # FVG check
    if direction=="LONG" and fvg["bull_fvg"]:
        fvg_mid = (fvg["bull_fvg"]["top"]+fvg["bull_fvg"]["bot"])/2
        if abs(price-fvg_mid) <= zone*2:
            zones_found.append(f"Bull FVG {fvg['bull_fvg']['bot']}-{fvg['bull_fvg']['top']}")

    if direction=="SHORT" and fvg["bear_fvg"]:
        fvg_mid = (fvg["bear_fvg"]["top"]+fvg["bear_fvg"]["bot"])/2
        if abs(price-fvg_mid) <= zone*2:
            zones_found.append(f"Bear FVG {fvg['bear_fvg']['bot']}-{fvg['bear_fvg']['top']}")

    return zones_found

# ─── DYNAMIC SL/TP (ATR Based) ───────────────────────────────
def calc_sl_tp(price, direction, atr):
    if direction=="LONG":
        sl  = round(price - atr*2.0, 6)
        tp1 = round(price + atr*1.5, 6)
        tp2 = round(price + atr*3.0, 6)
        tp3 = round(price + atr*4.5, 6)
    else:
        sl  = round(price + atr*2.0, 6)
        tp1 = round(price - atr*1.5, 6)
        tp2 = round(price - atr*3.0, 6)
        tp3 = round(price - atr*4.5, 6)

    risk  = abs(price-sl)
    rr_tp2 = round(abs(tp2-price)/risk, 2) if risk>0 else 0
    return sl, tp1, tp2, tp3, round(rr_tp2, 2)

# ─── MAIN: FULL CASCADE ANALYSIS ─────────────────────────────
def analyze_cascade(symbol, gainers_set=None):
    """
    TOP-DOWN: 4H → 1H → 30m → 15m → 5m
    Returns single best signal or None
    """

    # ── STEP 1: 4H + 1H TREND (HTF) ──────────────────────────
    htf_scores  = {}
    htf_dirs    = {}
    htf_notes   = {}

    for tf_label, tf_code in HTF:
        df = get_klines(symbol, tf_code, 150)
        if df is None: continue
        d, s, n = analyze_tf_trend(df)
        htf_dirs[tf_label]   = d
        htf_scores[tf_label] = s
        htf_notes[tf_label]  = n
        time.sleep(0.08)

    # Both HTF must agree
    h4_dir = htf_dirs.get("4H","neutral")
    h1_dir = htf_dirs.get("1H","neutral")

    if h4_dir == "neutral" or h1_dir == "neutral":
        return None
    if h4_dir != h1_dir and h4_dir != "neutral":
    return None   # HTF conflict — skip

    direction = "LONG" if h4_dir=="bullish" else "SHORT"
    htf_score = sum(htf_scores.values())

    # ── STEP 2: 30m + 15m CONFIRMATION (MTF) ─────────────────
    mtf_scores = {}
    mtf_dirs   = {}
    mtf_agrees = 0

    for tf_label, tf_code in MTF:
        df = get_klines(symbol, tf_code, 150)
        if df is None: continue
        d, s, n = analyze_tf_trend(df)
        mtf_dirs[tf_label]   = d
        mtf_scores[tf_label] = s
        if d == h4_dir:
            mtf_agrees += 1
        time.sleep(0.08)

    # At least 1 of 2 MTF must agree
    if mtf_agrees == 0:
        return None

    mtf_score = sum(mtf_scores.values())

    # ── STEP 3: 5m ENTRY ANALYSIS ────────────────────────────
    df5 = get_klines(symbol, "5m", 200)
    if df5 is None or len(df5)<50:
        return None
    df5 = add_indicators(df5)

    price = df5["close"].iloc[-1]
    atr   = df5["atr"].iloc[-1] if "atr" in df5.columns else price*0.005

    # 5m must also agree with HTF
    d5, s5, n5 = analyze_tf_trend(df5)
    if d5 not in ["neutral", h4_dir]:
        return None   # 5m contradicts — skip

    # ── STEP 4: SMC ON 5m ────────────────────────────────────
    sr5    = find_sr_zones(df5)
    ob5    = find_order_blocks(df5)
    fvg5   = find_fvg(df5)
    swing5 = get_swing_points(df5)
    flip5  = check_sr_flip(df5, sr5)
    sweep5 = check_sweep(df5)
    pd5, pd_pct = get_pd_zone(df5)
    eqhl5  = check_eqhl(df5)

    # Entry zone check — price near S/R, OB, or FVG
    entry_zones = check_entry_zone(df5, direction, sr5, ob5, fvg5)

    # ── STEP 5: 5m CANDLESTICK PATTERNS ─────────────────────
    candles = detect_5m_candles(df5)

    # Filter candles that match direction
    matching_candles = [
        c for c in candles
        if c[1]==direction or c[1]=="reversal"
    ]

    # At least 1 candlestick pattern required
    if not matching_candles:
        return None

    # Best candle (highest strength)
    best_candle = max(matching_candles, key=lambda x: x[2])

    # ── STEP 6: SCORING (0-50) ────────────────────────────────
    score = 0
    confirmations = []

    # HTF alignment (max 12)
    htf_pts = min(htf_score, 12)
    score += htf_pts
    confirmations.append(f"4H {h4_dir} + 1H {h1_dir} aligned")

    # MTF confirmation (max 8)
    mtf_pts = min(int(mtf_score*0.4), 8)
    score += mtf_pts
    if mtf_agrees==2:
        confirmations.append("30m + 15m both confirm")
    else:
        confirmations.append(f"{'30m' if mtf_dirs.get('30m')==h4_dir else '15m'} confirms")

    # Candlestick (max 8)
    candle_pts = best_candle[2] * 2
    score += candle_pts
    confirmations.append(f"5m: {best_candle[0]} (strength {best_candle[2]})")

    # Entry zone (max 6)
    if entry_zones:
        score += min(len(entry_zones)*3, 6)
        confirmations.append(f"Entry zone: {entry_zones[0]}")

    # S/R Flip + Retest (max 6)
    if flip5["retest"] and flip5["flipped"]:
        score += 6
        ft = "R→S" if flip5["type"]=="r_to_s" else "S→R"
        confirmations.append(f"S/R Flip Retest: {ft} at {flip5['level']}")
    elif flip5["flipped"]:
        score += 2
        confirmations.append(f"S/R Flip: {flip5['level']}")

    # Liquidity sweep (max 4)
    if sweep5["swept"]:
        if (sweep5["type"]=="bull" and direction=="LONG") or \
           (sweep5["type"]=="bear" and direction=="SHORT"):
            score += 4
            confirmations.append(f"Liquidity sweep at {sweep5['level']}")

    # Premium/Discount (max 4)
    if direction=="LONG"  and pd5=="discount":
        score+=4; confirmations.append(f"Discount zone {pd_pct}%")
    elif direction=="SHORT" and pd5=="premium":
        score+=4; confirmations.append(f"Premium zone {pd_pct}%")

    # Swing structure (max 4)
    if direction=="LONG":
        if swing5["HH"] and swing5["HL"]:
            score+=4; confirmations.append("5m HH+HL bullish structure")
        elif swing5["HL"]:
            score+=2; confirmations.append("5m Higher Low")
        if swing5["strong_low"] and abs(price-swing5["strong_low"])/price<0.012:
            score+=2; confirmations.append(f"Strong Low: {swing5['strong_low']}")
    else:
        if swing5["LH"] and swing5["LL"]:
            score+=4; confirmations.append("5m LH+LL bearish structure")
        elif swing5["LH"]:
            score+=2; confirmations.append("5m Lower High")
        if swing5["strong_high"] and abs(price-swing5["strong_high"])/price<0.012:
            score+=2; confirmations.append(f"Strong High: {swing5['strong_high']}")

    # EQH/EQL (max 2)
    if direction=="LONG" and eqhl5["eql"] and abs(price-eqhl5["eql"])/price<0.012:
        score+=2; confirmations.append(f"EQL liquidity: {eqhl5['eql']}")
    if direction=="SHORT" and eqhl5["eqh"] and abs(price-eqhl5["eqh"])/price<0.012:
        score+=2; confirmations.append(f"EQH liquidity: {eqhl5['eqh']}")

    # Gainer bonus (max 2)
    is_gainer = bool(gainers_set and symbol in gainers_set)
    if is_gainer:
        score+=2; confirmations.append("Top gainer momentum")

    score = min(score, 50)

    # ── STEP 7: SKIP IF BELOW MINIMUM ────────────────────────
    if score < SCORE_C:
        return None

    # ── STEP 8: SL/TP + R:R CHECK ────────────────────────────
    sl, tp1, tp2, tp3, rr = calc_sl_tp(price, direction, atr)

    if rr < MIN_RR:
        return None   # R:R too low

    # ── STEP 9: GRADE + POSITION SIZE ────────────────────────
    if score >= SCORE_A:
        grade = "A+"; pos_size = "2-3%"
    elif score >= SCORE_B:
        grade = "B";  pos_size = "1-2%"
    else:
        grade = "C";  pos_size = "0.5-1%"

    # HTF notes summary
    h4_note = " | ".join(htf_notes.get("4H",[])[:2])
    h1_note = " | ".join(htf_notes.get("1H",[])[:2])

    return {
        "symbol":       symbol,
        "direction":    direction,
        "grade":        grade,
        "score":        score,
        "pos_size":     pos_size,
        "price":        round(price, 6),
        "entry":        round(price, 6),
        "sl":           sl,
        "tp1":          tp1,
        "tp2":          tp2,
        "tp3":          tp3,
        "rr":           rr,
        "atr":          round(atr, 6),
        "candle":       best_candle[0],
        "candle_str":   best_candle[2],
        "all_candles":  [c[0] for c in matching_candles],
        "confirmations":confirmations,
        "h4_trend":     h4_dir,
        "h1_trend":     h1_dir,
        "h4_note":      h4_note,
        "h1_note":      h1_note,
        "mtf_agrees":   mtf_agrees,
        "entry_zones":  entry_zones,
        "pd_zone":      pd5,
        "pd_pct":       pd_pct,
        "flip":         flip5,
        "sweep":        sweep5,
        "eqhl":         eqhl5,
        "is_gainer":    is_gainer,
    }
