import csv
from datetime import datetime
import statistics

TARGET_DATE = "2026-03-02"
FILE = "trigger_history_15m.csv"

def analyze_failures():
    print(f"Analyzing failures for {TARGET_DATE}...")

    failures = []
    wins = []

    try:
        with open(FILE, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader, None)

            for row in reader:
                if not row or len(row) < 3: continue

                # Date Check
                try:
                    dt = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                    if dt.strftime("%Y-%m-%d") != TARGET_DATE: continue
                except: continue

                # Check Condition 3
                reason = row[6] if len(row) >= 7 else ""
                if "Condition_3" not in reason: continue

                # Extract Data
                # Example reason: Condition_3_15M_PREV (Net:201.92 > 0.8*Prev(49.48) & > Avg/2(134.18) & > 0.15%(98.80))
                try:
                    net_change = float(reason.split("Net:")[1].split(" ")[0])
                    prev_part = reason.split("Prev(")[1].split(")")[0]
                    prev_fluc = float(prev_part)

                    avg_part = reason.split("Avg/2(")[1].split(")")[0]
                    avg_fluc_div_2 = float(avg_part)
                    avg_fluc = avg_fluc_div_2 * 2

                    prob = float(row[8]) if len(row) >= 9 else 0.0

                    # Determine result (Simulated logic based on previous file reading,
                    # relying on verify or just assuming we need to fetch.
                    # Actually, analyze_cond3_stats.py fetched results.
                    # Let's assume we can't easily get result without fetching,
                    # but we can look at the parameters distribution regardless of result first,
                    # or better, use the logic from analyze_cond3_stats.py to get results first)

                except Exception as e:
                    # print(f"Parse error: {reason} -> {e}")
                    continue

                item = {
                    "time": row[0],
                    "net": net_change,
                    "prev": prev_fluc,
                    "avg": avg_fluc,
                    "prob": prob,
                    "reason": reason,
                    "market_id": row[1],
                    "side": row[2]
                }
                # For now, just collect all cond3 triggers
                wins.append(item)

    except FileNotFoundError:
        print("File not found")
        return

    # To separate wins/losses, we need outcome.
    # Since I cannot easily re-fetch everything quickly without waiting,
    # I will modify this to use the `analyze_cond3_stats.py` output logic if I could.
    # But wait, analyze_cond3_stats.py printed summary, not details.

    # Let's use the code from analyze_cond3_stats.py but modify it to print failure details
    pass

if __name__ == "__main__":
    analyze_failures()
