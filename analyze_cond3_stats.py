import csv
import requests
import json
import time
import os
from datetime import datetime

# Configuration
TARGET_DATE = "2026-03-02"
FILES = ["trigger_history_5m.csv", "trigger_history_15m.csv"]
GAMMA_API = "https://gamma-api.polymarket.com"

def get_market_outcome(market_id):
    try:
        url = f"{GAMMA_API}/markets/{market_id}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        pass
    return None

def analyze_cond3():
    all_rows = []

    # 1. Load Data
    print(f"Loading Condition 3 data for {TARGET_DATE}...")
    for filepath in FILES:
        if not os.path.exists(filepath): continue

        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader, None)

            for row in reader:
                if not row or len(row) < 3: continue

                # Date Check
                try:
                    dt = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                    if dt.strftime("%Y-%m-%d") != TARGET_DATE: continue
                except: continue

                # Check Condition
                reason = row[6] if len(row) >= 7 else ""
                if "Condition_3" not in reason: continue

                # Parse Fields
                mid = row[1]
                side = row[2]

                prob = 0.0
                amount = 0.0
                if len(row) >= 10:
                    try:
                        prob = float(row[8])
                        amount = float(row[9])
                    except: pass

                if prob == 0: prob = 0.99 # Fallback

                all_rows.append({
                    "MarketID": mid,
                    "Side": side,
                    "Prob": prob,
                    "Amount": amount,
                    "Reason": reason,
                    "File": filepath
                })

    print(f"Found {len(all_rows)} Condition 3 trades.")
    if not all_rows: return

    # 2. Fetch Outcomes
    market_cache = {}

    print("Fetching outcomes...")
    processed = 0
    for row in all_rows:
        mid = row['MarketID']
        if mid in market_cache:
            m_data = market_cache[mid]
        else:
            m_data = get_market_outcome(mid)
            market_cache[mid] = m_data
            time.sleep(0.1)
            processed += 1
            if processed % 10 == 0: print(f"Fetched {processed}...", end='\r')

        # Determine Outcome
        outcome = "Unknown"
        status = "Pending"

        if m_data and m_data.get('closed'):
            try:
                raw_p = m_data.get('outcomePrices', '[]')
                raw_o = m_data.get('outcomes', '[]')
                prices = json.loads(raw_p) if isinstance(raw_p, str) else raw_p
                outcomes = json.loads(raw_o) if isinstance(raw_o, str) else raw_o

                winner_idx = -1
                for i, p in enumerate(prices):
                    if float(p) > 0.9:
                        winner_idx = i
                        break

                if winner_idx != -1:
                    outcome = outcomes[winner_idx].upper()
                    status = "Resolved"
                    if outcome in ['YES', 'TRUE', '1', 'UP']: outcome = 'YES'
                    elif outcome in ['NO', 'FALSE', '0', 'DOWN']: outcome = 'NO'
            except: pass

        is_win = (row['Side'] == outcome) if status == "Resolved" else False

        pnl = 0.0
        if status == "Resolved":
            if is_win:
                revenue = row['Amount'] / row['Prob']
                pnl = revenue - row['Amount']
            else:
                pnl = -row['Amount']

        row['Status'] = status
        row['Result'] = "WIN" if is_win else "LOSS"
        row['PnL'] = pnl

    print("Done.")

    # 3. Bucket Analysis
    resolved_rows = [r for r in all_rows if r['Status'] == 'Resolved']

    if not resolved_rows:
        print("No resolved Condition 3 trades.")
        return

    # Buckets: 0.5-0.6, 0.6-0.7, 0.7-0.8, 0.8-0.9, 0.9-1.0
    buckets = {
        "0.50-0.60": [],
        "0.60-0.70": [],
        "0.70-0.80": [],
        "0.80-0.90": [],
        "0.90-1.00": []
    }

    for r in resolved_rows:
        p = r['Prob']
        if 0.5 <= p < 0.6: buckets["0.50-0.60"].append(r)
        elif 0.6 <= p < 0.7: buckets["0.60-0.70"].append(r)
        elif 0.7 <= p < 0.8: buckets["0.70-0.80"].append(r)
        elif 0.8 <= p < 0.9: buckets["0.80-0.90"].append(r)
        elif p >= 0.9: buckets["0.90-1.00"].append(r)
        else: pass # < 0.5 shouldn't happen usually for trend following buying YES/NO

    print("\n" + "="*80)
    print(f" Condition 3 Analysis by Probability ({TARGET_DATE})")
    print("="*80)
    print(f"{'Prob Range':<12} | {'Trades':<6} | {'Win Rate':<10} | {'PnL':<10} | {'ROI':<8} | {'Avg Prob'}")
    print("-" * 80)

    total_pnl = 0
    total_invested = 0

    for b_name in sorted(buckets.keys()):
        trades = buckets[b_name]
        count = len(trades)
        if count == 0:
            print(f"{b_name:<12} | {0:<6} | {'N/A':<10} | {'$0.00':<10} | {'0.0%':<8} | -")
            continue

        wins = sum(1 for t in trades if t['Result'] == 'WIN')
        pnl = sum(t['PnL'] for t in trades)
        invested = sum(t['Amount'] for t in trades)

        avg_prob = sum(t['Prob'] for t in trades) / count
        win_rate = (wins / count) * 100
        roi = (pnl / invested * 100) if invested > 0 else 0

        print(f"{b_name:<12} | {count:<6} | {win_rate:6.2f}%    | ${pnl:<9.2f} | {roi:>+6.1f}%  | {avg_prob:.3f}")

        total_pnl += pnl
        total_invested += invested

    print("="*80)
    print(f"TOTAL PnL: ${total_pnl:.2f} (ROI: {(total_pnl/total_invested*100) if total_invested else 0:.2f}%)")

    # 4. Detailed Failure Analysis
    print("\n" + "="*80)
    print(f" Condition 3 Failure Analysis ({TARGET_DATE})")
    print("="*80)
    print(f"{'Time':<20} | {'Prob':<6} | {'Net':<8} | {'Prev':<8} | {'Avg':<8} | {'Reason'}")
    print("-" * 80)

    for r in resolved_rows:
        if r['Result'] == 'LOSS':
            # Parse Reason for details
            reason = r['Reason']
            try:
                # Format: Condition_3_15M_PREV (Net:134.27 > 0.8*Prev(19.50) & > Avg/2(130.27) & > 0.15%(99.39))
                net_val = reason.split("Net:")[1].split(" ")[0]
                prev_val = reason.split("Prev(")[1].split(")")[0]
                avg_val = reason.split("Avg/2(")[1].split(")")[0]

                # Try to get timestamp from original rows if possible, but here we don't have it easily mapped back unless we stored it
                # We didn't store timestamp in step 1, let's just print what we have

                print(f"{r.get('MarketID', 'N/A'):<20} | {r['Prob']:<6.2f} | {net_val:<8} | {prev_val:<8} | {avg_val:<8} | {reason[:50]}...")
            except:
                 print(f"{r.get('MarketID', 'N/A'):<20} | {r['Prob']:<6.2f} | {'?':<8} | {'?':<8} | {'?':<8} | {reason[:50]}...")

if __name__ == "__main__":
    analyze_cond3()
