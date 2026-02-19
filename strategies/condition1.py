"""
策略: Condition 1 - 强波动突破 (Condition 1 - Strong Fluctuation Breakout)
优先级: 1 (由文件名决定)

逻辑:
- 时间: 全程有效
- 条件:
  1. 当前周期的净值 (abs(net_change)) > 过去5个周期最大波动值的 80% (可配置 PREV_CYCLE_FLUC_PCT_5)
  2. 当前周期的净值 (abs(net_change)) > 45 (可配置 PREV_CYCLE_MIN_ABS_5)
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
    recorder = FluctuationRecorder()
except ImportError:
    logger.error("Condition5: Failed to import FluctuationRecorder")
    recorder = None

def get_max_fluctuation_past_5_cycles(start_time):
    """
    获取过去 5 个周期 (每个 5 分钟) 的最大波动值
    1. 优先从本地读取
    2. 如果本地缺失，批量从 API 获取
    3. 记录获取到的数据到本地
    """
    if not recorder:
        return None

    # 确保 UTC
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    else:
        start_time = start_time.astimezone(timezone.utc)

    # 过去 5 个周期的起始时间
    # T-5, T-10, T-15, T-20, T-25
    cycle_starts = []
    for i in range(1, 6):
        t = start_time - timedelta(minutes=5 * i)
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
        logger.debug(f"Condition5: Local hit for all 5 cycles. Max: {max_fluc}")
        return max_fluc

    # 如果有缺失，需要从 API 获取
    # 为了减少 API 调用，我们一次性获取范围数据
    # Range: 最早缺失时间 -> start_time

    # 实际上，我们可以直接获取过去 25 分钟的数据，覆盖所有需要的周期
    req_end = start_time
    req_start = start_time - timedelta(minutes=25)

    start_str = req_start.isoformat()
    end_str = req_end.isoformat()

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
        logger.info(f"Condition1: Fetching API for missing cycles ({len(missing_cycles)}). Range: {req_start.strftime('%H:%M')} - {req_end.strftime('%H:%M')}")
        resp = requests.get(url, params=params, headers=headers, timeout=5)

        if resp.status_code == 200:
            data = resp.json()
            # [time, low, high, open, close, volume]
            # 数据是按时间倒序排列的 (最新的在前面)

            if data:
                # 处理 API 返回的数据
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

                    # 检查这个 candle 是否是我们需要的 5 个周期之一
                    # 我们需要的周期起始时间是 cycle_starts 中的
                    # candle_time 应该是 5分钟对齐的

                    # 简单的检查方法：看 candle_time 是否在我们需要的时间列表中
                    # 注意：浮点数/时间戳比较可能需要容差，但在整 300s granularity 下应该还好
                    # 最好是用 timestamp 比较

                    for target_t in cycle_starts:
                        if abs((candle_time - target_t).total_seconds()) < 60: # 允许 1 分钟误差
                            fetched_fluctuations.append(fluc)
                            break

                # 合并本地读取的和新获取的
                all_fluctuations = fluctuations + fetched_fluctuations

                if all_fluctuations:
                    max_fluc = max(all_fluctuations)
                    logger.info(f"Condition1: Updated fluctuations. Got {len(all_fluctuations)}/5 cycles. Max: {max_fluc:.2f}")
                    return max_fluc
                else:
                    logger.warning("Condition1: No matching cycles found in API data.")
            else:
                logger.warning(f"Condition1: API returned empty data for {start_str}")
        else:
            logger.warning(f"Condition1: Coinbase API Error: {resp.status_code} {resp.text}")

    except Exception as e:
        logger.error(f"Condition1: Fetching history failed: {e}")

    # 如果 API 失败，但本地有一些数据，可以使用本地的最大值吗？
    # 策略上可能偏向保守，如果数据不全，可能不应该交易，或者基于已知数据的最大值？
    # 这里我们返回已知数据的最大值，如果完全没有数据则返回 None
    if fluctuations:
        return max(fluctuations)

    return None

def check(state, config, indicators):
    # 1. 检查是否切换了市场，如果是则重置缓存
    current_market_id = state.active_market.get('id')
    cached_market_id = getattr(state, 'prev_fluc_market_id_5', None)

    if cached_market_id != current_market_id:
        state.prev_cycle_fluctuation_5 = None
        state.prev_fluc_market_id_5 = current_market_id
        state.last_fluctuation_attempt_time_5 = 0

    # 2. 尝试获取/读取缓存的最大波动值
    if not hasattr(state, 'prev_cycle_fluctuation_5'):
        state.prev_cycle_fluctuation_5 = None
        state.last_fluctuation_attempt_time_5 = 0

    if state.prev_cycle_fluctuation_5 is None:
        # 每 10 秒重试一次
        if time.time() - state.last_fluctuation_attempt_time_5 > 10:
            state.last_fluctuation_attempt_time_5 = time.time()
            val = get_max_fluctuation_past_5_cycles(state.start_time)
            if val is not None:
                state.prev_cycle_fluctuation_5 = val

    # 如果还是没有数据，无法判断，返回 None
    if state.prev_cycle_fluctuation_5 is None:
        return None

    max_prev_fluc = state.prev_cycle_fluctuation_5
    net_change = indicators['net_change']

    # 2. 判断条件
    # A. 比例阈值 (修改为 80% default, 原来是 90%)
    ratio_pct = config.get("PREV_CYCLE_FLUC_PCT_5", 0.8) # 80%
    ratio_threshold = max_prev_fluc * ratio_pct

    # B. 绝对值阈值
    abs_limit = config.get("PREV_CYCLE_MIN_ABS_5", 45.0) # 45

    # C. 绝对值硬阈值 (无需满足波动率比例)
    hard_abs_threshold = 140.0

    current_abs_change = abs(net_change)

    # 逻辑: (满足比例要求 AND 大于最小绝对值) OR (大于硬阈值 140)
    if (current_abs_change > ratio_threshold and current_abs_change > abs_limit) or (current_abs_change > hard_abs_threshold):
        side = "YES" if net_change > 0 else "NO"

        reason_str = ""
        if current_abs_change > hard_abs_threshold:
            reason_str = f"Condition_1_HARD_ABS ({current_abs_change:.2f} > {hard_abs_threshold})"
        else:
            reason_str = f"Condition_1_STRONG_FLUC ({current_abs_change:.2f} > {ratio_pct}*Max({max_prev_fluc:.2f}) & > {abs_limit})"

        return {
            "action": "trade",
            "side": side,
            "reason": reason_str
        }

    return None
