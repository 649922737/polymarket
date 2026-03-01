"""
策略: Condition 2 (15m) - 趋势突破 (Trend Breakout)
优先级: 2

逻辑:
- 时间: 全程有效
- 条件:
  1. 上升趋势: 当前价格 > 前3个周期历史最高价 + (当前价格 * 0.1%) -> 买 YES
  2. 下降趋势: 当前价格 < 前3个周期历史最低价 - (当前价格 * 0.1%) -> 买 NO
- 数据源: 运行时内存维护的 state.cycle_history (包含 max, min, close)
- 历史: 仅依赖运行时收集的数据
- 注意: 重启后需要 3 个完整周期 (45分钟) 才有足够数据
"""

import logging

logger = logging.getLogger("PolyBot")

def check(state, config, indicators):
    # Only run for 15m markets
    if getattr(state, "market_type", "") != "15m":
        return None

    current_p = state.current_price
    if current_p <= 0: return None

    # 从 state.cycle_history 获取数据
    history = getattr(state, "cycle_history", [])

    # 如果数据不足 3 个周期，直接跳过 (冷启动)
    if len(history) < 3:
        return None

    # 获取前 3 个完整周期的极值
    past_3_cycles = history[-3:]

    max_h = max(c['max'] for c in past_3_cycles)
    min_l = min(c['min'] for c in past_3_cycles)

    # 阈值: 当前价格的 0.1%
    threshold = current_p * 0.001

    # 1. 上升突破
    if current_p > (max_h + threshold):
        side = "YES"
        reason = f"Condition_2_15M_BREAK_UP (Cur:{current_p:.2f} > Max:{max_h:.2f} + {threshold:.2f})"

        # RSI/MACD 过滤
        rsi = indicators['rsi']
        macd_tuple = indicators.get('macd', (0,0,0))
        hist = macd_tuple[2]
        macd_thresh = config.get("MACD_THRESHOLD", -1.0)

        if rsi < 85 and hist > macd_thresh:
            return {
                "action": "trade",
                "side": "YES",
                "reason": reason,
                "size_multiplier": 1.0
            }

    # 2. 下降突破
    elif current_p < (min_l - threshold):
        side = "NO"
        reason = f"Condition_2_15M_BREAK_DOWN (Cur:{current_p:.2f} < Min:{min_l:.2f} - {threshold:.2f})"

        rsi = indicators['rsi']
        macd_tuple = indicators.get('macd', (0,0,0))
        hist = macd_tuple[2]
        macd_thresh = config.get("MACD_THRESHOLD", -1.0)

        if rsi > 15 and hist < -macd_thresh:
            return {
                "action": "trade",
                "side": "NO",
                "reason": reason,
                "size_multiplier": 1.0
            }

    return None