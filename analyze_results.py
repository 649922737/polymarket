import pandas as pd
import requests
import json
import time
import os
import glob
import argparse
from datetime import datetime

GAMMA_API = "https://gamma-api.polymarket.com"

def get_market_outcome(market_id):
    try:
        url = f"{GAMMA_API}/markets/{market_id}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Error fetching market {market_id}: {e}")
    return None

def load_all_history():
    all_files = glob.glob("trade_history_*.csv")
    # Include the main trade_history.csv if it exists and has content
    if os.path.exists("trade_history.csv") and os.path.getsize("trade_history.csv") > 0:
        all_files.append("trade_history.csv")

    if not all_files:
        return pd.DataFrame()

    dfs = []
    for f in all_files:
        try:
            # Use on_bad_lines='skip' to ignore malformed rows
            df = pd.read_csv(f, on_bad_lines='skip')
            # Add filename as source for debugging if needed
            # df['source_file'] = f
            dfs.append(df)
        except Exception as e:
            print(f"Skipping {f}: {e}")

    if not dfs:
        return pd.DataFrame()

    combined_df = pd.concat(dfs, ignore_index=True)

    # Ensure timestamp is datetime
    if 'timestamp' in combined_df.columns:
        # errors='coerce' turns invalid dates into NaT
        combined_df['timestamp'] = pd.to_datetime(combined_df['timestamp'], errors='coerce')
        # Drop rows with invalid timestamps
        combined_df = combined_df.dropna(subset=['timestamp'])
        combined_df['date'] = combined_df['timestamp'].dt.date

    return combined_df.sort_values('timestamp')

def parse_date(date_str):
    """Try to parse date string with multiple formats."""
    formats = ['%Y-%m-%d', '%Y%m%d']
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None

def analyze():
    parser = argparse.ArgumentParser(description='Analyze Polymarket trading results.')
    parser.add_argument('-d', '--date', type=str, help='Specific date to analyze (YYYY-MM-DD or YYYYMMDD)')
    parser.add_argument('-s', '--start', type=str, help='Start date for analysis range')
    parser.add_argument('-e', '--end', type=str, help='End date for analysis range')

    args = parser.parse_args()

    df = load_all_history()

    if df.empty:
        print("交易记录为空。")
        return

    # Filter by date if requested
    if args.date:
        target_date = parse_date(args.date)
        if target_date:
            df = df[df['date'] == target_date]
            print(f"Filtering for date: {target_date}")
        else:
            print(f"Invalid date format: {args.date}. Please use YYYY-MM-DD or YYYYMMDD.")
            return

    if args.start:
        start_date = parse_date(args.start)
        if start_date:
            df = df[df['date'] >= start_date]
            print(f"Filtering from start date: {start_date}")
        else:
            print(f"Invalid start date format: {args.start}. Please use YYYY-MM-DD or YYYYMMDD.")
            return

    if args.end:
        end_date = parse_date(args.end)
        if end_date:
            df = df[df['date'] <= end_date]
            print(f"Filtering until end date: {end_date}")
        else:
            print(f"Invalid end date format: {args.end}. Please use YYYY-MM-DD or YYYYMMDD.")
            return

    if df.empty:
        print("No trades found for the specified date(s).")
        return

    print(f"加载了 {len(df)} 条交易记录。正在查询结果...")

    results = []
    market_cache = {}

    for index, row in df.iterrows():
        mid = str(row['market_id'])
        side = str(row['side']).upper() # YES / NO
        condition = row['condition']

        # Add date info
        trade_date = row['date'] if 'date' in row else 'Unknown'

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
            results.append({
                "date": trade_date,
                "status": "error",
                "condition": clean_condition
            })
            continue

        # 检查是否已关闭/结算
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
                # 结算后价格通常是 1, 但有时是 0.999...
                if float(p) > 0.9:
                    winner = outcomes[i]
                    break

            if not winner:
                # 尚未结算
                results.append({
                    "date": trade_date,
                    "status": "pending",
                    "condition": clean_condition
                })
                continue

            # 归一化 Winner 字符串
            winner = winner.upper()
            if winner in ["TRUE", "1", "YES", "UP"]:
                winner = "YES"
            elif winner in ["FALSE", "0", "NO", "DOWN"]:
                winner = "NO"

            is_win = (side == winner)
            results.append({
                "date": trade_date,
                "status": "resolved",
                "condition": clean_condition,
                "result": "win" if is_win else "loss",
                "winner": winner,
                "my_side": side
            })

        except Exception as e:
            print(f"解析市场 {mid} 数据出错: {e}")
            results.append({
                "date": trade_date,
                "status": "parse_error",
                "condition": clean_condition
            })

    # 统计
    res_df = pd.DataFrame(results)
    if res_df.empty:
        print("没有结果。")
        return

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
    print("【按策略统计】")
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

    print("-" * 50)

    # 按日期分组
    print("【按日期统计】")
    # Convert date to string for sorting if needed, but pandas usually handles it
    for date_val, group in res_df.groupby("date"):
        resolved = group[group['status'] == 'resolved']
        if resolved.empty:
            print(f"日期: {date_val} | 无已结算订单 (Total: {len(group)})")
            continue

        wins = len(resolved[resolved['result'] == 'win'])
        losses = len(resolved[resolved['result'] == 'loss'])
        win_rate = (wins / len(resolved)) * 100
        print(f"日期: {date_val} | 胜率: {win_rate:6.2f}% ({wins}/{len(resolved)})")

    print("="*50)

if __name__ == "__main__":
    analyze()
