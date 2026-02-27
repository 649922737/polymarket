"""
策略: Condition 1 (15m) - 强波动突破
优先级: 1

逻辑:
- 时间: 全程有效
- 条件:
  1. 当前周期的净值 > 过去5个周期(15m)最大波动值的 80%
  2. 当前周期的净值 > 90
- 动作: 直接下单
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
    logger.error("Condition1_15m: Failed to import FluctuationRecorder")
    FluctuationRecorder = None

def get_max_fluctuation_past_5_cycles(start_time, recorder):
    interval_minutes = 15

    # 确保 UTC
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    else:
        start_time = start_time.astimezone(timezone.utc)

    # 过去 5 个周期的起始时间
    cycle_starts = []
    for i in range(1, 6):
        t = start_time - timedelta(minutes=interval_minutes * i)
        cycle_starts.append(t)

    # 尝试从本地读取
    fluctuations = []
    missing_cycles = []

    for t in cycle_starts:
        val = recorder.get_fluctuation(t)
        if val is not None:
            fluctuations.append(val)
        else:
            missing_cycles.append(t)

    # 如果所有数据都在本地找到了
    if not missing_cycles:
        return max(fluctuations)

    # API 获取
    req_end = start_time
    req_start = start_time - timedelta(minutes=interval_minutes * 5)

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
        logger.info(f"Condition1 (15m): Fetching API. Range: {req_start.strftime('%H:%M')} - {req_end.strftime('%H:%M')}")
        resp = requests.get(url, params=params, headers=headers, timeout=5)

        if resp.status_code == 200:
            data = resp.json()
            if data:
                fetched_fluctuations = []
                for candle in data:
                    ts = candle[0]
                    low = float(candle[1])
                    high = float(candle[2])
                    open_price = float(candle[3])
                    close_price = float(candle[4])
                    fluc = high - low
                    net_val = close_price - open_price

                    candle_time = datetime.fromtimestamp(ts, timezone.utc)

                    recorder.record_fluctuation(candle_time, fluc)
                    recorder.record_net_change(candle_time, net_val)

                    for target_t in cycle_starts:
                        if abs((candle_time - target_t).total_seconds()) < 60:
                            fetched_fluctuations.append(fluc)
                            break

                all_fluctuations = fluctuations + fetched_fluctuations
                if all_fluctuations:
                    max_fluc = max(all_fluctuations)
                    logger.info(f"Condition1 (15m): Max Fluc: {max_fluc:.2f}")
                    return max_fluc
    except Exception as e:
        logger.error(f"Condition1 (15m): Fetching history failed: {e}")

    if fluctuations:
        return max(fluctuations)
    return None

def check(state, config, indicators):
    # Only run for 15m markets
    # redundant check if loaded correctly, but good for safety
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
    prev_fluc_key = "prev_cycle_fluctuation_15m"
    market_id_key = "prev_fluc_market_id_15m"
    last_attempt_key = "last_fluctuation_attempt_time_15m"

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
            val = get_max_fluctuation_past_5_cycles(state.start_time, recorder)
            if val is not None:
                setattr(state, prev_fluc_key, val)
                prev_fluc = val

    if prev_fluc is None:
        return None

    net_change = indicators['net_change']
    current_abs_change = abs(net_change)

    # Configs for 15m
    ratio_pct = config.get("PREV_CYCLE_FLUC_PCT_15", 0.8)
    abs_limit = config.get("PREV_CYCLE_MIN_ABS_15", 90.0)

    ratio_threshold = prev_fluc * ratio_pct

    if current_abs_change > ratio_threshold and current_abs_change > abs_limit:
        side = "YES" if net_change > 0 else "NO"
        reason_str = f"Condition_1_15M_FLUC ({current_abs_change:.2f} > {ratio_pct}*Max({prev_fluc:.2f}) & > {abs_limit})"
        return {
            "action": "trade",
            "side": side,
            "reason": reason_str
        }

    return None
