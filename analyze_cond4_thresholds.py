import json
import os
from datetime import datetime, timedelta

DATA_DIR = "market_data"
DATE_STR = "2026-02-28"

def load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"Missing {filename}")
        return {}
    with open(path, 'r') as f:
        return json.load(f)

def analyze():
    fluc_data = load_json(f"fluctuations_{DATE_STR}.json")
    net_data = load_json(f"net_changes_{DATE_STR}.json")

    if not fluc_data: return

    # Sort keys (HH:MM:SS)
    times = sorted(fluc_data.keys())

    # We need datetime objects to easily subtract 5 minutes
    # Assume 2026-02-28 for all
    dt_map = {}
    for t_str in times:
        dt = datetime.strptime(f"{DATE_STR} {t_str}", "%Y-%m-%d %H:%M:%S")
        dt_map[t_str] = dt

    print(f"{'Time':<10} | {'Net Change':<10} | {'Prev Fluc':<10} | {'Avg Fluc(5)':<12} | {'Threshold (Avg/2)':<18} | {'Triggered?'}")
    print("-" * 85)

    for i, t_str in enumerate(times):
        current_dt = dt_map[t_str]

        # 1. Get Prev Fluc (t - 5m)
        prev_dt = current_dt - timedelta(minutes=5)
        prev_key = prev_dt.strftime("%H:%M:%S")
        prev_fluc = fluc_data.get(prev_key, 0.0)

        # 2. Get Avg Fluc (t - 5m ... t - 25m)
        past_flucs = []
        for k in range(1, 6):
            p_dt = current_dt - timedelta(minutes=5*k)
            p_key = p_dt.strftime("%H:%M:%S")
            val = fluc_data.get(p_key)
            if val is not None:
                past_flucs.append(val)

        if not past_flucs:
            avg_fluc = 0.0
        else:
            avg_fluc = sum(past_flucs) / len(past_flucs)

        threshold = avg_fluc / 2.0

        # Current Net
        net = net_data.get(t_str, 0.0)
        abs_net = abs(net)

        # Check Condition 4 Logic
        # > Prev * 0.8 AND > Threshold
        cond1 = abs_net > (prev_fluc * 0.8)
        cond2 = abs_net > threshold
        triggered = "YES" if (cond1 and cond2) else ""

        # Only show relevant times (e.g. every 5 mins or when net is significant)
        # To avoid spam, let's print all 5-min intervals
        if current_dt.minute % 5 == 0:
             print(f"{t_str:<10} | {abs_net:<10.2f} | {prev_fluc:<10.2f} | {avg_fluc:<12.2f} | {threshold:<18.2f} | {triggered}")

if __name__ == "__main__":
    analyze()
