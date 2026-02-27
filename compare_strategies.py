import json
import glob
import os
from datetime import datetime, timedelta

def load_data(directory="market_data"):
    fluctuations = {}
    net_changes = {}

    for filepath in glob.glob(os.path.join(directory, "fluctuations_*.json")):
        date_str = os.path.basename(filepath).replace("fluctuations_", "").replace(".json", "")
        with open(filepath, 'r') as f:
            fluctuations[date_str] = json.load(f)

    for filepath in glob.glob(os.path.join(directory, "net_changes_*.json")):
        date_str = os.path.basename(filepath).replace("net_changes_", "").replace(".json", "")
        with open(filepath, 'r') as f:
            net_changes[date_str] = json.load(f)

    return fluctuations, net_changes

def get_max_prev_fluc(time_str, flucs_data):
    try:
        t = datetime.strptime(time_str, "%H:%M:%S")
    except: return None

    values = []
    for i in range(1, 6):
        prev = t - timedelta(minutes=5*i)
        k = prev.strftime("%H:%M:%S")
        if k in flucs_data:
            values.append(flucs_data[k])

    return max(values) if values else None

def get_future_outcome(time_str, net_changes_data):
    """
    Check if the trend continued in the NEXT 5 minutes.
    Return: Net change of the NEXT candle.
    """
    try:
        t = datetime.strptime(time_str, "%H:%M:%S")
        next_t = t + timedelta(minutes=5)
        k = next_t.strftime("%H:%M:%S")
        if k in net_changes_data:
            return net_changes_data[k]
    except: pass
    return None

def analyze():
    flucs, nets = load_data()
    dates = sorted(list(set(flucs.keys()) & set(nets.keys())))

    # Stats
    old_stats = {"total": 0, "wins": 0, "continuation_sum": 0.0}
    new_stats = {"total": 0, "wins": 0, "continuation_sum": 0.0}

    for d in dates:
        day_flucs = flucs[d]
        day_nets = nets[d]
        times = sorted(day_nets.keys())

        for t in times:
            net = day_nets[t]
            max_prev = get_max_prev_fluc(t, day_flucs)

            if max_prev is None: continue

            abs_net = abs(net)
            direction = 1 if net > 0 else -1

            # --- Next Candle Outcome ---
            # If we bought at the END of this candle (breakout confirmed),
            # did the NEXT candle continue the move?
            next_net = get_future_outcome(t, day_nets)
            if next_net is None: continue

            # Did price move in our direction?
            # Win = Next candle continued the direction (Net > 0 if Long, Net < 0 if Short)
            # Or simplified: next_net * direction > 0
            outcome_val = next_net * direction
            is_win = outcome_val > 0

            # --- OLD Strategy ---
            # Threshold: 80% MaxFluc AND Abs > 45
            if abs_net > (max_prev * 0.8) and abs_net > 45.0:
                old_stats["total"] += 1
                if is_win: old_stats["wins"] += 1
                old_stats["continuation_sum"] += next_net * direction

            # --- NEW Strategy ---
            # Threshold: 100% MaxFluc AND Abs > 80
            if abs_net > (max_prev * 1.0) and abs_net > 80.0:
                new_stats["total"] += 1
                if is_win: new_stats["wins"] += 1
                new_stats["continuation_sum"] += next_net * direction

    print("=" * 60)
    print(f"{'Metric':<20} | {'Old Strategy':<15} | {'New Strategy':<15}")
    print("-" * 60)

    # Calc Metrics
    old_winrate = (old_stats["wins"] / old_stats["total"] * 100) if old_stats["total"] else 0
    new_winrate = (new_stats["wins"] / new_stats["total"] * 100) if new_stats["total"] else 0

    old_avg_cont = (old_stats["continuation_sum"] / old_stats["total"]) if old_stats["total"] else 0
    new_avg_cont = (new_stats["continuation_sum"] / new_stats["total"]) if new_stats["total"] else 0

    print(f"{'Trigger Count':<20} | {old_stats['total']:<15} | {new_stats['total']:<15}")
    print(f"{'Win Rate (Next 5m)':<20} | {old_winrate:.2f}%{'':<9} | {new_winrate:.2f}%{'':<9}")
    print(f"{'Avg Continuation ($)':<20} | {old_avg_cont:.2f}{'':<13} | {new_avg_cont:.2f}{'':<13}")
    print("=" * 60)
    print("\nNote: 'Win Rate' here means the price continued in the breakout direction")
    print("during the immediate next 5-minute cycle.")

if __name__ == "__main__":
    analyze()
