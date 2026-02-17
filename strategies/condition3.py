"""
策略: Condition 3 - 上个周期波动突破 (Previous Cycle Fluctuation Breakout)
优先级: 3 (由文件名决定)

逻辑:
- 时间: 全程有效
- 条件:
  1. 当前周期的净值 (abs(net_change)) > 上个周期波动值 (High-Low) 的 60% (可配置 PREV_CYCLE_FLUC_PCT)
  2. 当前周期的净值 (abs(net_change)) > 65 (可配置 PREV_CYCLE_MIN_ABS)
- 动作: 直接下单
"""

import time
import logging
import requests
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("PolyBot")

def get_previous_fluctuation(start_time):
    # 确保 UTC
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    else:
        start_time = start_time.astimezone(timezone.utc)

    # 上一个 5 分钟周期
    # Start: T-5min, End: T
    prev_start = start_time - timedelta(minutes=5)
    prev_end = start_time

    start_str = prev_start.isoformat()
    end_str = prev_end.isoformat()

    # 请求 Coinbase 5分钟 Candle
    url = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
    params = {
        'start': start_str,
        'end': end_str,
        'granularity': 300
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            # [time, low, high, open, close, volume]
            if data and len(data) > 0:
                candle = data[0]
                low = float(candle[1])
                high = float(candle[2])
                fluc = high - low
                logger.info(f"Condition3: 获取到上个周期波动: {fluc:.2f} ({prev_start.strftime('%H:%M')} - {prev_end.strftime('%H:%M')})")
                return fluc
            else:
                logger.warning(f"Condition3: 上个周期无 Candle 数据 ({start_str})")
        else:
            logger.warning(f"Condition3: Coinbase API Error: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Condition3: 获取历史数据失败: {e}")

    return None

def check(state, config, indicators):
    # 1. 检查是否切换了市场，如果是则重置缓存
    current_market_id = state.active_market.get('id')
    cached_market_id = getattr(state, 'prev_fluc_market_id', None)

    if cached_market_id != current_market_id:
        state.prev_cycle_fluctuation = None
        state.prev_fluc_market_id = current_market_id
        state.last_fluctuation_attempt_time = 0

    # 2. 尝试获取/读取缓存的上个周期波动
    if not hasattr(state, 'prev_cycle_fluctuation'):
        state.prev_cycle_fluctuation = None
        state.last_fluctuation_attempt_time = 0

    if state.prev_cycle_fluctuation is None:
        # 每 10 秒重试一次
        if time.time() - state.last_fluctuation_attempt_time > 10:
            state.last_fluctuation_attempt_time = time.time()
            val = get_previous_fluctuation(state.start_time)
            if val is not None:
                state.prev_cycle_fluctuation = val

    # 如果还是没有数据，无法判断，返回 None
    if state.prev_cycle_fluctuation is None:
        return None

    prev_fluc = state.prev_cycle_fluctuation
    net_change = indicators['net_change']

    # 2. 判断条件
    # A. 比例阈值
    ratio_pct = config.get("PREV_CYCLE_FLUC_PCT", 0.6)
    ratio_threshold = prev_fluc * ratio_pct

    # B. 绝对值阈值
    abs_limit = config.get("PREV_CYCLE_MIN_ABS", 65.0)

    current_abs_change = abs(net_change)

    if current_abs_change > ratio_threshold and current_abs_change > abs_limit:
        side = "YES" if net_change > 0 else "NO"

        return {
            "action": "trade",
            "side": side,
            "reason": f"Condition_3_FLUC_BREAK ({current_abs_change:.2f} > {ratio_pct}*{prev_fluc:.2f} & > {abs_limit})"
        }

    return None
