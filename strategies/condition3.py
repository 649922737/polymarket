"""
策略: Condition 3 - 中期反转 (Mid Reversal)
优先级: 3 (由文件名决定)

逻辑:
- 时间: 市场开始 2.5分钟 (150s) 后
- 条件:
  1. 发生过至少一次反转 (reversal_count >= 1)
  2. 价格波动 > 0.1% (REVERSAL_VOL_PCT)
  3. 反转后幅度 > 0.05% (REVERSAL_NET_PCT)
  4. RSI 和 MACD 确认趋势
- 动作: 顺着反转后的趋势下单
"""

def check(state, config, indicators):
    elapsed = indicators['elapsed']
    if elapsed < 150:
        return None

    fluctuation = indicators['fluctuation']
    net_change = indicators['net_change']
    rsi = indicators['rsi']
    # macd_val, signal, hist = indicators['macd']
    # 这里直接使用 indicators['macd'] 元组
    macd_tuple = indicators.get('macd', (0,0,0))
    hist = macd_tuple[2]

    start_p = state.start_price
    rev_vol_limit = start_p * config["REVERSAL_VOL_PCT"]
    rev_net_limit = start_p * config["REVERSAL_NET_PCT"]
    abs_limit = config.get("MIN_ABS_CHANGE", 0)

    if state.reversal_count >= 1:
        if fluctuation > rev_vol_limit and abs(net_change) > rev_net_limit and abs(net_change) > abs_limit:
            side = "YES" if net_change > 0 else "NO"

            # RSI/MACD 确认
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
                    "reason": "Condition_3_REVERSAL"
                }

    return None
