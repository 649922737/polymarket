"""
策略: Condition 5 - 尾期趋势 (Late Trend)
优先级: 5 (由文件名决定)

逻辑:
- 时间: 市场开始 200s 后
- 条件:
  1. 反转次数极少 (<= 1)，说明趋势单一
  2. 净变化幅度很大 > 0.1% (BREAK_THRESHOLD_PCT)
- 动作: 顺势下单
"""

def check(state, config, indicators):
    elapsed = indicators['elapsed']
    if elapsed < 200:
        return None

    net_change = indicators['net_change']
    start_p = state.start_price
    break_limit = start_p * config["BREAK_THRESHOLD_PCT"]

    if state.reversal_count <= 1 and abs(net_change) > break_limit:
        side = "YES" if net_change > 0 else "NO"

        # RSI/MACD 确认
        rsi = indicators['rsi']
        macd_tuple = indicators.get('macd', (0,0,0))
        hist = macd_tuple[2]
        macd_thresh = config.get("MACD_THRESHOLD", 0)

        is_valid = False
        if side == "YES":
            if rsi < 80 and hist > macd_thresh:
                is_valid = True
        else:
            if rsi > 20 and hist < -macd_thresh:
                is_valid = True

        if is_valid:
            return {
                "action": "trade",
                "side": side,
                "reason": "Condition_5_TREND"
            }

    return None
