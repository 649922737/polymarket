import os
import json
import glob
from datetime import datetime

DATA_DIR = "market_data"

def load_json(path):
    with open(path, 'r') as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w') as f:
        # Keep keys sorted
        sorted_data = dict(sorted(data.items()))
        json.dump(sorted_data, f, indent=2)

def aggregate_data():
    # Find all dates with data
    net_files = glob.glob(os.path.join(DATA_DIR, "net_changes_*.json"))
    dates = []
    for f in net_files:
        basename = os.path.basename(f)
        # Skip existing 15m files if they get matched
        if "_15m_" in basename: continue

        date_str = basename.replace("net_changes_", "").replace(".json", "")
        dates.append(date_str)

    dates.sort()

    if not dates:
        print("No data files found.")
        return

    for date_str in dates:
        print(f"Processing {date_str}...")

        nc_file = os.path.join(DATA_DIR, f"net_changes_{date_str}.json")
        fluc_file = os.path.join(DATA_DIR, f"fluctuations_{date_str}.json")

        if not os.path.exists(fluc_file):
            print(f"Skipping {date_str}: Missing fluctuations file")
            continue

        try:
            nc_data = load_json(nc_file)
            fluc_data = load_json(fluc_file)
        except Exception as e:
            print(f"Error loading {date_str}: {e}")
            continue

        # Merge keys
        all_times = sorted(list(set(nc_data.keys()) | set(fluc_data.keys())))

        buckets = {}

        for t_str in all_times:
            # Parse time HH:MM:SS
            try:
                # Add dummy date just for time parsing
                dt = datetime.strptime(f"2000-01-01 {t_str}", "%Y-%m-%d %H:%M:%S")
            except:
                continue

            # Calculate 15m bucket start
            bucket_minute = (dt.minute // 15) * 15
            bucket_dt = dt.replace(minute=bucket_minute, second=0)
            bucket_key = bucket_dt.strftime("%H:%M:%S")

            if bucket_key not in buckets:
                buckets[bucket_key] = []

            buckets[bucket_key].append({
                "time": t_str,
                "net": nc_data.get(t_str, 0.0),
                "fluc": fluc_data.get(t_str, 0.0)
            })

        nc_15m = {}
        fluc_15m = {}

        for k, items in buckets.items():
            # Sort by time
            items.sort(key=lambda x: x['time'])

            # 1. Net Change: Sum
            total_net = sum(item['net'] for item in items)
            # Round to 2 decimals to avoid float drift
            nc_15m[k] = round(total_net, 2)

            # 2. Fluctuation: Reconstruct Path
            current_price = 0.0
            highs = []
            lows = []

            # Track start of interval
            highs.append(current_price)
            lows.append(current_price)

            for item in items:
                open_p = current_price
                net = item['net']
                close_p = open_p + net
                fluc = item['fluc']

                # Assume symmetric wick around body
                # Body = [min(O,C), max(O,C)]
                # Body Range = abs(net)
                # Fluc Range = fluc
                # Wicks = max(0, fluc - abs(net))
                # High = max(O,C) + Wicks/2
                # Low = min(O,C) - Wicks/2

                eff_fluc = max(fluc, abs(net))
                wicks = eff_fluc - abs(net)

                high = max(open_p, close_p) + (wicks / 2)
                low = min(open_p, close_p) - (wicks / 2)

                highs.append(high)
                lows.append(low)

                current_price = close_p

            if highs and lows:
                max_h = max(highs)
                min_l = min(lows)
                total_fluc = max_h - min_l
                fluc_15m[k] = round(total_fluc, 2)
            else:
                fluc_15m[k] = 0.0

        # Save
        nc_out = os.path.join(DATA_DIR, f"net_changes_15m_{date_str}.json")
        fluc_out = os.path.join(DATA_DIR, f"fluctuations_15m_{date_str}.json")

        save_json(nc_out, nc_15m)
        save_json(fluc_out, fluc_15m)
        print(f"Generated 15m data for {date_str} -> {os.path.basename(nc_out)}, {os.path.basename(fluc_out)}")

if __name__ == "__main__":
    aggregate_data()
