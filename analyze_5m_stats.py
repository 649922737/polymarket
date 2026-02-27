import os
import json
import glob

DATA_DIR = "market_data"

def load_json(path):
    with open(path, 'r') as f:
        return json.load(f)

def analyze():
    # Find 5m files (exclude _15m_)
    net_files = glob.glob(os.path.join(DATA_DIR, "net_changes_*.json"))
    dates = []
    for f in net_files:
        basename = os.path.basename(f)
        if "_15m_" in basename: continue

        date_str = basename.replace("net_changes_", "").replace(".json", "")
        dates.append(date_str)

    dates.sort()

    print(f"{'Date':<12} | {'Avg Fluc':<10} | {'Avg Net':<10} | {'Avg |Net|':<10} | {'Count':<5}")
    print("-" * 65)

    total_fluc = []
    total_net = []
    total_abs_net = []

    for date_str in dates:
        fluc_file = os.path.join(DATA_DIR, f"fluctuations_{date_str}.json")
        net_file = os.path.join(DATA_DIR, f"net_changes_{date_str}.json")

        if not os.path.exists(net_file) or not os.path.exists(fluc_file):
            continue

        try:
            fluc_data = load_json(fluc_file)
            net_data = load_json(net_file)
        except:
            continue

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
