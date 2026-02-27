import pandas as pd
import requests
import json
import time
import os
import glob
from datetime import datetime

GAMMA_API = "https://gamma-api.polymarket.com"

def get_market_outcome(market_id):
    try:
        url = f"{GAMMA_API}/markets/{market_id}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Error fetching market {market_id}: {e}")
    return None

def load_history(date_str):
    all_files = glob.glob("trade_history_*.csv")
    if os.path.exists("trade_history.csv") and os.path.getsize("trade_history.csv") > 0:
        all_files.append("trade_history.csv")

    dfs = []
    for f in all_files:
        try:
            df = pd.read_csv(f)
            dfs.append(df)
        except:
            pass

    if not dfs:
        return pd.DataFrame()

    combined_df = pd.concat(dfs, ignore_index=True)
    if 'timestamp' in combined_df.columns:
        combined_df['timestamp'] = pd.to_datetime(combined_df['timestamp'])
        combined_df['date'] = combined_df['timestamp'].dt.date

    # Drop duplicates
    combined_df = combined_df.drop_duplicates(subset=['timestamp', 'market_id', 'condition'])

    target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    return combined_df[combined_df['date'] == target_date]

def analyze_failures(date_str):
    df = load_history(date_str)
    if df.empty:
        return

    print(f"Loaded {len(df)} trades for {date_str}. Analyzing failures...")

    failures = []
    market_cache = {}

    for index, row in df.iterrows():
        mid = str(row['market_id'])
        side = str(row['side']).upper()
        condition = row['condition']
        timestamp = row['timestamp']

        if isinstance(condition, str) and "(" in condition:
            clean_condition = condition.split("(")[0].strip()
        else:
            clean_condition = condition

        if mid in market_cache:
            market_data = market_cache[mid]
        else:
            market_data = get_market_outcome(mid)
            market_cache[mid] = market_data
            time.sleep(0.05)

        if not market_data:
            continue

        try:
            raw_prices = market_data.get('outcomePrices', '[]')
            raw_outcomes = market_data.get('outcomes', '[]')

            if isinstance(raw_prices, str):
                prices = json.loads(raw_prices)
            else:
                prices = raw_prices

            if isinstance(raw_outcomes, str):
                outcomes = json.loads(raw_outcomes)
            else:
                outcomes = raw_outcomes

            winner = None
            for i, p in enumerate(prices):
                if float(p) > 0.9:
                    winner = outcomes[i]
                    break

            if not winner:
                continue

            winner = winner.upper()
            if winner in ["TRUE", "1", "YES", "UP"]:
                winner = "YES"
            elif winner in ["FALSE", "0", "NO", "DOWN"]:
                winner = "NO"

            is_win = (side == winner)

            if not is_win:
                failures.append({
                    "timestamp": timestamp,
                    "condition": clean_condition,
                    "market_id": mid,
                    "side": side,
                    "winner": winner
                })

        except Exception as e:
            print(f"Error parsing {mid}: {e}")

    if not failures:
        print("No failures found.")
        return

    fail_df = pd.DataFrame(failures)

    print("\n=== Failure Analysis ===")
    print(f"Total Failures: {len(fail_df)}")

    # 5-minute cycle analysis
    # Assuming 5-minute cycles start at :00, :05, :10, etc.
    # We want to see where within the cycle the failure occurred.
    # e.g., if trade was at 10:04:30, it's 4m 30s into the cycle.

    fail_df['minute'] = fail_df['timestamp'].dt.minute
    fail_df['second'] = fail_df['timestamp'].dt.second
    fail_df['cycle_offset_seconds'] = (fail_df['minute'] % 5) * 60 + fail_df['second']

    print("\nDistribution of Failures within 5-Minute Cycle:")
    # Bin by 30 seconds
    bins = range(0, 301, 30)
    labels = [f"{i}-{i+30}s" for i in range(0, 271, 30)]

    fail_df['cycle_bin'] = pd.cut(fail_df['cycle_offset_seconds'], bins=bins, labels=labels)

    dist = fail_df['cycle_bin'].value_counts().sort_index()
    print(dist)

    print("\nDetailed Failures by Condition:")
    for cond, group in fail_df.groupby("condition"):
        print(f"\nCondition: {cond}")
        print(group[['timestamp', 'side', 'cycle_offset_seconds']].sort_values('timestamp'))

        # Analyze cycle timing for this condition
        avg_offset = group['cycle_offset_seconds'].mean()
        print(f"Average time into cycle: {avg_offset:.1f} seconds ({int(avg_offset//60)}m {int(avg_offset%60)}s)")

if __name__ == "__main__":
    analyze_failures("2026-02-23")
