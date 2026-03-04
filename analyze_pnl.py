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
MAX_PROB_FILTER = 0.90 # Filter trades with Prob > this value

def get_market_outcome(market_id):
    try:
        url = f"{GAMMA_API}/markets/{market_id}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        pass
    return None

def analyze_file(filepath):
    if not os.path.exists(filepath):
        print(f"File {filepath} not found.")
        return None

    print(f"\nAnalyzing {filepath} for {TARGET_DATE}...")

    # Read CSV
    rows = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader, None)

        for line_num, row in enumerate(reader, start=2):
            if not row or len(row) < 3: continue

            # Parse Time
            time_str = row[0]
            try:
                dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                date_str = dt.strftime("%Y-%m-%d")
            except:
                continue

            if date_str != TARGET_DATE:
                continue

            # Columns (migrated format):
            # Time, MarketID, Side, BTC_Price, Net, Fluc, Reason, Multiplier, Prob, Amount
            # 0,    1,        2,    3,         4,   5,    6,      7,          8,    9

            mid = row[1]
            side = row[2]

            prob = 0.0
            amount = 0.0

            if len(row) >= 10:
                try:
                    prob = float(row[8])
                    amount = float(row[9])
                except: pass

            if prob == 0: prob = 0.99

            # Filter high probability trades
            if prob > MAX_PROB_FILTER:
                continue

            reason = row[6] if len(row) >= 7 else "Unknown"
            condition_name = reason.split('(')[0].strip().strip('"').strip("'")

            rows.append({
                "Time": dt,
                "MarketID": mid,
                "Side": side,
                "Condition": condition_name,
                "Prob": prob,
                "Amount": amount
            })

    if not rows:
        print(f"No records found for {TARGET_DATE}")
        return None

    print(f"Found {len(rows)} records.")

    # Fetch Outcomes
    market_cache = {}
    results = []

    print("Fetching outcomes...")
    for i, row in enumerate(rows):
        if i % 10 == 0: print(f"Processing {i}/{len(rows)}...", end='\r')

        mid = str(row['MarketID'])
        if mid in market_cache:
            m_data = market_cache[mid]
        else:
            m_data = get_market_outcome(mid)
            market_cache[mid] = m_data
            time.sleep(0.1)

        outcome = "Unknown"
        status = "Pending"

        if m_data:
            if m_data.get('closed'):
                try:
                    raw_p = m_data.get('outcomePrices', '[]')
                    raw_o = m_data.get('outcomes', '[]')
                    prices = json.loads(raw_p) if isinstance(raw_p, str) else raw_p
                    outcomes = json.loads(raw_o) if isinstance(raw_o, str) else raw_o

                    winner_idx = -1
                    for idx, p in enumerate(prices):
                        if float(p) > 0.9:
                            winner_idx = idx
                            break

                    if winner_idx != -1:
                        outcome = outcomes[winner_idx].upper()
                        status = "Resolved"
                        if outcome in ['YES', 'TRUE', '1', 'UP']: outcome = 'YES'
                        elif outcome in ['NO', 'FALSE', '0', 'DOWN']: outcome = 'NO'
                except: pass
            elif m_data.get('active'):
                status = "Active"

        is_win = False
        pnl = 0.0

        if status == "Resolved":
            is_win = (row['Side'] == outcome)
            if is_win:
                # PnL = Revenue - Cost
                # Revenue = Amount / Prob (Shares) * 1.0 (Payout is 1.0)
                # Ensure Prob is safe
                safe_prob = row['Prob'] if row['Prob'] > 0 else 0.99
                revenue = row['Amount'] / safe_prob
                pnl = revenue - row['Amount']
            else:
                pnl = -row['Amount']

        results.append({
            **row,
            "Status": status,
            "Outcome": outcome,
            "Result": "WIN" if is_win else "LOSS",
            "PnL": pnl
        })

    print(f"Processing {len(rows)}/{len(rows)}... Done.")

    return results

def print_stats(filename, results):
    if not results: return

    resolved = [r for r in results if r['Status'] == 'Resolved']

    print("\n" + "="*80)
    print(f" ANALYSIS: {filename} ({TARGET_DATE})")
    print("="*80)

    if not resolved:
        print("No resolved trades yet.")
        return

    total_trades = len(resolved)
    total_wins = sum(1 for r in resolved if r['Result'] == 'WIN')
    total_pnl = sum(r['PnL'] for r in resolved)
    total_invested = sum(r['Amount'] for r in resolved)

    win_rate = (total_wins / total_trades) * 100
    roi = (total_pnl / total_invested * 100) if total_invested > 0 else 0

    print(f"Total Trades: {total_trades}")
    print(f"Win Rate:     {win_rate:.2f}% ({total_wins}/{total_trades})")
    print(f"Total PnL:    ${total_pnl:+.2f}")
    print(f"Total Vol:    ${total_invested:.2f}")
    print(f"ROI:          {roi:+.2f}%")

    print("-" * 80)
    print(f"{'Strategy':<30} | {'Win Rate':<8} | {'PnL':<8} | {'ROI':<7} | {'W/L':<5} | {'Pend'}")
    print("-" * 80)

    # Group by Strategy
    strategies = {}
    for r in results:
        cond = r['Condition']
        if cond not in strategies:
            strategies[cond] = {'total': 0, 'resolved': 0, 'wins': 0, 'pnl': 0.0, 'invested': 0.0}

        strategies[cond]['total'] += 1
        if r['Status'] == 'Resolved':
            strategies[cond]['resolved'] += 1
            strategies[cond]['pnl'] += r['PnL']
            strategies[cond]['invested'] += r['Amount']
            if r['Result'] == 'WIN':
                strategies[cond]['wins'] += 1

    for strat in sorted(strategies.keys()):
        s = strategies[strat]
        pending = s['total'] - s['resolved']

        if s['resolved'] == 0:
            print(f"{strat:<30} | {'N/A':<8} | {'$0.00':<8} | {'0.0%':<7} | {'0/0':<5} | {pending}")
        else:
            rate = (s['wins'] / s['resolved']) * 100
            roi_s = (s['pnl'] / s['invested'] * 100) if s['invested'] > 0 else 0
            wl = f"{s['wins']}/{s['resolved']-s['wins']}"
            print(f"{strat:<30} | {rate:5.1f}%   | ${s['pnl']:<7.2f} | {roi_s:>+6.1f}% | {wl:<5} | {pending}")

    print("="*80)

def main():
    for f in FILES:
        res = analyze_file(f)
        print_stats(f, res)

if __name__ == "__main__":
    main()
