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
        # Load file
        try:
            df = pd.read_csv(f)
            # Ensure timestamp is parsed correctly
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                # Filter by date range first to speed up
                start_ts = pd.to_datetime(start_date_str)
                end_ts = pd.to_datetime(end_date_str) + pd.Timedelta(days=1)
                df = df[(df['timestamp'] >= start_ts) & (df['timestamp'] < end_ts)]

            dfs.append(df)
        except Exception as e:
            # print(f"Skipping {f}: {e}")
            pass

    if not dfs:
        return pd.DataFrame()

    combined_df = pd.concat(dfs, ignore_index=True)

    # Drop duplicates
    if not combined_df.empty:
        combined_df = combined_df.drop_duplicates(subset=['timestamp', 'market_id', 'condition'])

    return combined_df

def analyze_timing(start_date_str, end_date_str):
    df = load_history(start_date_str, end_date_str)
    if df.empty:
        print(f"No trades found between {start_date_str} and {end_date_str}")
        return

    # Calculate offset
    # Assuming 5m cycle starts at HH:00, HH:05, ...
    # offset = (minute % 5) * 60 + second

    df['minute'] = df['timestamp'].dt.minute
    df['second'] = df['timestamp'].dt.second
    df['cycle_offset'] = (df['minute'] % 5) * 60 + df['second']

    # Fetch outcomes only for necessary trades
    # To save time, we can group by market_id first
    market_ids = df['market_id'].unique()
    market_outcomes = {}

    # Fetch in batches or one by one
    print(f"Fetching outcomes for {len(market_ids)} markets...")
    for mid in market_ids:
        res = get_market_outcome(mid)
        if res:
            try:
                # Parse winner
                prices = json.loads(res.get('outcomePrices', '[]'))
                outcomes = json.loads(res.get('outcomes', '[]'))

                winner = None
                if prices and outcomes:
                    for i, p in enumerate(prices):
                        if float(p) > 0.95: # Settlement price usually 1.0, but check > 0.95
                            winner = outcomes[i]
                            break

                if winner:
                    w = winner.upper()
                    if w in ["YES", "UP", "TRUE", "1"]: market_outcomes[mid] = "YES"
                    elif w in ["NO", "DOWN", "FALSE", "0"]: market_outcomes[mid] = "NO"
            except:
                pass

    # Calculate win/loss
    df['outcome'] = df['market_id'].map(market_outcomes)
    df = df.dropna(subset=['outcome']) # Only settled markets

    df['is_win'] = df['side'] == df['outcome']

    # Filter < 120s
    early_trades = df[df['cycle_offset'] < 120]
    total_trades = len(df)
    total_early = len(early_trades)

    print(f"\nAnalysis for {start_date_str} to {end_date_str}")
    print(f"Total Settled Trades: {total_trades}")
    print(f"Early Trades (<120s): {total_early} ({total_early/total_trades*100:.1f}%)")

    if total_early > 0:
        early_wins = len(early_trades[early_trades['is_win']])
        early_losses = total_early - early_wins
        win_rate = early_wins / total_early * 100
        print(f"Early Trades Win Rate: {early_wins}/{total_early} ({win_rate:.2f}%)")
        print(f"Early Trades Losses: {early_losses}")

    # Breakdown by 30s
    bins = [0, 30, 60, 90, 120, 300]
    labels = ["0-30s", "30-60s", "60-90s", "90-120s", ">120s"]
    df['time_bin'] = pd.cut(df['cycle_offset'], bins=bins, labels=labels, right=False)

    grouped = df.groupby('time_bin', observed=False)
    print("\n=== Win Rate by Time Bin ===")
    for name, group in grouped:
        t = len(group)
        w = len(group[group['is_win']])
        l = t - w
        rate = (w/t*100) if t > 0 else 0.0
        print(f"{name:<10} | Total: {t:<4} | Wins: {w:<3} | Losses: {l:<3} | Rate: {rate:.2f}%")

if __name__ == "__main__":
    analyze_timing("2026-03-01", "2026-03-01")
