"""
策略: Condition 2 (15m) - 动量跟随
优先级: 2 (文件名决定)

逻辑:
- 时间: 全程有效
- 条件:
  1. 价格波动 (fluctuation) > 0.3% (VOL_THRESHOLD_PCT)
  2. 净变化绝对值 (abs(net_change)) > 0.1% (NET_CHANGE_PCT)
- 动作: 顺势下单 (net_change > 0 买 YES, < 0 买 NO)
"""

def check(state, config, indicators):
    # Only run for 15m markets
    if getattr(state, "market_type", "") != "15m":
        return None

    fluctuation = indicators['fluctuation']
    net_change = indicators['net_change']
    start_p = state.start_price

    # 配置参数 (15m 专用)
    # 波动阈值 0.3%
    vol_thresh_pct = config.get("VOL_THRESHOLD_PCT_15", 0.003)
    # 净变化阈值 0.1%
    net_thresh_pct = config.get("NET_CHANGE_PCT_15", 0.001)

    vol_limit = start_p * vol_thresh_pct
    net_limit = start_p * net_thresh_pct

    # 还需要满足最小绝对值变化 (USD)
    abs_limit_usd = config.get("MIN_ABS_CHANGE_15", 0)

    # 核心判断逻辑
    if fluctuation > vol_limit and abs(net_change) > net_limit and abs(net_change) > abs_limit_usd:
        side = "YES" if net_change > 0 else "NO"

        # 简单过滤：反向指标确认 (可选，这里先不加 RSI/MACD 强限制，保持纯动量)
        # 如果需要，可以参照 5m 策略添加 RSI < 80 (买入) / RSI > 20 (卖出) 等

        reason_str = f"Condition_2_15M_MOMENTUM (Fluc:{fluctuation:.2f}>{vol_limit:.2f}, Net:{abs(net_change):.2f}>{net_limit:.2f})"

        return {
            "action": "trade",
            "side": side,
            "reason": reason_str,
            "size_multiplier": 1.0
        }

    return None
