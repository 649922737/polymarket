import requests
import json
import time
import pandas as pd
from datetime import datetime

def analyze_5m():
    filename = "trade_history_2026-02-28.csv"
    try:
        with open(filename, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"未找到 5m 交易记录文件 ({filename})。")
        return

    print(f"加载了 {len(lines)-1} 条 5m 交易记录。正在查询链上结果...")

    results = []
    market_cache = {}

    for line in lines[1:]:
        line = line.strip()
        if not line: continue

        parts = line.split(',')
        if len(parts) < 8: continue

        timestamp_str = parts[0]
        market_id = parts[1]

        # Parse fields from the end to be safe against commas in condition
        side = parts[-6]
        poly_price = float(parts[-4])

        condition_parts = parts[2:-6]
        condition = ",".join(condition_parts)

        # 5m 策略通常没有后缀，或者是 STRONG_FLUC, MOMENTUM 等
        if "15M" in condition:
            # Skip if 15m somehow got in here (shouldn't happen)
            continue

        if "(" in condition:
            cond_name = condition.split("(")[0].strip()
        else:
            cond_name = condition

        # Parse timestamp for minute distribution
        try:
            dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            # 5m cycle: 0-4
            minute_in_cycle = dt.minute % 5
        except:
            minute_in_cycle = -1

        # --- Query ---
        mid = market_id
        try:
            if mid in market_cache:
                market = market_cache[mid]
            else:
                url = f"https://gamma-api.polymarket.com/markets/{mid}"
                resp = requests.get(url, timeout=5)
                if resp.status_code != 200:
                    continue
                market = resp.json()
                market_cache[mid] = market
                time.sleep(0.1)

            if not market.get('closed'): continue

            raw_prices = market.get('outcomePrices', '[]')
            raw_outcomes = market.get('outcomes', '[]')

            if isinstance(raw_prices, str): prices = json.loads(raw_prices)
            else: prices = raw_prices

            if isinstance(raw_outcomes, str): outcomes = json.loads(raw_outcomes)
            else: outcomes = raw_outcomes

            winner = None
            for i, p in enumerate(prices):
                if float(p) > 0.9:
                    winner = outcomes[i]
                    break

            if not winner: continue

            winner = winner.upper()
            if winner in ["TRUE", "1", "YES", "UP"]: winner = "YES"
            elif winner in ["FALSE", "0", "NO", "DOWN"]: winner = "NO"

            is_win = (side == winner)

            results.append({
                "status": "resolved",
                "result": "win" if is_win else "loss",
                "condition": cond_name,
                "minute_in_cycle": minute_in_cycle,
                "poly_price": poly_price
            })

            if not is_win:
                print(f"❌ [LOSS] {mid} | Min:{minute_in_cycle} | Prob:{poly_price:.2f} | {cond_name}")

        except Exception as e:
            print(f"Error {mid}: {e}")

    # Stats
    res_df = pd.DataFrame(results)
    if res_df.empty:
        print("无已结算记录。")
        return

    wins = len(res_df[res_df['result']=='win'])
    total = len(res_df)
    losses = res_df[res_df['result']=='loss']

    print(f"\n5m 总体胜率: {wins}/{total} ({wins/total*100:.2f}%)")

    print("\n【失败订单 - 周期内分钟分布 (0-4)】")
    loss_counts = losses['minute_in_cycle'].value_counts().sort_index()
    for minute in range(5):
        count = loss_counts.get(minute, 0)
        bar = "#" * count
        print(f"Min {minute}: {count} {bar}")

    print("\n【按策略统计】")
    for cond, group in res_df.groupby("condition"):
        w = len(group[group['result'] == 'win'])
        t = len(group)
        print(f"{cond:<30}: {w}/{t} ({w/t*100:.2f}%)")

if __name__ == "__main__":
    analyze_5m()
