"""
策略: Condition 2 - 趋势突破 (Trend Breakout)
优先级: 2

逻辑:
- 时间: 全程有效
- 条件:
  1. 上升趋势: 当前价格 > 前3个周期历史最高价 + (当前价格 * 0.1%) -> 买 YES
  2. 下降趋势: 当前价格 < 前3个周期历史最低价 - (当前价格 * 0.1%) -> 买 NO
- 数据源: 运行时内存维护的 state.cycle_history (包含 max, min, close)
- 历史: 仅依赖运行时收集的数据，不依赖本地文件或估算
"""

import logging

logger = logging.getLogger("PolyBot")

def check(state, config, indicators):
    # 此策略只适用于 5m 市场
    if getattr(state, "market_type", "5m") != "5m":
        return None

    current_p = state.current_price
    if current_p <= 0: return None

    # 从 state.cycle_history 获取数据
    # cycle_history = [{'max': 100, 'min': 90, 'close': 95}, ...]
    history = getattr(state, "cycle_history", [])

    # 如果内存中数据不足，尝试从 market_cycles_5m_YYYY-MM-DD.csv 加载
    if len(history) < 3:
        import csv
        import os
        from datetime import datetime, timedelta

        def load_from_file(filepath):
            if not os.path.exists(filepath): return []
            res = []
            try:
                with open(filepath, 'r') as f:
                    lines = f.readlines()
                    # 倒序读取最后 10 行
                    last_lines = lines[-10:] if len(lines) > 10 else lines
                    for line in last_lines:
                        parts = line.strip().split(',')
                        if len(parts) >= 5:
                            try:
                                res.append({
                                    "max": float(parts[2]),
                                    "min": float(parts[3]),
                                    "close": float(parts[4])
                                })
                            except: pass
            except: pass
            return res

        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

        # 1. 尝试今天
        csv_today = f"market_cycles_5m_{today_str}.csv"
        loaded_history = load_from_file(csv_today)

        # 2. 如果今天不够，尝试昨天补全
        if len(loaded_history) < 3:
            csv_yest = f"market_cycles_5m_{yesterday_str}.csv"
            hist_yest = load_from_file(csv_yest)
            # 合并：昨天在前，今天在后
            loaded_history = hist_yest + loaded_history

        if loaded_history:
            history = loaded_history[-3:]

    # 如果数据不足 3 个周期，直接跳过 (冷启动)
    if len(history) < 3:
        # logger.debug(f"Condition2: Not enough cycle history ({len(history)}/3)")
        return None

    # 获取前 3 个完整周期的极值
    # 注意: cycle_history[-1] 是最近的一个完整周期
    # 取最后 3 个
    past_3_cycles = history[-3:]

    max_h = max(c['max'] for c in past_3_cycles)
    min_l = min(c['min'] for c in past_3_cycles)

    # 阈值: 动态调整
    # 大周期看空: 上升阻力加大(0.15%), 下跌阻力维持(0.1%)
    # 大周期看涨: 上升阻力维持(0.1%), 下跌阻力加大(0.15%)

    # 目前状态: 1D看空 (STRONGLY BEARISH)
    # -> 上升突破需要更强的动能 (+0.15%)
    # -> 下跌突破维持标准 (+0.1%)

    threshold_up = current_p * 0.0015
    threshold_down = current_p * 0.001

    # 1. 上升突破
    if current_p > (max_h + threshold_up):
        side = "YES"
        reason = f"Condition_2_BREAK_UP (Cur:{current_p:.2f} > Max:{max_h:.2f} + {threshold_up:.2f})"

        # RSI/MACD 确认
        rsi = indicators['rsi']
        macd_tuple = indicators.get('macd', (0,0,0))
        hist = macd_tuple[2]
        macd_thresh = config.get("MACD_THRESHOLD", 0)

        if rsi < 80 and hist > macd_thresh:
            return {
                "action": "trade",
                "side": "YES",
                "reason": reason,
                "size_multiplier": 1.0
            }

    # 2. 下降突破
    elif current_p < (min_l - threshold_down):
        side = "NO"
        reason = f"Condition_2_BREAK_DOWN (Cur:{current_p:.2f} < Min:{min_l:.2f} - {threshold_down:.2f})"

        rsi = indicators['rsi']
        macd_tuple = indicators.get('macd', (0,0,0))
        hist = macd_tuple[2]
        macd_thresh = config.get("MACD_THRESHOLD", 0)

        if rsi > 20 and hist < -macd_thresh:
            return {
                "action": "trade",
                "side": "NO",
                "reason": reason,
                "size_multiplier": 1.0
            }

    return None
