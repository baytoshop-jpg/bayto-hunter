# scanner_main.py – SINGLE SCAN (for GitHub Actions)
import time
from datetime import datetime
from scanner_core import (
    get_top_gainers, analyze_symbol, send_telegram, is_dup, mark_sent
)

def make_signal_msg(signal):
    emoji = "🟢" if signal['direction'] == "LONG" else "🔴"
    strat_list = "\n".join(f"  • {s}" for s in signal['strategies'])
    return f"""{emoji} <b>#{signal['symbol']} - {signal['direction']} SIGNAL</b>
━━━━━━━━━━━━━━━━━━━━━━━
📊 <b>Grade: {signal['grade']}</b>
📐 <b>Confirmations: {signal['score']} strategies</b>
🎯 <b>Entry:</b> {signal['entry']}
🛡️ <b>Stop Loss:</b> {signal['sl']}
🚀 <b>Take Profit:</b> {signal['tp']}
📈 <b>Risk/Reward:</b> 1:{signal['rr']}
━━━━━━━━━━━━━━━━━━━━━━━
<b>✅ Active Strategies:</b>
{strat_list}
━━━━━━━━━━━━━━━━━━━━━━━
🤖 <b>Ultimate Scanner v9.5 (GitHub Actions)</b>"""

def run_scan():
    print(f"\n{'='*60}")
    print(f"  🔥 SCAN - {datetime.now().strftime('%H:%M:%S')}")
    gainers = get_top_gainers(40)
    if not gainers:
        print("  No coins found.")
        return
    print("\n  TOP 20 MOVERS:")
    for i,g in enumerate(gainers[:20],1):
        arrow = "🚀" if g['change']>15 else "📈" if g['change']>5 else "📊" if g['change']>0 else "📉"
        print(f"    {i:2}. {arrow} {g['symbol']}: {g['change']:+.2f}%")
    print(f"\n  Analyzing {len(gainers)} coins...\n")
    signals = []
    for i, coin in enumerate(gainers,1):
        print(f"    [{i:2}/{len(gainers)}] {coin['symbol']}... ", end="")
        if is_dup(coin['symbol'], "LONG") and is_dup(coin['symbol'], "SHORT"):
            print("⏭️ Duplicate")
            continue
        sig = analyze_symbol(coin['symbol'])
        if sig:
            if is_dup(sig['symbol'], sig['direction']):
                print("⏭️ Recent")
                continue
            signals.append(sig)
            print(f"✅ {sig['direction']} | {sig['score']} strategies")
            print(f"       Entry:{sig['entry']}  SL:{sig['sl']}  TP:{sig['tp']}")
            send_telegram(make_signal_msg(sig))
            mark_sent(sig['symbol'], sig['direction'])
        else:
            print("❌ No setup")
        time.sleep(0.2)   # small delay only to avoid hitting rate limits
    print(f"\n{'='*60}")
    print(f"  📡 SIGNALS FOUND: {len(signals)}")
    print(f"{'='*60}")

if __name__ == "__main__":
    # NO infinite loop – run once and exit
    run_scan()
