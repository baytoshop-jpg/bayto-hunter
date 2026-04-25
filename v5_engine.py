"""
v5_engine.py — FIXED + ENHANCED Top-Down Analysis Engine
4H → 1H → 30m → 15m → 5m CASCADE
FIXED: Indentation, None checks, missing variables
ADDED: Multiple timeframe confluence scoring
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
    for attempt in range(3):
        try:
            r = requests.get(f"{FAPI}/fapi/v1/exchangeInfo", timeout=30)
            syms = [
                s["symbol"] for s in r.json()["symbols"]
                if s["quoteAsset"]=="USDT"
                and s["status"]=="TRADING"
                and s["contractType"]=="PERPETUAL"
            ]
            if len(syms) > 50:
                print(f"  Binance API: {len(syms)} pairs mile!")
                return sorted(syms)
        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}")
            time.sleep(3)
    
    print("  API nahi mili — large fallback list use ho rahi hai")
    return [
        "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
        "ADAUSDT","AVAXUSDT","DOGEUSDT","LINKUSDT","DOTUSDT",
        "MATICUSDT","LTCUSDT","ATOMUSDT","NEARUSDT","APTUSDT",
        "ARBUSDT","OPUSDT","INJUSDT","SUIUSDT","TIAUSDT",
        "WIFUSDT","PEPEUSDT","SHIBUSDT","TONUSDT","FETUSDT",
        "RENDERUSDT","STXUSDT","RUNEUSDT","LDOUSDT","ORDIUSDT",
        "SEIUSDT","TRBUSDT","WLDUSDT","BLURUSDT","CFXUSDT",
    ]

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
        d=c.diff()
        g=d.clip(lower=0).rolling(14).mean()
        ls=(-d.clip(upper=0)).rolling(14).mean()
        df["rsi"]    = 100-(100/(1+g/ls))
        fast=c.ewm(span=12).mean()-c.ewm(span=26).mean()
        df["macd_h"] = fast-fast.ewm(span=9).mean()
        df["atr"]    = (h-l).rolling(14).mean()
    df["vol_ma"] = v.rolling(20).mean()
    return df

# ─── HTF/MTF TREND ANALYSIS ──────────────────────────────────
def analyze_tf_trend(df):
    """Ek timeframe ka trend analyze karo"""
    # FIXED: Agar df None hai to pehle hi return
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

    if price > ema200:
        direction = "bullish"
        score += 3
        notes.append("Above EMA200")
    else:
        direction = "bearish"
        score += 3
        notes.append("Below EMA200")

    if ema20>ema50>ema200:
        score+=4
        notes.append("EMA stack bullish")
    elif ema20<ema50<ema200:
        score+=4
        notes.append("EMA stack bearish")

    if direction=="bullish" and abs(price-ema20)/price<0.01:
        score+=2
        notes.append("EMA20 bounce")
    elif direction=="bullish" and abs(price-ema50)/price<0.015:
        score+=2
        notes.append("EMA50 support")

    if direction=="bullish":
        if 35<=rsi<=60:
            score+=2
            notes.append(f"RSI {rsi:.0f} pullback")
        elif rsi<35:
            score+=1
            notes.append(f"RSI {rsi:.0f} oversold")
    else:
        if 55<=rsi<=75:
            score+=2
            notes.append(f"RSI {rsi:.0f} overbought")
        elif rsi>75:
            score+=1
            notes.append(f"RSI {rsi:.0f} extreme OB")

    if macd_h>0 and pmh<=0:
        score+=3
        notes.append("MACD bull cross")
    elif macd_h<0 and pmh>=0:
        score+=3
        notes.append("MACD bear cross")
    elif macd_h>0 and direction=="bullish":
        score+=1
    elif macd_h<0 and direction=="bearish":
        score+=1

    return direction, score, notes

# ─── SWING STRUCTURE ─────────────────────────────────────────
def get_swing_points(df, lb=5):
    hi, li = [], []
    n = len(df)
    for i in range(lb, n-lb):
        if df["high"].iloc[i]==df["high"].iloc[i-lb:i+lb+1].max():
            hi.append(i)
        if df["low"].iloc[i] ==df["low"].iloc[i-lb:i+lb+1].min():
            li.append(i)
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
        if ha[i]==max(ha[i-2:i+3]):
            cands.append(ha[i])
        if la[i]==min(la[i-2:i+3]):
            cands.append(la[i])

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
            if z["touches"]>merged[-1]["touches"]:
                merged[-1]=z
        else:
            merged.append(z)
    return merged

# ─── ORDER BLOCKS ────────────────────────────────────────────
def find_order_blocks(df):
    res={"bull_ob":None,"bear_ob":None}
    rc=df.tail(30).reset_index(drop=True)
    for i in range(1,len(rc)-1):
        p=rc.iloc[i-1]
        cur=rc.iloc[i]
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
        zlo = lv*0.9915
        zhi = lv*1.0085

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
    if len(df)<20:
        return {"swept":False}
    rc=df.tail(20)
    last=df.iloc[-1]
    h20=rc["high"].iloc[:-1].max()
    l20=rc["low"].iloc[:-1].min()
    if last["low"]<l20 and last["close"]>l20 and last["close"]>last["open"]:
        return {"swept":True,"type":"bull","level":round(l20,6)}
    if last["high"]>h20 and last["close"]<h20 and last["close"]<last["open"]:
        return {"swept":True,"type":"bear","level":round(h20,6)}
    return {"swept":False}

# ─── PREMIUM/DISCOUNT ────────────────────────────────────────
def get_pd_zone(df, lb=100):
    rc=df.tail(lb)
    sh=rc["high"].max()
    sl=rc["low"].min()
    p=df["close"].iloc[-1]
    rng=sh-sl
    if rng==0:
        return "equilibrium",50
    pct=(p-sl)/rng*100
    return ("discount" if pct<37 else "premium" if pct>63 else "equilibrium"), round(pct,1)

# ─── EQH/EQL ─────────────────────────────────────────────────
def check_eqhl(df, lb=50, thresh=0.003):
    rc=df.tail(lb)
    hs=rc["high"].values
    ls=rc["low"].values
    eqh=eql=None
    for i in range(len(hs)-1):
        for j in range(i+3,len(hs)):
            if abs(hs[i]-hs[j])/hs[i]<thresh:
                eqh=round((hs[i]+hs[j])/2,6)
    for i in range(len(ls)-1):
        for j in range(i+3,len(ls)):
            if abs(ls[i]-ls[j])/ls[i]<thresh:
                eql=round((ls[i]+ls[j])/2,6)
    return {"eqh":eqh,"eql":eql}

# ─── 5m CANDLESTICK PATTERNS ─────────────────────────────────
def detect_5m_candles(df):
    """Entry Detection — Breakout + Retest + Chart Patterns"""
    found = []
    if len(df) < 20:
        return found

    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    atr = df["atr"].iloc[-1] if "atr" in df.columns else abs(c[-1]-o[-1])

    high20 = max(h[-20:-1])
    low20  = min(l[-20:-1])

    price  = c[-1]
    prev   = c[-2]

    # 1. BREAKOUT + RETEST
    if prev > high20 * 0.998:
        if abs(price - high20) / price < 0.015:
            if c[-1] > o[-1]:
                found.append(("Breakout Retest Bullish", "LONG", 4))

    if prev < low20 * 1.002:
        if abs(price - low20) / price < 0.015:
            if c[-1] < o[-1]:
                found.append(("Breakdown Retest Bearish", "SHORT", 4))

    # 2. BULL FLAG
    if len(c) >= 18:
        pole_up   = (c[-10] - c[-18]) / c[-18] if c[-18] > 0 else 0
        consol    = (max(h[-8:-1]) - min(l[-8:-1])) / price if price > 0 else 1
        if pole_up > 0.03 and consol < 0.02:
            if price > max(h[-8:-1]):
                found.append(("Bull Flag Breakout", "LONG", 4))
            elif abs(price - max(h[-8:-1])) / price < 0.01:
                found.append(("Bull Flag Retest", "LONG", 3))

    # 3. BEAR FLAG
    if len(c) >= 18:
        pole_dn   = (c[-18] - c[-10]) / c[-18] if c[-18] > 0 else 0
        consol    = (max(h[-8:-1]) - min(l[-8:-1])) / price if price > 0 else 1
        if pole_dn > 0.03 and consol < 0.02:
            if price < min(l[-8:-1]):
                found.append(("Bear Flag Breakdown", "SHORT", 4))
            elif abs(price - min(l[-8:-1])) / price < 0.01:
                found.append(("Bear Flag Retest", "SHORT", 3))

    # 4. TRIANGLES
    h_last = h[-15:]
    l_last = l[-15:]
    if len(h_last) >= 15:
        h_flat = (max(h_last) - min(h_last)) / max(h_last) < 0.015
        l_slope = (l_last[-1] - l_last[0]) / len(l_last)
        if h_flat and l_slope > 0:
            if price > max(h_last) * 0.998:
                found.append(("Ascending Triangle Breakout", "LONG", 4))

        l_flat = (max(l_last) - min(l_last)) / max(l_last) < 0.015
        h_slope = (h_last[-1] - h_last[0]) / len(h_last)
        if l_flat and h_slope < 0:
            if price < min(l_last) * 1.002:
                found.append(("Descending Triangle Breakdown", "SHORT", 4))

    # 5. WEDGES
    if len(c) >= 10:
        h5 = h[-10:]
        l5 = l[-10:]
        h_slope5 = np.polyfit(range(len(h5)), h5, 1)[0]
        l_slope5 = np.polyfit(range(len(l5)), l5, 1)[0]
        wedge_w  = (h5[-1]-l5[-1])
        wedge_w0 = (h5[0]-l5[0])
        converging = wedge_w < wedge_w0 * 0.7

        if h_slope5 < 0 and l_slope5 < 0 and converging:
            if c[-1] > o[-1] and price > max(h5[-3:]):
                found.append(("Falling Wedge Breakout", "LONG", 3))

        if h_slope5 > 0 and l_slope5 > 0 and converging:
            if c[-1] < o[-1] and price < min(l5[-3:]):
                found.append(("Rising Wedge Breakdown", "SHORT", 3))

    # 6. DOUBLE BOTTOM/TOP
    if len(l) >= 50:
        l50 = l[-50:]
        troughs = [(i, l50[i]) for i in range(2, len(l50)-2)
                   if l50[i] == min(l50[i-2:i+3])]
        if len(troughs) >= 2:
            t1, t2 = troughs[-2], troughs[-1]
            if abs(t1[1]-t2[1])/t1[1] < 0.015 and t2[0]-t1[0] > 5:
                neck = max(h[-50:][t1[0]:t2[0]+1]) if t2[0]>t1[0] else price
                if price > neck * 1.001:
                    found.append(("Double Bottom Breakout", "LONG", 4))

    if len(h) >= 50:
        h50 = h[-50:]
        peaks = [(i, h50[i]) for i in range(2, len(h50)-2)
                 if h50[i] == max(h50[i-2:i+3])]
        if len(peaks) >= 2:
            p1, p2 = peaks[-2], peaks[-1]
            if abs(p1[1]-p2[1])/p1[1] < 0.015 and p2[0]-p1[0] > 5:
                neck = min(l[-50:][p1[0]:p2[0]+1]) if p2[0]>p1[0] else price
                if price < neck * 0.999:
                    found.append(("Double Top Breakdown", "SHORT", 4))

    # 7. ENGULFING
    body3 = abs(c[-1]-o[-1])
    body2 = abs(c[-2]-o[-2])
    if (c[-2]<o[-2] and c[-1]>o[-1] and
            c[-1]>o[-2] and o[-1]<c[-2] and body3>body2):
        found.append(("Bullish Engulfing", "LONG", 3))
    if (c[-2]>o[-2] and c[-1]<o[-1] and
            c[-1]<o[-2] and o[-1]>c[-2] and body3>body2):
        found.append(("Bearish Engulfing", "SHORT", 3))

    # 8. HAMMER / SHOOTING STAR
    uw = h[-1] - max(c[-1],o[-1])
    lw = min(c[-1],o[-1]) - l[-1]
    tot = h[-1]-l[-1]
    if tot > 0:
        if lw > body3*2 and lw > uw*2 and c[-2]<o[-2]:
            found.append(("Hammer Reversal", "LONG", 3))
        if uw > body3*2 and uw > lw*2 and c[-2]>o[-2]:
            found.append(("Shooting Star", "SHORT", 3))

    return found

# ─── 5m ENTRY ZONE CHECK ─────────────────────────────────────
def check_entry_zone(df, direction, sr_zones, ob, fvg):
    price = df["close"].iloc[-1]
    atr   = df["atr"].iloc[-1] if "atr" in df.columns else price*0.005
    zone  = atr * 1.5

    zones_found = []

    for z in sr_zones:
        if abs(price - z["level"]) <= zone:
            zones_found.append(f"S/R {z['type']} at {z['level']}")

    if direction=="LONG" and ob.get("bull_ob"):
        ob_mid = (ob["bull_ob"]["high"]+ob["bull_ob"]["low"])/2
        if abs(price-ob_mid) <= zone*2:
            zones_found.append(f"Bullish OB {ob['bull_ob']['low']}-{ob['bull_ob']['high']}")

    if direction=="SHORT" and ob.get("bear_ob"):
        ob_mid = (ob["bear_ob"]["high"]+ob["bear_ob"]["low"])/2
        if abs(price-ob_mid) <= zone*2:
            zones_found.append(f"Bearish OB {ob['bear_ob']['low']}-{ob['bear_ob']['high']}")

    if direction=="LONG" and fvg.get("bull_fvg"):
        fvg_mid = (fvg["bull_fvg"]["top"]+fvg["bull_fvg"]["bot"])/2
        if abs(price-fvg_mid) <= zone*2:
            zones_found.append(f"Bull FVG {fvg['bull_fvg']['bot']}-{fvg['bull_fvg']['top']}")

    if direction=="SHORT" and fvg.get("bear_fvg"):
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
    return sl, tp1, tp2, tp3, rr_tp2

# ─── MAIN: FULL CASCADE ANALYSIS ─────────────────────────────
def analyze_cascade(symbol, gainers_set=None):
    """TOP-DOWN: 4H → 1H → 30m → 15m → 5m"""

    # STEP 1: 4H + 1H TREND (HTF)
    htf_scores  = {}
    htf_dirs    = {}
    htf_notes   = {}

    for tf_label, tf_code in HTF:
        df = get_klines(symbol, tf_code, 150)
        if df is None:
            continue
        d, s, n = analyze_tf_trend(df)
        htf_dirs[tf_label]   = d
        htf_scores[tf_label] = s
        htf_notes[tf_label]  = n
        time.sleep(0.08)

    # Both HTF must agree
    h4_dir = htf_dirs.get("4H", "neutral")
    h1_dir = htf_dirs.get("1H", "neutral")

    # FIXED: Yeh condition sahi se indent ki gayi
    if h4_dir == "neutral" and h1_dir == "neutral":
        return None

    direction = "LONG" if (h4_dir=="bullish" or h1_dir=="bullish") else "SHORT"
    htf_score = sum(htf_scores.values())

    # STEP 2: 30m + 15m CONFIRMATION (MTF)
    mtf_scores = {}
    mtf_dirs   = {}
    mtf_agrees = 0

    for tf_label, tf_code in MTF:
        df = get_klines(symbol, tf_code, 150)
        if df is None:
            continue
        d, s, n = analyze_tf_trend(df)
        mtf_dirs[tf_label]   = d
        mtf_scores[tf_label] = s
        if d == h4_dir:
            mtf_agrees += 1
        time.sleep(0.08)

    if mtf_agrees == 0:
        return None

    mtf_score = sum(mtf_scores.values())

    # STEP 3: 5m ENTRY ANALYSIS
    df5 = get_klines(symbol, "5m", 200)
    if df5 is None or len(df5)<50:
        return None
    df5 = add_indicators(df5)

    price = df5["close"].iloc[-1]
    atr   = df5["atr"].iloc[-1] if "atr" in df5.columns else price*0.005

    d5, s5, n5 = analyze_tf_trend(df5)
    if d5 not in ["neutral", h4_dir]:
        return None

    # STEP 4: SMC ON 5m
    sr5    = find_sr_zones(df5)
    ob5    = find_order_blocks(df5)
    fvg5   = find_fvg(df5)
    swing5 = get_swing_points(df5)
    flip5  = check_sr_flip(df5, sr5)
    sweep5 = check_sweep(df5)
    pd5, pd_pct = get_pd_zone(df5)
    eqhl5  = check_eqhl(df5)

    entry_zones = check_entry_zone(df5, direction, sr5, ob5, fvg5)

    # STEP 5: 5m CANDLESTICK PATTERNS
    candles = detect_5m_candles(df5)
    matching_candles = [c for c in candles if c[1]==direction]

    if not matching_candles:
        return None

    best_candle = max(matching_candles, key=lambda x: x[2])

    # STEP 6: SCORING
    score = 0
    confirmations = []

    htf_pts = min(htf_score, 12)
    score += htf_pts
    confirmations.append(f"4H {h4_dir} + 1H {h1_dir} aligned")

    mtf_pts = min(int(mtf_score*0.4), 8)
    score += mtf_pts
    if mtf_agrees==2:
        confirmations.append("30m + 15m both confirm")
    else:
        confirmations.append(f"{'30m' if mtf_dirs.get('30m')==h4_dir else '15m'} confirms")

    candle_pts = best_candle[2] * 2
    score +=
