import pandas as pd
import json
import os
from datetime import datetime, timedelta
import glob

# Constants
LEVERAGE = 5.0
FEE_RATE = 0.0008 # 0.08% per trade
DATA_DIR = "market_data"

def load_json(path):
    with open(path, 'r') as f:
        return json.load(f)

def get_end_price(date_str, cycle_end_time_str, start_price):
    path = os.path.join(DATA_DIR, f"net_changes_15m_{date_str}.json")
    if not os.path.exists(path):
        return None

    data = load_json(path)
    try:
        end_dt = datetime.strptime(cycle_end_time_str, "%H:%M:%S")
        start_dt = end_dt - timedelta(minutes=15)
        key = start_dt.strftime("%H:%M:%S")
    except:
        return None

    net_change = data.get(key)
    if net_change is None:
        return None

    return start_price + net_change

def backtest():
    trigger_file = "trigger_history_15m.csv"
    if not os.path.exists(trigger_file):
        print(f"No trigger file: {trigger_file}")
        return

    with open(trigger_file, 'r') as f:
        lines = f.readlines()

    print(f"Loaded {len(lines)-1} triggers (raw lines).")

    total_pnl = 0.0
    wins = 0
    losses = 0

    results = []

    # Skip header
    for line in lines[1:]:
        line = line.strip()
        if not line: continue

        # Manual parse to handle commas in Reason
        # Time,MarketID,Side,BTC_Price,Net,Fluc,Reason,Multiplier
        parts = line.split(',')

        # Safe guards
        if len(parts) < 8: continue

        time_str = parts[0]
        # market_id = parts[1]
        side = parts[2]

        # BTC_Price is index 3
        try:
            entry_price = float(parts[3])
            net_at_trigger = float(parts[4])
        except:
            continue

        # Calculate Start Price of the cycle
        start_price = entry_price - net_at_trigger

        # Determine Cycle End Time
        try:
            dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except:
            continue

        date_str = dt.strftime("%Y-%m-%d")

        minute = dt.minute
        cycle_start_minute = (minute // 15) * 15
        cycle_end_minute = cycle_start_minute + 15

        cycle_end_dt = dt.replace(minute=0, second=0) + timedelta(minutes=cycle_end_minute)
        cycle_end_str = cycle_end_dt.strftime("%H:%M:%S")

        # Get End Price
        end_price = get_end_price(date_str, cycle_end_str, start_price)

        if end_price is None:
            continue

        # Calculate PnL
        price_change_pct = (end_price - entry_price) / entry_price

        if side == "YES": # Long
            raw_pnl = price_change_pct
        else: # Short
            raw_pnl = -price_change_pct

        lev_pnl = raw_pnl * LEVERAGE

        # Fees: Open + Close
        total_fee = FEE_RATE * 2

        net_pnl = lev_pnl - total_fee

        total_pnl += net_pnl
        if net_pnl > 0: wins += 1
        else: losses += 1

        results.append({
            "Time": time_str,
            "Side": side,
            "Entry": entry_price,
            "Exit": end_price,
            "Net_PnL%": net_pnl * 100
        })

    # Report
    print(f"\n{'='*60}")
    print(f"Perp Backtest (Lev: {LEVERAGE}x, Fee: {FEE_RATE*100}% x2)")
    print(f"{'='*60}")
    print(f"{'Time':<20} | {'Side':<4} | {'Entry':<8} | {'Exit':<8} | {'PnL%':<8}")
    print("-" * 60)

    for r in results:
        print(f"{r['Time']:<20} | {r['Side']:<4} | {r['Entry']:<8.2f} | {r['Exit']:<8.2f} | {r['Net_PnL%']:<8.2f}%")

    print("-" * 60)
    count = len(results)
    if count > 0:
        win_rate = (wins / count) * 100
        avg_pnl = total_pnl / count * 100
        print(f"Total Trades: {count}")
        print(f"Win Rate:     {win_rate:.2f}% ({wins}/{count})")
        print(f"Avg PnL:      {avg_pnl:.2f}%")
        print(f"Total Return: {total_pnl*100:.2f}% (Sum of PnL%)")
    else:
        print("No trades matched with price data.")

if __name__ == "__main__":
    backtest()
