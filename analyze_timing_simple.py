import csv
import glob
import os
import time
import json
import requests
from datetime import datetime, timedelta

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

def analyze_timing(target_date_str):
    print(f"Analyzing trades for {target_date_str}...")

    # Find relevant files
    files = glob.glob(f"trade_history*_{target_date_str}.csv")
    if not files:
        # Try without date suffix if not found (though specific date files are expected)
        files = ["trade_history.csv"]

    trades = []

    for f in files:
        if not os.path.exists(f): continue
        print(f"Reading {f}...")

        with open(f, 'r') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                ts_str = row['timestamp']
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except:
                    continue

                # Filter by date just in case
                if ts.strftime("%Y-%m-%d") != target_date_str:
                    continue

                market_id = row['market_id']
                side = row['side']
                condition = row['condition']

                # Determine cycle offset
                minute = ts.minute
                second = ts.second

                # Assuming 5m cycle
                cycle_offset = (minute % 5) * 60 + second

                trades.append({
                    "timestamp": ts,
                    "market_id": market_id,
                    "side": side,
                    "condition": condition,
                    "offset": cycle_offset
                })

    if not trades:
        print("No trades found.")
        return

    # Fetch outcomes
    market_outcomes = {}
    market_ids = set(t['market_id'] for t in trades)

    print(f"Fetching outcomes for {len(market_ids)} markets...")
    count = 0
    for mid in market_ids:
        res = get_market_outcome(mid)
        if res:
            try:
                raw_p = res.get('outcomePrices', '[]')
                raw_o = res.get('outcomes', '[]')

                prices = json.loads(raw_p) if isinstance(raw_p, str) else raw_p
                outcomes = json.loads(raw_o) if isinstance(raw_o, str) else raw_o

                winner = None
                for i, p in enumerate(prices):
                    if float(p) > 0.95:
                        winner = outcomes[i]
                        break

                if winner:
                    w = winner.upper()
                    if w in ["YES", "UP", "TRUE", "1"]: market_outcomes[mid] = "YES"
                    elif w in ["NO", "DOWN", "FALSE", "0"]: market_outcomes[mid] = "NO"
            except:
                pass
        count += 1
        if count % 10 == 0:
            print(f"Processed {count}/{len(market_ids)}...")
        time.sleep(0.05)

    # Analyze
    total = 0
    early_total = 0 # < 120s
    early_losses = 0
    early_wins = 0

    print("\n=== Analysis Results ===")

    for t in trades:
        mid = t['market_id']
        if mid not in market_outcomes:
            continue

        total += 1
        outcome = market_outcomes[mid]
        is_win = (t['side'] == outcome)

        offset = t['offset']
        if offset < 120:
            early_total += 1
            if is_win:
                early_wins += 1
            else:
                early_losses += 1

    print("\n=== Detailed Early Loss Analysis ===")
    print(f"Total Early Trades (<120s): {early_total}")
    print(f"Early Wins: {early_wins} ({early_wins/early_total*100:.2f}%)")
    print(f"Early Losses: {early_losses} ({early_losses/early_total*100:.2f}%)")

    # Analyze Late Trades
    print("\n=== Late Trade Breakdown (>=120s) ===")
    print(f"{'Timestamp':<20} | {'Condition':<30} | {'Side':<4} | {'Result':<6} | {'Offset'}")
    print("-" * 80)

    total_late = 0
    total_late_wins = 0

    for t in trades:
        mid = t['market_id']
        if mid not in market_outcomes: continue

        outcome = market_outcomes[mid]
        is_win = (t['side'] == outcome)
        offset = t['offset']

        if offset >= 120:
            total_late += 1
            if is_win: total_late_wins += 1

            res_str = "WIN" if is_win else "LOSS"
            print(f"{t['timestamp']} | {t['condition'][:30]:<30} | {t['side']:<4} | {res_str:<6} | {offset}s")

    if total_late > 0:
        print(f"\nTotal Late Trades: {total_late}")
        print(f"Late Win Rate: {total_late_wins}/{total_late} ({total_late_wins/total_late*100:.1f}%)")

if __name__ == "__main__":
    analyze_timing("2026-03-01")
