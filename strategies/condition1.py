"""
策略: Condition 1 - 强波动突破 (Condition 1 - Strong Fluctuation Breakout)
优先级: 1 (由文件名决定)

逻辑:
- 时间: 全程有效
- 条件:
  1. 当前周期的净值 (abs(net_change)) > 过去5个周期最大波动值的 80%
  2. 当前周期的净值 (abs(net_change)) > 45 (5m) / 90 (15m)
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
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

try:
    from fluctuation_recorder import FluctuationRecorder
except ImportError:
    logger.error("Condition1: Failed to import FluctuationRecorder")
    FluctuationRecorder = None

def get_max_fluctuation_past_5_cycles(start_time, interval_minutes, recorder):
    """
    获取过去 5 个周期 (每个 interval_minutes) 的最大波动值
    """
    if not recorder:
        return None

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
        max_fluc = max(fluctuations)
        return max_fluc

    # 如果有缺失，需要从 API 获取
    # Range: 最早缺失时间 -> start_time
    req_end = start_time
    req_start = start_time - timedelta(minutes=interval_minutes * 5)

    start_str = req_start.isoformat()
    end_str = req_end.isoformat()

    # 根据 interval 决定 granularity
    # Coinbase 只有 60, 300, 900, 3600...
    granularity = 300
    if interval_minutes == 15:
        granularity = 900
    elif interval_minutes == 5:
        granularity = 300
    else:
        # Fallback to 1m if needed, but we stick to 5/15
        granularity = 60 * interval_minutes

    url = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
    params = {
        'start': start_str,
        'end': end_str,
        'granularity': granularity
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
    }

    try:
        logger.info(f"Condition1 ({interval_minutes}m): Fetching API for missing cycles. Range: {req_start.strftime('%H:%M')} - {req_end.strftime('%H:%M')}")
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

                    # 记录到本地
                    recorder.record_fluctuation(candle_time, fluc)
                    recorder.record_net_change(candle_time, net_val)

                    # 检查是否匹配需要的周期
                    for target_t in cycle_starts:
                        if abs((candle_time - target_t).total_seconds()) < 60:
                            fetched_fluctuations.append(fluc)
                            break

                all_fluctuations = fluctuations + fetched_fluctuations
                if all_fluctuations:
                    max_fluc = max(all_fluctuations)
                    logger.info(f"Condition1: Updated fluctuations. Max: {max_fluc:.2f}")
                    return max_fluc
            else:
                logger.warning(f"Condition1: API returned empty data")
        else:
            logger.warning(f"Condition1: Coinbase API Error: {resp.status_code}")

    except Exception as e:
        logger.error(f"Condition1: Fetching history failed: {e}")

    if fluctuations:
        return max(fluctuations)

    return None

def check(state, config, indicators):
    # Only run for 5m markets
    if getattr(state, "market_type", "5m") != "5m":
        return None

    # Initialize recorder if needed
    if not hasattr(state, "recorder_5m"):
        if FluctuationRecorder:
            setattr(state, "recorder_5m", FluctuationRecorder(file_suffix=""))
        else:
            return None

    recorder = state.recorder_5m

    # State keys
    prev_fluc_key = "prev_cycle_fluctuation_5"
    market_id_key = "prev_fluc_market_id_5"
    last_attempt_key = "last_fluctuation_attempt_time_5"

    # 1. 检查是否切换了市场
    current_market_id = state.active_market.get('id')
    cached_market_id = getattr(state, market_id_key, None)

    if cached_market_id != current_market_id:
        setattr(state, prev_fluc_key, None)
        setattr(state, market_id_key, current_market_id)
        setattr(state, last_attempt_key, 0)

    # 2. 尝试获取缓存值
    prev_fluc = getattr(state, prev_fluc_key, None)
    last_attempt = getattr(state, last_attempt_key, 0)

    if prev_fluc is None:
        if time.time() - last_attempt > 10:
            setattr(state, last_attempt_key, time.time())
            # 5m interval
            val = get_max_fluctuation_past_5_cycles(state.start_time, 5, recorder)
            if val is not None:
                setattr(state, prev_fluc_key, val)
                prev_fluc = val

    if prev_fluc is None:
        return None

    net_change = indicators['net_change']
    current_abs_change = abs(net_change)

    # Configs for 5m
    ratio_pct = config.get("PREV_CYCLE_FLUC_PCT_5", 0.8)
    abs_limit = config.get("PREV_CYCLE_MIN_ABS_5", 60.0) # 提高阈值：从 45.0 提到 60.0
    hard_abs_threshold = 140.0

    ratio_threshold = prev_fluc * ratio_pct

    # Logic
    triggered = False
    reason_str = ""

    if current_abs_change > ratio_threshold and current_abs_change > abs_limit:
        triggered = True
        reason_str = f"Condition_1_STRONG_FLUC ({current_abs_change:.2f} > {ratio_pct}*Max({prev_fluc:.2f}) & > {abs_limit})"
    elif current_abs_change > hard_abs_threshold:
        triggered = True
        reason_str = f"Condition_1_HARD_ABS ({current_abs_change:.2f} > {hard_abs_threshold})"

    if triggered:
        side = "YES" if net_change > 0 else "NO"
        return {
            "action": "trade",
            "side": side,
            "reason": reason_str
        }

    return None
