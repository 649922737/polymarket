import pandas as pd
import requests
import json
import time
import os
from datetime import datetime

GAMMA_API = "https://gamma-api.polymarket.com"

def get_market_outcome(market_id):
    try:
        url = f"{GAMMA_API}/markets/{market_id}"
        resp = requests.get(url)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Error fetching market {market_id}: {e}")
    return None

def analyze():
    if not os.path.exists("trade_history.csv"):
        print("没有找到 trade_history.csv。请先运行 autoorder.py 进行交易。")
        return

    try:
        df = pd.read_csv("trade_history.csv")
    except Exception as e:
        print(f"读取 CSV 失败: {e}")
        return

    if df.empty:
        print("交易记录为空。")
        return

    print(f"加载了 {len(df)} 条交易记录。正在查询结果...")

    results = []
    market_cache = {}

    for index, row in df.iterrows():
        mid = str(row['market_id'])
        side = str(row['side']).upper() # YES / NO
        condition = row['condition']

        # 清理策略名称 (去除括号内的动态参数，便于合并统计)
        if isinstance(condition, str) and "(" in condition:
            clean_condition = condition.split("(")[0].strip()
        else:
            clean_condition = condition

        # 获取市场数据
        if mid in market_cache:
            market_data = market_cache[mid]
        else:
            market_data = get_market_outcome(mid)
            market_cache[mid] = market_data
            time.sleep(0.1) # Rate limit

        if not market_data:
            results.append({"status": "error", "condition": clean_condition})
            continue

        # 检查是否已关闭/结算
        # closed=True 只是交易关闭，resolved 才是资金结算
        # 但我们可以通过 outcomePrices 来判断结果

        try:
            raw_prices = market_data.get('outcomePrices', '[]')
            raw_outcomes = market_data.get('outcomes', '[]')

            if isinstance(raw_prices, str):
                prices = json.loads(raw_prices)
            else:
                prices = raw_prices

            if isinstance(raw_outcomes, str):
                outcomes = json.loads(raw_outcomes)
            else:
                outcomes = raw_outcomes

            # 寻找赢家 (Price ~= 1)
            winner = None
            for i, p in enumerate(prices):
                if float(p) > 0.9: # 结算后价格通常是 1
                    winner = outcomes[i]
                    break

            if not winner:
                # 尚未结算
                results.append({"status": "pending", "condition": clean_condition})
                continue

            # 归一化 Winner 字符串
            winner = winner.upper()
            if winner in ["TRUE", "1", "YES", "UP"]:
                winner = "YES"
            elif winner in ["FALSE", "0", "NO", "DOWN"]:
                winner = "NO"

            is_win = (side == winner)
            results.append({
                "status": "resolved",
                "condition": clean_condition,
                "result": "win" if is_win else "loss",
                "winner": winner,
                "my_side": side
            })

        except Exception as e:
            print(f"解析市场 {mid} 数据出错: {e}")
            results.append({"status": "parse_error", "condition": clean_condition})

    # 统计
    res_df = pd.DataFrame(results)
    if res_df.empty:
        print("没有结果。")
        return

    # 打印详细记录
    print("\n" + "="*80)
    print(f"{'时间':<20} | {'市场ID':<10} | {'策略':<20} | {'方向':<5} | {'结果':<8} | {'状态'}")
    print("-" * 80)

    # 重新遍历以打印每一行 (结合原始 CSV 数据)
    # 我们需要合并原始数据和结果
    # 简单的做法是把 result 信息加到 results 列表里，然后和 df 一起打印

    # 这里的 results 列表顺序和 df 是一致的
    for i, row in df.iterrows():
        res = results[i]
        timestamp = row['timestamp']
        mid = row['market_id']
        cond = row['condition']
        side = row['side']

        status = res.get('status', 'unknown')
        result_str = res.get('result', '-')

        # 格式化输出
        print(f"{timestamp:<20} | {mid:<10} | {cond:<20} | {side:<5} | {result_str:<8} | {status}")

    print("="*80)

    print("\n" + "="*50)
    print(f"策略表现统计 (生成时间: {datetime.now().strftime('%H:%M:%S')})")
    print("="*50)

    # 总体统计
    resolved_total = res_df[res_df['status'] == 'resolved']
    if not resolved_total.empty:
        total_wins = len(resolved_total[resolved_total['result'] == 'win'])
        total_rate = (total_wins / len(resolved_total)) * 100
        print(f"总体胜率: {total_rate:.2f}% ({total_wins}/{len(resolved_total)})")
    else:
        print("总体胜率: N/A (无已结算订单)")

    print("-" * 50)

    # 按 Condition 分组
    for cond, group in res_df.groupby("condition"):
        total = len(group)
        resolved = group[group['status'] == 'resolved']
        pending = len(group[group['status'] == 'pending'])

        if resolved.empty:
            print(f"策略: {cond:<25} | 等待结算: {pending}/{total}")
            continue

        wins = len(resolved[resolved['result'] == 'win'])
        losses = len(resolved[resolved['result'] == 'loss'])
        win_rate = (wins / len(resolved)) * 100

        print(f"策略: {cond:<25} | 胜率: {win_rate:6.2f}% | 胜/负: {wins}/{losses} | 等待: {pending}")

    print("="*50)

if __name__ == "__main__":
    analyze()
