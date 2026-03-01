import pandas as pd
from datetime import datetime

def analyze_filter_impact():
    filename = "trade_history_2026-02-28.csv"
    try:
        with open(filename, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print("未找到 5m 交易记录文件。")
        return

    print(f"加载了 {len(lines)-1} 条记录。")

    c2_total = 0
    c2_filtered = 0
    c4_total = 0
    c4_filtered = 0

    filtered_records = []

    for line in lines[1:]:
        line = line.strip()
        if not line: continue

        parts = line.split(',')
        timestamp_str = parts[0]

        condition_parts = parts[2:-6]
        condition = ",".join(condition_parts)

        # Identify strategy
        is_c2 = "Condition_2" in condition or "MOMENTUM" in condition
        is_c4 = "Condition_4" in condition or "FLUC_BREAK" in condition

        if not (is_c2 or is_c4):
            continue

        # Parse time
        try:
            dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            minute_in_cycle = dt.minute % 5
        except:
            continue

        # Filter logic:
        # Option A: Ignore min 0 and 1
        is_filtered_2min = minute_in_cycle < 2
        # Option B: Ignore only min 0
        is_filtered_1min = minute_in_cycle < 1

        if is_c2:
            c2_total += 1
            if is_filtered_2min:
                c2_filtered += 1
            if is_filtered_1min:
                c2_filtered_1min += 1

        if is_c4:
            c4_total += 1
            if is_filtered_2min:
                c4_filtered += 1
            if is_filtered_1min:
                c4_filtered_1min += 1

    print("\n【过滤前2分钟 (Min 0,1) 的影响】")
    print(f"Condition 2: 过滤 {c2_filtered}/{c2_total} ({c2_filtered/c2_total*100:.1f}%)")
    print(f"Condition 4: 过滤 {c4_filtered}/{c4_total} ({c4_filtered/c4_total*100:.1f}%)")
    total_filtered = c2_filtered + c4_filtered
    print(f"总计减少: {total_filtered}/{c2_total + c4_total} ({total_filtered/(c2_total + c4_total)*100:.1f}%)")

    print("\n【只过滤前1分钟 (Min 0) 的影响】")
    print(f"Condition 2: 过滤 {c2_filtered_1min}/{c2_total} ({c2_filtered_1min/c2_total*100:.1f}%)")
    print(f"Condition 4: 过滤 {c4_filtered_1min}/{c4_total} ({c4_filtered_1min/c4_total*100:.1f}%)")
    total_filtered_1min = c2_filtered_1min + c4_filtered_1min
    print(f"总计减少: {total_filtered_1min}/{c2_total + c4_total} ({total_filtered_1min/(c2_total + c4_total)*100:.1f}%)")

if __name__ == "__main__":
    analyze_filter_impact()
