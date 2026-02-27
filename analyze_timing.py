import pandas as pd
import requests
import json
import time
import os
import glob
from datetime import datetime, timedelta

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

def load_history(start_date_str, end_date_str):
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

    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

    return combined_df[(combined_df['date'] >= start_date) & (combined_df['date'] <= end_date)]

def analyze_timing(start_date_str, end_date_str):
    df = load_history(start_date_str, end_date_str)
    if df.empty:
        print(f"No trades found between {start_date_str} and {end_date_str}")
        return

    print(f"Loaded {len(df)} trades from {start_date_str} to {end_date_str}. Analyzing timing...")

    trades = []
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
            time.sleep(0.02) # Faster for bulk

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

            trades.append({
                "timestamp": timestamp,
                "condition": clean_condition,
                "is_win": is_win
            })

        except Exception as e:
            print(f"Error parsing {mid}: {e}")

    if not trades:
        print("No analyzed trades found.")
        return

    trade_df = pd.DataFrame(trades)

    trade_df['minute'] = trade_df['timestamp'].dt.minute
    trade_df['second'] = trade_df['timestamp'].dt.second
    trade_df['cycle_offset_seconds'] = (trade_df['minute'] % 5) * 60 + trade_df['second']

    # 0-60s vs >60s analysis
    early_trades = trade_df[trade_df['cycle_offset_seconds'] < 60]
    late_trades = trade_df[trade_df['cycle_offset_seconds'] >= 60]

    print("\n=== Win Rate by Timing (0-60s vs >60s) ===")

    def print_stats(name, df):
        total = len(df)
        wins = len(df[df['is_win']])
        losses = total - wins
        rate = (wins / total * 100) if total > 0 else 0
        print(f"{name:<15} | Total: {total:<4} | Wins: {wins:<3} | Losses: {losses:<3} | Win Rate: {rate:.2f}%")

    print_stats("Early (<60s)", early_trades)
    print_stats("Late (>=60s)", late_trades)

    print("\n=== Detailed Breakdown by 30s Bins ===")
    bins = range(0, 301, 30)
    labels = [f"{i}-{i+30}s" for i in range(0, 271, 30)]
    trade_df['cycle_bin'] = pd.cut(trade_df['cycle_offset_seconds'], bins=bins, labels=labels)

    grouped = trade_df.groupby('cycle_bin', observed=False)
    for name, group in grouped:
        total = len(group)
        wins = len(group[group['is_win']])
        losses = total - wins
        rate = (wins / total * 100) if total > 0 else 0
        print(f"{name:<10} | Total: {total:<4} | Wins: {wins:<3} | Losses: {losses:<3} | Win Rate: {rate:.2f}%")

if __name__ == "__main__":
    # Analyze last 7 days (2026-02-17 to 2026-02-23)
    analyze_timing("2026-02-17", "2026-02-23")
