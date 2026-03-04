import csv
import os
import argparse
import glob
from datetime import datetime, timedelta
from collections import defaultdict

# Configuration
INTERVALS = ["5m", "15m"]  # 时间间隔

# 时间间隔映射（分钟）
INTERVAL_MINUTES = {
    "5m": 5,
    "15m": 15
}

# 时区配置
# trigger_history 使用 UTC+8（北京时间）
# market_cycles 使用 UTC 时间
TRIGGER_TIMEZONE_OFFSET = 8  # UTC+8

def load_market_cycles(filepath):
    """
    加载市场周期数据

    Args:
        filepath: market_cycles CSV文件路径

    Returns:
        dict: {timestamp: {'Open': float, 'High': float, 'Low': float, 'Close': float}}
    """
    cycles = {}
    if not os.path.exists(filepath):
        return cycles

    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                timestamp = datetime.strptime(row['Timestamp'], "%Y-%m-%d %H:%M:%S")
                cycles[timestamp] = {
                    'Open': float(row['Open']),
                    'High': float(row['High']),
                    'Low': float(row['Low']),
                    'Close': float(row['Close'])
                }
            except:
                continue

    return cycles

def get_cycle_data(trade_time, cycles, interval_minutes):
    """
    获取交易时间之前最近完成的周期数据

    Args:
        trade_time: 交易时间（UTC+8）
        cycles: 市场周期数据（UTC时间）
        interval_minutes: 时间间隔（分钟）

    Returns:
        dict: {'Open': float, 'High': float, 'Low': float, 'Close': float} 或 None

    示例：
        交易时间 00:34:50 (UTC) 在 00:30-00:45 周期内
        应该查找 00:30 这一行（代表 00:15-00:30 的周期）
    """
    # 将交易时间从 UTC+8 转换为 UTC 时间
    trade_time_utc = trade_time - timedelta(hours=TRIGGER_TIMEZONE_OFFSET)

    # 找到交易所在周期的开始时间
    # 例如：00:34:50 所在周期是 00:30-00:45，开始时间是 00:30
    minute = trade_time_utc.minute
    cycle_start_minute = (minute // interval_minutes) * interval_minutes

    cycle_boundary = trade_time_utc.replace(minute=cycle_start_minute, second=0, microsecond=0)

    # 在cycles中查找这个时间点的周期数据
    # 这代表的是之前已完成的那个周期
    if cycle_boundary in cycles:
        return cycles[cycle_boundary]

    # 如果找不到精确匹配，尝试找最近的过去周期
    for i in range(1, 10):  # 最多向前查找10个周期
        test_time = cycle_boundary - timedelta(minutes=interval_minutes * i)
        if test_time in cycles:
            return cycles[test_time]

    return None

def analyze_file(filepath, cycles_data, interval, target_date=None, max_prob_filter=None):
    """
    分析单个CSV文件（模拟交易）

    Args:
        filepath: trigger_history CSV文件路径（时间为UTC+8）
        cycles_data: 市场周期数据（时间为UTC）
        interval: 时间间隔（5m或15m）
        target_date: 目标日期(YYYY-MM-DD格式)，None表示分析所有日期
        max_prob_filter: 最大概率过滤值，None表示不过滤
    """
    if not os.path.exists(filepath):
        print(f"File {filepath} not found.")
        return None

    date_filter_msg = f"for {target_date}" if target_date else "for all dates"
    print(f"\nAnalyzing {filepath} {date_filter_msg}...")
    print(f"  Note: Converting trigger times from UTC+8 to UTC for cycle matching")

    interval_minutes = INTERVAL_MINUTES[interval]

    # Read CSV
    rows = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader, None)

        for row in reader:
            if not row or len(row) < 3:
                continue

            # Parse Time
            time_str = row[0]
            try:
                dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                date_str = dt.strftime("%Y-%m-%d")
            except:
                continue

            # 如果指定了日期过滤，则只保留该日期的数据
            if target_date and date_str != target_date:
                continue

            # Columns:
            # Time, MarketID, Side, BTC_Price, Net, Fluc, Reason, Multiplier, Prob, Amount
            # 0,    1,        2,    3,         4,   5,    6,      7,          8,    9

            mid = row[1]
            side = row[2]
            btc_price = float(row[3]) if len(row) >= 4 else 0.0

            prob = 0.0
            amount = 0.0

            if len(row) >= 10:
                try:
                    prob = float(row[8])
                    amount = float(row[9])
                except:
                    pass

            if prob == 0:
                prob = 0.99

            # 如果指定了概率过滤，则过滤掉高概率交易
            if max_prob_filter is not None and prob > max_prob_filter:
                continue

            reason = row[6] if len(row) >= 7 else "Unknown"
            condition_name = reason.split('(')[0].strip().strip('"').strip("'")

            rows.append({
                "Time": dt,
                "Date": date_str,
                "MarketID": mid,
                "Side": side,
                "BTC_Price": btc_price,
                "Condition": condition_name,
                "Prob": prob,
                "Amount": amount
            })

    if not rows:
        filter_msg = f" for {target_date}" if target_date else ""
        print(f"No records found{filter_msg}")
        return None

    print(f"Found {len(rows)} records.")

    # 计算模拟交易结果
    results = []
    resolved_count = 0
    no_data_count = 0

    print("Calculating simulated trade outcomes...")
    for i, row in enumerate(rows):
        if i % 10 == 0:
            print(f"Processing {i}/{len(rows)}...", end='\r')

        # 获取周期数据
        cycle_data = get_cycle_data(row['Time'], cycles_data, interval_minutes)

        if cycle_data is None:
            # 找不到价格数据，标记为No Data
            results.append({
                **row,
                "Open_Price": None,
                "Close_Price": None,
                "Status": "No Data",
                "Outcome": "Unknown",
                "Result": "N/A",
                "PnL": 0.0
            })
            no_data_count += 1
            continue

        open_price = cycle_data['Open']
        close_price = cycle_data['Close']

        # 判断交易结果
        # 比较周期的开盘价和收盘价，判断涨跌
        # 涨：Close > Open
        # 跌：Close < Open
        # YES交易：预测涨，如果涨则WIN
        # NO交易：预测跌，如果跌则WIN
        is_win = False
        if row['Side'] == 'YES':
            is_win = close_price > open_price
            outcome = 'YES' if close_price > open_price else 'NO'
        else:  # NO
            is_win = close_price < open_price
            outcome = 'NO' if close_price < open_price else 'YES'

        # 计算PnL
        # 如果赢了：PnL = (Amount / Prob) - Amount = Amount * (1/Prob - 1)
        # 如果输了：PnL = -Amount
        if is_win:
            safe_prob = row['Prob'] if row['Prob'] > 0 else 0.99
            revenue = row['Amount'] / safe_prob
            pnl = revenue - row['Amount']
        else:
            pnl = -row['Amount']

        results.append({
            **row,
            "Open_Price": open_price,
            "Close_Price": close_price,
            "Status": "Resolved",
            "Outcome": outcome,
            "Result": "WIN" if is_win else "LOSS",
            "PnL": pnl
        })
        resolved_count += 1

    print(f"Processing {len(rows)}/{len(rows)}... Done.")
    if no_data_count > 0:
        print(f"Warning: {no_data_count} trades have no market cycle data")

    return results

