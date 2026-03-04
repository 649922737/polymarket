import csv
import requests
import json
import time
import os
from datetime import datetime

# Configuration
# DATES = ["2026-03-02", "2026-03-03"]
# Today is 3.3, user wants 3.2 and 3.3
TARGET_DATES = ["2026-03-02", "2026-03-03"]
GAMMA_API = "https://gamma-api.polymarket.com"

# Files to analyze
FILES = [
    ("trigger_history_5m.csv", "5-Minute"),
    ("trigger_history_15m.csv", "15-Minute")
]

def get_market_outcome(market_id):
    try:
        url = f"{GAMMA_API}/markets/{market_id}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        pass
    return None

def analyze_multi_days():
    print(f"Analyzing strategies for {TARGET_DATES}...\n")

    overall_pnl = 0
    overall_invested = 0

    market_cache = {}

    for target_date in TARGET_DATES:
        print(f"========== DATE: {target_date} ==========")

        date_pnl = 0
        date_invested = 0

        for file_path, label in FILES:
            if not os.path.exists(file_path):
                # print(f"[{label}] File {file_path} not found.")
                continue

            rows = []
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader, None)

                for row in reader:
                    if not row or len(row) < 3: continue

                    # Date check
                    try:
                        dt = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                        if dt.strftime("%Y-%m-%d") != target_date: continue
                    except: continue

                    # Parse extended fields if available
                    prob = 0.0
                    amount = 0.0
                    if len(row) >= 10:
                        try:
                            prob = float(row[8])
                            amount = float(row[9])
                        except: pass

                    # Fallback amount if 0 (simulation default)
                    if amount == 0: amount = 2.0
                    if prob == 0: prob = 0.5 # Default if missing

                    rows.append({
                        "Time": dt,
                        "MarketID": row[1],
                        "Side": row[2],
                        "Reason": row[6] if len(row) >= 7 else "Unknown",
                        "Prob": prob,
                        "Amount": amount,
                        "File": file_path
                    })

            if not rows:
                print(f"[{label}] No trades found.\n")
                continue

            # Fetch outcomes
            print(f"[{label}] Fetching outcomes for {len(rows)} trades...")
            processed = 0
            resolved_count = 0

            # Local stats for this file/date
            current_stats = {}

            for r in rows:
                mid = r['MarketID']
                if mid in market_cache:
                    m_data = market_cache[mid]
                else:
                    m_data = get_market_outcome(mid)
                    market_cache[mid] = m_data
                    time.sleep(0.05)
                    processed += 1
                    if processed % 10 == 0: print(f"Fetched {processed}...", end='\r')

                # Determine Result
                status = "Pending"
                outcome = "Unknown"

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
                elif m_data and m_data.get('active'):
                    pass

                r['Status'] = status

                if status == "Resolved":
                    resolved_count += 1
                    is_win = (r['Side'] == outcome)
                    r['Result'] = "WIN" if is_win else "LOSS"

                    # PnL Calculation
                    if is_win:
                        revenue = r['Amount'] / (r['Prob'] if r['Prob'] > 0 else 0.99)
                        pnl = revenue - r['Amount']
                    else:
                        pnl = -r['Amount']

                    r['PnL'] = pnl

                    # Update Strategy Stats
                    strat_name = r['Reason'].split('(')[0].strip()

                    if strat_name not in current_stats:
                        current_stats[strat_name] = {'wins': 0, 'losses': 0, 'pnl': 0, 'invested': 0}

                    stats = current_stats[strat_name]
                    if is_win: stats['wins'] += 1
                    else: stats['losses'] += 1
                    stats['pnl'] += pnl
                    stats['invested'] += r['Amount']

            if resolved_count > 0:
                print(f"\n--- {label} Results ({target_date}) ---")
                print(f"{'Strategy Name':<35} | {'Win Rate':<10} | {'PnL':<10} | {'ROI':<8} | {'Trades'}")
                print("-" * 80)

                file_pnl = 0
                file_invested = 0

                for name, stats in sorted(current_stats.items()):
                    total = stats['wins'] + stats['losses']
                    win_rate = (stats['wins'] / total) * 100
                    roi = (stats['pnl'] / stats['invested'] * 100) if stats['invested'] > 0 else 0

                    print(f"{name:<35} | {win_rate:6.2f}%    | ${stats['pnl']:<9.2f} | {roi:>+6.1f}%  | {stats['wins']}/{total}")

                    file_pnl += stats['pnl']
                    file_invested += stats['invested']

                print("-" * 80)
                file_roi = (file_pnl / file_invested * 100) if file_invested > 0 else 0
                print(f"{'TOTAL':<35} | {'':<10} | ${file_pnl:<9.2f} | {file_roi:>+6.1f}%  | {resolved_count}")

                date_pnl += file_pnl
                date_invested += file_invested
            else:
                print(f"[{label}] No resolved trades yet.")

            print("\n")

        print(f">>> DATE SUMMARY ({target_date}): ${date_pnl:.2f}\n")
        overall_pnl += date_pnl
        overall_invested += date_invested

    print("="*80)
    total_roi = (overall_pnl / overall_invested * 100) if overall_invested > 0 else 0
    print(f"GRAND TOTAL (2 Days): ${overall_pnl:.2f} (ROI: {total_roi:+.2f}%)")
    print("="*80)

if __name__ == "__main__":
    analyze_multi_days()
