"""
策略: Condition 3 (15m) - 上个周期波动突破
优先级: 3 (文件名决定)

逻辑:
- 时间: 全程有效
- 条件:
  1. 当前周期的净值 (abs(net_change)) > 上个周期(15m)波动值 (High-Low) 的 80% (PREV_CYCLE_FLUC_PCT_15)
  2. 当前周期的净值 (abs(net_change)) > (过去5个周期平均波动 / 2)
  3. 当前周期的净值 (abs(net_change)) > 当前价格的 0.15% (例如 60000 -> 90.0)
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

def get_avg_fluctuation_past_5_cycles(start_time, interval_minutes, recorder):
    """
    获取过去 5 个周期 (每个 interval_minutes) 的平均波动值
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

    fluctuations = []
    missing_cycles = []

    for t in cycle_starts:
        val = recorder.get_fluctuation(t)
        if val is not None:
            fluctuations.append(val)
        else:
            missing_cycles.append(t)

    # API 补全
    if missing_cycles:
        req_end = start_time
        req_start = start_time - timedelta(minutes=interval_minutes * 5)

        start_str = req_start.isoformat()
        end_str = req_end.isoformat()
        granularity = 60 * interval_minutes

        url = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
        params = {'start': start_str, 'end': end_str, 'granularity': granularity}
        headers = {"User-Agent": "Mozilla/5.0"}

        try:
            logger.info(f"Condition3 (15m): Fetching API for avg data. {req_start.strftime('%H:%M')} - {req_end.strftime('%H:%M')}")
            resp = requests.get(url, params=params, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data:
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

                        # Match cycle
                        for target_t in cycle_starts:
                            if abs((candle_time - target_t).total_seconds()) < 60:
                                fluctuations.append(fluc)
                                break
        except Exception as e:
            logger.error(f"Condition3 (15m): Fetch history failed: {e}")

    if fluctuations:
        return sum(fluctuations) / len(fluctuations)

    return None

def get_prev_cycle_fluctuation(start_time, recorder):
    """获取上一个周期的波动值 (15分钟)"""
    interval_minutes = 15
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    else:
        start_time = start_time.astimezone(timezone.utc)

    prev_cycle_start = start_time - timedelta(minutes=interval_minutes)

    # 尝试从本地读取 (API 补全由 avg 函数统一处理，或者这里单独处理)
    # 为了保险，还是保留这里的 API 逻辑，以防 avg 函数没运行
    val = recorder.get_fluctuation(prev_cycle_start)
    if val is not None:
        return val

    return None # 实际上 avg 函数的 batch fetch 应该已经覆盖了这里

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
    avg_fluc_key = "cond3_avg_fluc_15"
    prev_fluc_key = "cond3_prev_fluc_15"
    market_id_key = "cond3_market_id_15m"
    last_attempt_key = "cond3_last_attempt_15m"

    # Reset on market switch
    current_market_id = state.active_market.get('id')
    cached_market_id = getattr(state, market_id_key, None)
    if cached_market_id != current_market_id:
        setattr(state, avg_fluc_key, None)
        setattr(state, prev_fluc_key, None)
        setattr(state, market_id_key, current_market_id)
        setattr(state, last_attempt_key, 0)

    # Fetch
    avg_fluc = getattr(state, avg_fluc_key, None)
    prev_fluc = getattr(state, prev_fluc_key, None)
    last_attempt = getattr(state, last_attempt_key, 0)

    if avg_fluc is None or prev_fluc is None:
        if time.time() - last_attempt > 10:
            setattr(state, last_attempt_key, time.time())

            # 1. Get Avg (This populates recorder)
            val_avg = get_avg_fluctuation_past_5_cycles(state.start_time, 15, recorder)
            if val_avg is not None:
                setattr(state, avg_fluc_key, val_avg)
                avg_fluc = val_avg

            # 2. Get Prev
            val_prev = get_prev_cycle_fluctuation(state.start_time, recorder)
            if val_prev is not None:
                setattr(state, prev_fluc_key, val_prev)
                prev_fluc = val_prev

    if avg_fluc is None or prev_fluc is None:
        return None

    net_change = indicators['net_change']
    current_abs_change = abs(net_change)

    # Configs
    ratio_pct = config.get("PREV_CYCLE_FLUC_PCT_15", 0.8)

    threshold_1 = prev_fluc * ratio_pct
    threshold_2 = avg_fluc / 2.0
    threshold_3 = state.current_price * 0.0015 # 0.15%

    if current_abs_change > threshold_1 and current_abs_change > threshold_2 and current_abs_change > threshold_3:
        side = "YES" if net_change > 0 else "NO"

        # RSI/MACD 过滤
        rsi = indicators['rsi']
        macd_tuple = indicators.get('macd', (0,0,0))
        hist = macd_tuple[2]
        macd_thresh = config.get("MACD_THRESHOLD", -1.0)

        is_valid = False
        if side == "YES":
            if rsi < 85 and hist > macd_thresh:
                is_valid = True
        else:
            if rsi > 15 and hist < -macd_thresh:
                is_valid = True

        if not is_valid:
            logger.info(f"Condition3 (15m): Filtered | Side:{side} | RSI:{rsi:.1f} | MACD:{hist:.3f}")
            return None

        reason_str = f"Condition_3_15M_PREV (Net:{current_abs_change:.2f} > {ratio_pct}*Prev({prev_fluc:.2f}) & > Avg/2({threshold_2:.2f}) & > 0.15%({threshold_3:.2f}))"

        return {
            "action": "trade",
            "side": side,
            "reason": reason_str,
            "size_multiplier": 1.0
        }

    return None