def generate_html_report(filename, results, target_date=None, max_prob_filter=None):
    if not results:
        return ""

    resolved = [r for r in results if r['Status'] == 'Resolved']

    # 统计数据
    total_trades = len(resolved)
    total_wins = sum(1 for r in resolved if r['Result'] == 'WIN')
    total_pnl = sum(r['PnL'] for r in resolved)
    total_invested = sum(r['Amount'] for r in resolved)

    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    roi = (total_pnl / total_invested * 100) if total_invested > 0 else 0

    # 按策略分组
    strategies = defaultdict(lambda: {
        'total': 0,
        'resolved': 0,
        'wins': 0,
        'pnl': 0.0,
        'invested': 0.0
    })

    for r in results:
        cond = r['Condition']
        strategies[cond]['total'] += 1
        if r['Status'] == 'Resolved':
            strategies[cond]['resolved'] += 1
            strategies[cond]['pnl'] += r['PnL']
            strategies[cond]['invested'] += r['Amount']
            if r['Result'] == 'WIN':
                strategies[cond]['wins'] += 1

    # 生成 HTML
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Strategy Analysis Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
            .container {{ max-width: 1200px; margin: 0 auto; background-color: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            h1, h2 {{ color: #333; }}
            .summary-box {{ display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap; }}
            .card {{ background: #fff; padding: 15px; border: 1px solid #ddd; border-radius: 4px; flex: 1; min-width: 150px; text-align: center; }}
            .card h3 {{ margin: 0 0 10px 0; font-size: 14px; color: #666; }}
            .card .value {{ font-size: 24px; font-weight: bold; }}
            .positive {{ color: #28a745; }}
            .negative {{ color: #dc3545; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #f8f9fa; font-weight: 600; }}
            tr:hover {{ background-color: #f8f9fa; }}
            .strategy-name {{ font-weight: 500; }}
            .win-tag {{ background-color: #d4edda; color: #155724; padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
            .loss-tag {{ background-color: #f8d7da; color: #721c24; padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Strategy Performance Report</h1>
            <p>File: {filename} | Date: {target_date if target_date else 'All'} | Prob Filter: {max_prob_filter if max_prob_filter else 'None'}</p>

            <div class="summary-box">
                <div class="card">
                    <h3>Total Trades</h3>
                    <div class="value">{total_trades}</div>
                </div>
                <div class="card">
                    <h3>Win Rate</h3>
                    <div class="value { 'positive' if win_rate >= 50 else 'negative' }">{win_rate:.1f}%</div>
                </div>
                <div class="card">
                    <h3>Total PnL</h3>
                    <div class="value { 'positive' if total_pnl >= 0 else 'negative' }">${total_pnl:+.2f}</div>
                </div>
                <div class="card">
                    <h3>ROI</h3>
                    <div class="value { 'positive' if roi >= 0 else 'negative' }">{roi:+.1f}%</div>
                </div>
            </div>

            <h2>Strategy Breakdown</h2>
            <table>
                <thead>
                    <tr>
                        <th>Strategy Name</th>
                        <th>Total Orders</th>
                        <th>Success Rate</th>
                        <th>PnL</th>
                        <th>ROI</th>
                        <th>W/L</th>
                    </tr>
                </thead>
                <tbody>
    """

    for strat in sorted(strategies.keys()):
        s = strategies[strat]
        if s['resolved'] == 0:
            continue

        rate = (s['wins'] / s['resolved']) * 100
        pnl = s['pnl']
        roi_s = (s['pnl'] / s['invested'] * 100) if s['invested'] > 0 else 0
        wins = s['wins']
        losses = s['resolved'] - wins

        pnl_class = "positive" if pnl >= 0 else "negative"
        roi_class = "positive" if roi_s >= 0 else "negative"
        rate_class = "positive" if rate >= 50 else "negative"

        html += f"""
                    <tr>
                        <td class="strategy-name">{strat}</td>
                        <td>{s['total']}</td>
                        <td class="{rate_class}">{rate:.1f}%</td>
                        <td class="{pnl_class}">${pnl:+.2f}</td>
                        <td class="{roi_class}">{roi_s:+.1f}%</td>
                        <td><span class="win-tag">{wins}</span> / <span class="loss-tag">{losses}</span></td>
                    </tr>
        """

    html += """
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """

    return html

def print_stats(filename, results, target_date=None, max_prob_filter=None):
    """
    打印统计信息表格，并生成 HTML 报告
    """
    if not results:
        return

    resolved = [r for r in results if r['Status'] == 'Resolved']

    # 构建标题
    title_parts = [filename]
    if target_date:
        title_parts.append(f"Date: {target_date}")
    if max_prob_filter is not None:
        title_parts.append(f"Prob ≤ {max_prob_filter}")

    title = " | ".join(title_parts)

    print("\n" + "="*100)
    print(f" ANALYSIS: {title}")
    print("="*100)

    if not resolved:
        print("No resolved trades.")
        return

    total_trades = len(resolved)
    total_wins = sum(1 for r in resolved if r['Result'] == 'WIN')
    total_pnl = sum(r['PnL'] for r in resolved)
    total_invested = sum(r['Amount'] for r in resolved)

    win_rate = (total_wins / total_trades) * 100
    roi = (total_pnl / total_invested * 100) if total_invested > 0 else 0

    print(f"Total Trades: {total_trades}")
    print(f"Win Rate:     {win_rate:.2f}% ({total_wins}/{total_trades})")
    print(f"Total PnL:    ${total_pnl:+.2f}")
    print(f"Total Vol:    ${total_invested:.2f}")
    print(f"ROI:          {roi:+.2f}%")

    print("-" * 100)
    print(f"{'Strategy':<30} | {'Total Orders':<12} | {'Success Rate':<13} | {'PnL':<12} | {'ROI':<7} | {'W/L':<7}")
    print("-" * 100)

    # Group by Strategy
    strategies = defaultdict(lambda: {
        'total': 0,
        'resolved': 0,
        'wins': 0,
        'pnl': 0.0,
        'invested': 0.0
    })

    for r in results:
        cond = r['Condition']
        strategies[cond]['total'] += 1
        if r['Status'] == 'Resolved':
            strategies[cond]['resolved'] += 1
            strategies[cond]['pnl'] += r['PnL']
            strategies[cond]['invested'] += r['Amount']
            if r['Result'] == 'WIN':
                strategies[cond]['wins'] += 1

    # 按策略名称排序
    for strat in sorted(strategies.keys()):
        s = strategies[strat]
        total_orders = s['total']

        if s['resolved'] == 0:
            success_rate = "N/A"
            pnl_str = "$0.00"
            roi_str = "0.0%"
            wl_str = "0/0"
        else:
            rate = (s['wins'] / s['resolved']) * 100

            # ANSI 颜色代码
            GREEN = '\033[92m'
            RED = '\033[91m'
            RESET = '\033[0m'

            # 为 PnL 和 ROI 添加颜色
            pnl_color = GREEN if s['pnl'] >= 0 else RED
            roi_color = GREEN if (s['pnl'] / s['invested']) >= 0 else RED

            success_rate = f"{rate:.1f}%"
            pnl_str = f"{pnl_color}${s['pnl']:+.2f}{RESET}"
            roi_s = (s['pnl'] / s['invested'] * 100) if s['invested'] > 0 else 0
            roi_str = f"{roi_color}{roi_s:+.1f}%{RESET}"
            wl_str = f"{s['wins']}/{s['resolved']-s['wins']}"

        # 注意：格式化字符串的宽度计算不包含ANSI转义码，这里为了简单起见，可能会稍微对不齐
        # 更好的做法是单独打印或使用支持颜色的库，这里仅做简单调整
        # 由于ANSI码会占用字符长度，导致对齐混乱，这里恢复无颜色打印，颜色仅在HTML报告中体现
        # 或者只在非对齐的关键指标上加颜色

        # 恢复无颜色打印以保持对齐
        pnl_val_str = f"${s['pnl']:+.2f}"
        roi_val_str = f"{roi_s:+.1f}%"

        print(f"{strat:<30} | {total_orders:<12} | {success_rate:<13} | {pnl_val_str:<12} | {roi_val_str:<7} | {wl_str:<7}")

    print("="*100)

    # 生成 HTML 报告文件
    html_content = generate_html_report(filename, results, target_date, max_prob_filter)
    report_filename = f"report_{os.path.basename(filename).replace('.csv', '')}.html"
    with open(report_filename, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"HTML Report generated: {report_filename}")

def load_multi_day_cycles(interval, target_date, days_before=1, days_after=1):
    """
    加载多天的市场周期数据

    Args:
        interval: 时间间隔（5m或15m）
        target_date: 目标日期
        days_before: 加载目标日期前几天的数据
        days_after: 加载目标日期后几天的数据

    Returns:
        dict: 合并的市场周期数据
    """
    all_cycles = {}

    # 解析目标日期
    target_dt = datetime.strptime(target_date, "%Y-%m-%d")

    # 加载前后几天的数据
    for day_offset in range(-days_before, days_after + 1):
        date_to_load = target_dt + timedelta(days=day_offset)
        date_str = date_to_load.strftime("%Y-%m-%d")
        cycles_file = f"market_cycles_{interval}_{date_str}.csv"

        if os.path.exists(cycles_file):
            cycles = load_market_cycles(cycles_file)
            all_cycles.update(cycles)
            print(f"  Loaded {len(cycles)} cycles from {cycles_file}")

    return all_cycles

def get_files_to_analyze(target_date=None):
    """
    获取需要分析的文件列表

    Args:
        target_date: 目标日期(YYYY-MM-DD格式)，None表示分析所有日期

    Returns:
        list: [(trigger_file, interval, target_date_str), ...]
    """
    files = []

    if target_date:
        # 如果指定了日期，查找该日期的文件
        for interval in INTERVALS:
            trigger_file = f"trigger_history_{interval}_{target_date}.csv"
            if os.path.exists(trigger_file):
                files.append((trigger_file, interval, target_date))
            else:
                print(f"Warning: {trigger_file} not found")
    else:
        # 如果没有指定日期，查找所有日期的文件
        for interval in INTERVALS:
            pattern = f"trigger_history_{interval}_*.csv"
            trigger_files = sorted(glob.glob(pattern))
            for trigger_file in trigger_files:
                # 从trigger文件名提取日期
                # trigger_history_5m_2026-03-04.csv -> 2026-03-04
                parts = trigger_file.replace('.csv', '').split('_')
                # parts example: ['trigger', 'history', '5m', '2026-03-04']

                date_part = None
                if len(parts) >= 4:
                    # 尝试最后一部分是否为日期
                    # case: trigger_history_5m_2026-03-04
                    possible_date = parts[-1]
                    try:
                        datetime.strptime(possible_date, "%Y-%m-%d")
                        date_part = possible_date
                    except ValueError:
                        pass

                if date_part:
                    files.append((trigger_file, interval, date_part))

    return files

def main():
    parser = argparse.ArgumentParser(
        description='分析Polymarket模拟交易PnL',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python analyze_pnl.py                           # 分析所有数据
  python analyze_pnl.py --date 2026-03-04         # 分析2026-03-04的数据
  python analyze_pnl.py --prob 0.85               # 分析概率≤0.85的交易
  python analyze_pnl.py --date 2026-03-04 --prob 0.85  # 组合过滤
        """
    )

    parser.add_argument(
        '--date',
        type=str,
        help='指定分析日期 (格式: YYYY-MM-DD)，不指定则分析所有日期'
    )

    parser.add_argument(
        '--prob',
        type=float,
        help='过滤概率阈值，只分析概率≤此值的交易 (例如: 0.85)'
    )

    args = parser.parse_args()

    # 验证日期格式
    if args.date:
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            print(f"错误: 日期格式不正确，应为 YYYY-MM-DD，例如 2026-03-04")
            return

    # 验证概率范围
    if args.prob is not None:
        if not (0 < args.prob <= 1):
            print(f"错误: 概率值应在 0 到 1 之间")
            return

    # 获取需要分析的文件
    files = get_files_to_analyze(args.date)

    if not files:
        if args.date:
            print(f"错误: 未找到日期 {args.date} 的历史文件或周期数据文件")
        else:
            print("错误: 未找到任何历史文件或周期数据文件")
        return

    # 分析每个文件
    for trigger_file, interval, file_date in files:
        print(f"\nLoading market cycles data for {interval} around {file_date}...")
        # 加载多天的市场周期数据（前后各1天，共3天）
        cycles_data = load_multi_day_cycles(interval, file_date, days_before=1, days_after=1)

        if not cycles_data:
            print(f"Warning: No market cycle data found for {interval} around {file_date}")
            continue

        print(f"  Total cycles loaded: {len(cycles_data)}")

        # 分析交易数据
        res = analyze_file(trigger_file, cycles_data, interval,
                          target_date=args.date, max_prob_filter=args.prob)
        print_stats(trigger_file, res, target_date=args.date, max_prob_filter=args.prob)

if __name__ == "__main__":
    main()
