import requests
import json
import time
import pandas as pd
from datetime import datetime

def analyze_15m():
    filename = "trade_history_15m_2026-02-28.csv"
    try:
        with open(filename, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"未找到 {filename}")
        return

    print(f"加载了 {len(lines)-1} 条记录。")

    results = []
    market_cache = {}

    # Skip header
    for line in lines[1:]:
        line = line.strip()
        if not line: continue

        parts = line.split(',')
        timestamp_str = parts[0]
        market_id = parts[1]
        side = parts[-6]
        poly_price = float(parts[-4])

        condition_parts = parts[2:-6]
        condition = ",".join(condition_parts)

        if "(" in condition:
            cond_name = condition.split("(")[0].strip()
        else:
            cond_name = condition

        # Parse timestamp
        try:
            dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            minute_in_cycle = dt.minute % 15
        except:
            minute_in_cycle = -1

        # --- 查询逻辑 ---
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

            res_item = {
                "status": "resolved",
                "result": "win" if is_win else "loss",
                "condition": cond_name,
                "minute_in_cycle": minute_in_cycle,
                "poly_price": poly_price
            }
            results.append(res_item)

            if not is_win:
                print(f"❌ [LOSS] {mid} | Min:{minute_in_cycle:02d} | Prob:{poly_price:.2f} | {cond_name}")

        except Exception as e:
            print(f"Error {mid}: {e}")

    # Stats
    res_df = pd.DataFrame(results)
    if res_df.empty:
        print("无结果。")
        return

    wins = len(res_df[res_df['result']=='win'])
    total = len(res_df)
    losses = res_df[res_df['result']=='loss']

    print(f"\n15m 总体胜率: {wins}/{total} ({wins/total*100:.2f}%)")

    print("\n【失败订单 - 周期内分钟分布 (0-14)】")
    # Count losses per minute
    loss_counts = losses['minute_in_cycle'].value_counts().sort_index()

    for minute in range(15):
        count = loss_counts.get(minute, 0)
        # Visual bar
        bar = "#" * count
        print(f"Min {minute:02d}: {count} {bar}")

    print("\n【失败订单 - 入场概率分布】")
    high_prob_losses = len(losses[losses['poly_price'] > 0.8])
    print(f"入场概率 > 0.8 的亏损: {high_prob_losses}/{len(losses)}")

if __name__ == "__main__":
    analyze_15m()
