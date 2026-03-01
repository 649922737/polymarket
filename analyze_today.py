import csv
import requests
import json
import time
import os
from datetime import datetime

# Configuration
TARGET_DATE = "2026-03-01"
FILE_PATH = "trigger_history_15m.csv"
GAMMA_API = "https://gamma-api.polymarket.com"

def get_market_outcome(market_id):
    try:
        url = f"{GAMMA_API}/markets/{market_id}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Error fetching market {market_id}: {e}")
    return None

def analyze_15m_today():
    if not os.path.exists(FILE_PATH):
        print(f"File {FILE_PATH} not found.")
        return

    print(f"Loading {FILE_PATH}...")

    # Read CSV manually
    rows = []
    with open(FILE_PATH, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader, None) # Skip header

        for line_num, row in enumerate(reader, start=2):
            if not row: continue

            # Simple validation
            if len(row) < 3: continue

            # Parse Time
            time_str = row[0]
            try:
                dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                date_str = dt.strftime("%Y-%m-%d")
            except:
                continue

            if date_str != TARGET_DATE:
                continue

            mid = row[1]
            side = row[2]

            # Extract Reason
            # In CSV, Reason might be quoted if it contains commas. csv.reader handles that.
            # But the column index depends on whether we migrated or not.
            # If we migrated, Reason is at index 6 (0-based) IF columns are correct.
            # Time, MarketID, Side, BTC_Price, Net, Fluc, Reason, Multiplier, Prob, Amount
            # 0,    1,        2,    3,         4,   5,    6,      7,          8,    9

            if len(row) >= 7:
                reason = row[6]
            else:
                reason = "Unknown"

            rows.append({
                "Time": dt,
                "MarketID": mid,
                "Side": side,
                "Reason": reason
            })

    if not rows:
        print(f"No records found for {TARGET_DATE}")
        return

    print(f"Found {len(rows)} records for {TARGET_DATE}")

    results = []
    market_cache = {}

    print("Fetching market outcomes (this may take a moment)...")

    for i, row in enumerate(rows):
        mid = str(row['MarketID'])
        side = str(row['Side']).upper()
        reason = str(row['Reason'])

        # Extract simple condition name
        condition_name = reason.split('(')[0].strip().strip('"').strip("'")

        # Get outcome
        if mid in market_cache:
            m_data = market_cache[mid]
        else:
            m_data = get_market_outcome(mid)
            market_cache[mid] = m_data
            time.sleep(0.1) # Rate limit

            if i % 10 == 0:
                print(f"Processed {i}/{len(rows)}...", end='\r')

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
                except:
                    pass
            elif m_data.get('active'):
                 status = "Active"

        is_win = False
        if status == "Resolved":
            is_win = (side == outcome)

        results.append({
            "Time": row['Time'],
            "Condition": condition_name,
            "Side": side,
            "Outcome": outcome,
            "Status": status,
            "Result": "WIN" if is_win else "LOSS"
        })

    print(f"Processed {len(rows)}/{len(rows)}... Done.")

    # Stats
    resolved_results = [r for r in results if r['Status'] == 'Resolved']

    print("\n" + "="*80)
    print(f"  15-Minute Strategy Analysis for {TARGET_DATE}")
    print("="*80)

    if not resolved_results:
        print("No resolved markets yet.")
    else:
        wins = sum(1 for r in resolved_results if r['Result'] == 'WIN')
        total = len(resolved_results)
        win_rate = (wins / total) * 100
        print(f"Overall Win Rate: {win_rate:.2f}% ({wins}/{total})")

        print("-" * 80)
        print(f"{'Strategy':<35} | {'Win Rate':<10} | {'W/L':<10} | {'Pending'}")
        print("-" * 80)

        # Group by strategy
        strategies = {}
        for r in results:
            cond = r['Condition']
            if cond not in strategies:
                strategies[cond] = {'total': 0, 'resolved': 0, 'wins': 0}

            strategies[cond]['total'] += 1
            if r['Status'] == 'Resolved':
                strategies[cond]['resolved'] += 1
                if r['Result'] == 'WIN':
                    strategies[cond]['wins'] += 1

        for strat in sorted(strategies.keys()):
            data = strategies[strat]
            pending = data['total'] - data['resolved']

            if data['resolved'] == 0:
                print(f"{strat:<35} | {'N/A':<10} | {'0/0':<10} | {pending}")
            else:
                s_rate = (data['wins'] / data['resolved']) * 100
                wl_str = f"{data['wins']}/{data['resolved']-data['wins']}"
                print(f"{strat:<35} | {s_rate:.2f}%     | {wl_str:<10} | {pending}")

    print("="*80)

    print("\nRecent Resolved Results:")
    # Sort by time
    resolved_results.sort(key=lambda x: x['Time'])
    for r in resolved_results[-10:]:
        time_s = r['Time'].strftime('%H:%M')
        cond_s = (r['Condition'][:25] + '..') if len(r['Condition']) > 25 else r['Condition']
        print(f"{time_s} | {cond_s:<27} | {r['Side']} -> {r['Outcome']} | {r['Result']}")

if __name__ == "__main__":
    analyze_15m_today()
