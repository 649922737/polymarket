import os
import json
import glob

DATA_DIR = "market_data"

def load_json(path):
    with open(path, 'r') as f:
        return json.load(f)

def analyze():
    # Find 15m files
    files = glob.glob(os.path.join(DATA_DIR, "fluctuations_15m_*.json"))
    dates = []
    for f in files:
        basename = os.path.basename(f)
        date_str = basename.replace("fluctuations_15m_", "").replace(".json", "")
        dates.append(date_str)

    dates.sort()

    if not dates:
        print("No 15m data files found. Please run generate_15m_data.py first.")
        return

    print(f"{'Date':<12} | {'Avg Fluc':<10} | {'Avg Net':<10} | {'Avg |Net|':<10} | {'Count':<5}")
    print("-" * 65)

    total_fluc = []
    total_net = []
    total_abs_net = []

    for date_str in dates:
        fluc_file = os.path.join(DATA_DIR, f"fluctuations_15m_{date_str}.json")
        net_file = os.path.join(DATA_DIR, f"net_changes_15m_{date_str}.json")

        if not os.path.exists(net_file):
            continue

        fluc_data = load_json(fluc_file)
        net_data = load_json(net_file)

        fluc_vals = list(fluc_data.values())
        net_vals = list(net_data.values())

        # Ensure we align them or just take all values (assuming keys match)
        # Since generated script matches keys, just taking values is fine usually,
        # but let's be safe and use keys intersection
        keys = sorted(list(set(fluc_data.keys()) & set(net_data.keys())))

        if not keys:
            continue

        f_vals = [fluc_data[k] for k in keys]
        n_vals = [net_data[k] for k in keys]
        an_vals = [abs(x) for x in n_vals]

        avg_fluc = sum(f_vals) / len(f_vals)
        avg_net = sum(n_vals) / len(n_vals)
        avg_abs_net = sum(an_vals) / len(an_vals)
        count = len(keys)

        total_fluc.extend(f_vals)
        total_net.extend(n_vals)
        total_abs_net.extend(an_vals)

        print(f"{date_str:<12} | {avg_fluc:<10.2f} | {avg_net:<10.2f} | {avg_abs_net:<10.2f} | {count:<5}")

    print("-" * 65)
    if total_fluc:
        avg_f = sum(total_fluc) / len(total_fluc)
        avg_n = sum(total_net) / len(total_net)
        avg_an = sum(total_abs_net) / len(total_abs_net)
        print(f"{'TOTAL':<12} | {avg_f:<10.2f} | {avg_n:<10.2f} | {avg_an:<10.2f} | {len(total_fluc):<5}")

if __name__ == "__main__":
    analyze()
