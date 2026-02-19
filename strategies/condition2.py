"""
策略: Condition 2 - 全程动量 (Momentum)
优先级: 2 (由文件名决定)

逻辑:
- 时间: 全程有效
- 条件:
  1. 价格波动 (fluctuation) > 0.15% (VOL_THRESHOLD_PCT)
  2. 净变化绝对值 (abs(net_change)) > 0.05% (NET_CHANGE_PCT)
- 动作: 顺势下单 (net_change > 0 买 YES, < 0 买 NO)
"""

def check(state, config, indicators):
    fluctuation = indicators['fluctuation']
    net_change = indicators['net_change']
    start_p = state.start_price

    vol_limit = start_p * config["VOL_THRESHOLD_PCT"]
    net_limit_early = start_p * config["NET_CHANGE_PCT"]
    abs_limit = config.get("MIN_ABS_CHANGE", 0)

    if fluctuation > vol_limit and abs(net_change) > net_limit_early and abs(net_change) > abs_limit:
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
            # 对称阈值: YES > -1, NO < 1
            if rsi > 20 and hist < -macd_thresh:
                is_valid = True

        if is_valid:
            # 检查是否触发双倍单逻辑
            # 当净变化绝对值 > 0.2% (start_p * 0.002) 时，下单两倍
            size_mult = 1.0
            double_limit = start_p * 0.002
            if abs(net_change) > double_limit:
                size_mult = 2.0

            return {
                "action": "trade",
                "side": side,
                "reason": "Condition_2_MOMENTUM",
                "size_multiplier": size_mult
            }

    return None
