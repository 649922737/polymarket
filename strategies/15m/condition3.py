"""
策略: Condition 3 (15m) - 上个周期波动突破
优先级: 3 (文件名决定)

逻辑:
- 时间: 全程有效
- 条件:
  1. 当前周期的净值 (abs(net_change)) > 上个周期(15m)波动值 (High-Low) 的 80% (PREV_CYCLE_FLUC_PCT_15)
  2. 当前周期的净值 (abs(net_change)) > 95 (PREV_CYCLE_MIN_ABS_15)
- 动作: 顺势下单
"""

import time
import logging
import requests
import sys
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("PolyBot")

# Add parent directory to path to import fluctuation_recorder
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir) # strategies
grandparent_dir = os.path.dirname(parent_dir) # root
if grandparent_dir not in sys.path:
    sys.path.append(grandparent_dir)

try:
    from fluctuation_recorder import FluctuationRecorder
except ImportError:
    logger.error("Condition3_15m: Failed to import FluctuationRecorder")
    FluctuationRecorder = None

def get_prev_cycle_fluctuation(start_time, recorder):
    """获取上一个周期的波动值 (15分钟)"""
    interval_minutes = 15

    # 确保 UTC
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    else:
        start_time = start_time.astimezone(timezone.utc)

    # 上一个周期的起始时间
    prev_cycle_start = start_time - timedelta(minutes=interval_minutes)

    # 1. 尝试从本地读取
    val = recorder.get_fluctuation(prev_cycle_start)
    if val is not None:
        logger.info(f"Condition3 (15m): Found local prev fluctuation: {val}")
        return val

    # 2. API 获取
    # 请求上一个周期的K线
    req_start = prev_cycle_start
    req_end = start_time # 不包含当前周期

    start_str = req_start.isoformat()
    end_str = req_end.isoformat()

    url = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
    params = {
        'start': start_str,
        'end': end_str,
        'granularity': 900 # 15m
    }
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        logger.info(f"Condition3 (15m): Fetching API for {req_start}")
        resp = requests.get(url, params=params, headers=headers, timeout=5)

        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, list):
                # Coinbase 返回最新的在最前，应该只有1条数据
                candle = data[0]
                ts = candle[0]
                low = float(candle[1])
                high = float(candle[2])
                open_price = float(candle[3])
                close_price = float(candle[4])

                fluc = high - low
                net_val = close_price - open_price

                candle_time = datetime.fromtimestamp(ts, timezone.utc)

                # 校验时间是否匹配 (误差允许60s)
                if abs((candle_time - prev_cycle_start).total_seconds()) < 60:
                    recorder.record_fluctuation(candle_time, fluc)
                    recorder.record_net_change(candle_time, net_val)
                    logger.info(f"Condition3 (15m): Fetched prev fluctuation: {fluc}")
                    return fluc
    except Exception as e:
        logger.error(f"Condition3 (15m): Fetching history failed: {e}")

    return None

def check(state, config, indicators):
    # Only run for 15m markets
    if getattr(state, "market_type", "") != "15m":
        return None

    # Init recorder
    if not hasattr(state, "recorder_15m"):
        if FluctuationRecorder:
            setattr(state, "recorder_15m", FluctuationRecorder(file_suffix="15m"))
        else:
            return None
    recorder = state.recorder_15m

    # Caching keys
    prev_fluc_key = "prev_cycle_fluctuation_val_15m" # Different key from condition1 to be safe
    market_id_key = "prev_fluc_market_id_c3_15m"
    last_attempt_key = "last_fluctuation_attempt_c3_15m"

    # Reset on market switch
    current_market_id = state.active_market.get('id')
    cached_market_id = getattr(state, market_id_key, None)
    if cached_market_id != current_market_id:
        setattr(state, prev_fluc_key, None)
        setattr(state, market_id_key, current_market_id)
        setattr(state, last_attempt_key, 0)

    # Fetch
    prev_fluc = getattr(state, prev_fluc_key, None)
    last_attempt = getattr(state, last_attempt_key, 0)

    if prev_fluc is None:
        if time.time() - last_attempt > 10:
            setattr(state, last_attempt_key, time.time())
            val = get_prev_cycle_fluctuation(state.start_time, recorder)
            if val is not None:
                setattr(state, prev_fluc_key, val)
                prev_fluc = val

    if prev_fluc is None:
        return None

    net_change = indicators['net_change']
    current_abs_change = abs(net_change)

    # Configs for 15m Condition 3
    ratio_pct = config.get("PREV_CYCLE_FLUC_PCT_15", 0.8)
    abs_limit = config.get("PREV_CYCLE_MIN_ABS_15", 95.0)

    ratio_threshold = prev_fluc * ratio_pct

    if current_abs_change > ratio_threshold and current_abs_change > abs_limit:
        side = "YES" if net_change > 0 else "NO"
        reason_str = f"Condition_3_15M_PREV ({current_abs_change:.2f} > {ratio_pct}*{prev_fluc:.2f} & > {abs_limit})"

        return {
            "action": "trade",
            "side": side,
            "reason": reason_str,
            "size_multiplier": 1.0
        }

    return None
