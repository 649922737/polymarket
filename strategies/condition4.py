"""
策略: Condition 4 - 上个周期波动突破 (Previous Cycle Fluctuation Breakout)
优先级: 4 (由文件名决定)

逻辑:
- 时间: 全程有效
- 条件:
  1. 当前周期的净值 (abs(net_change)) > 上个周期波动值 (High-Low) 的 80% (PREV_CYCLE_FLUC_PCT)
  2. 当前周期的净值 (abs(net_change)) > (过去5个周期波动平均值 / 2)
  3. 当前周期的净值 (abs(net_change)) > 当前价格的 0.1% (例如 60000 -> 60.0)
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
    logger.error("Condition4: Failed to import FluctuationRecorder")
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
            logger.info(f"Condition4: Fetching API for missing avg data. {req_start.strftime('%H:%M')} - {req_end.strftime('%H:%M')}")
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
            logger.error(f"Condition4: Fetch history failed: {e}")

    if fluctuations:
        return sum(fluctuations) / len(fluctuations)

    return None

def get_previous_fluctuation(start_time, recorder):
    """获取上一个周期的波动 (用于条件1)"""
    prev_start = start_time - timedelta(minutes=5)

    # Try local
    if recorder:
        val = recorder.get_fluctuation(prev_start)
        if val is not None:
            return val

    # Fetch specific single candle if needed (usually handled by batch fetch above, but just in case)
    # Reuse the batch fetch logic or rely on it being there.
    # For simplicity, let's assume batch fetch covers it or do a simple fetch here.
    return None # We rely on batch fetch to populate recorder

def check(state, config, indicators):
    # Only for 5m (Condition4 is a 5m strategy)
    if getattr(state, "market_type", "5m") != "5m":
        return None

    # Init recorder
    if not hasattr(state, "recorder_5m"):
        if FluctuationRecorder:
            setattr(state, "recorder_5m", FluctuationRecorder(file_suffix=""))
        else:
            return None
    recorder = state.recorder_5m

    # Caching
    avg_fluc_key = "cond4_avg_fluc_5"
    prev_fluc_key = "cond4_prev_fluc_5"
    market_id_key = "cond4_market_id"
    last_attempt_key = "cond4_last_attempt"

    current_market_id = state.active_market.get('id')
    cached_market_id = getattr(state, market_id_key, None)

    if cached_market_id != current_market_id:
        setattr(state, avg_fluc_key, None)
        setattr(state, prev_fluc_key, None)
        setattr(state, market_id_key, current_market_id)
        setattr(state, last_attempt_key, 0)

    avg_fluc = getattr(state, avg_fluc_key, None)
    prev_fluc = getattr(state, prev_fluc_key, None)
    last_attempt = getattr(state, last_attempt_key, 0)

    if avg_fluc is None or prev_fluc is None:
        if time.time() - last_attempt > 10:
            setattr(state, last_attempt_key, time.time())

            # 1. Get Avg (This also fetches data into recorder)
            avg_val = get_avg_fluctuation_past_5_cycles(state.start_time, 5, recorder)
            if avg_val is not None:
                setattr(state, avg_fluc_key, avg_val)
                avg_fluc = avg_val

            # 2. Get Prev (From recorder)
            # Ensure correct timezone
            st = state.start_time
            if st.tzinfo is None: st = st.replace(tzinfo=timezone.utc)
            else: st = st.astimezone(timezone.utc)

            prev_t = st - timedelta(minutes=5)
            prev_val = recorder.get_fluctuation(prev_t)
            if prev_val is not None:
                setattr(state, prev_fluc_key, prev_val)
                prev_fluc = prev_val

    if avg_fluc is None or prev_fluc is None:
        return None

    net_change = indicators['net_change']
    current_abs_change = abs(net_change)

    # Logic
    # 1. > Prev Cycle * 0.8
    # 2. > Avg(5 cycles) / 2
    # 3. > Current Price * 0.001 (0.1% of price)

    ratio_pct = config.get("PREV_CYCLE_FLUC_PCT", 0.8)

    threshold_1 = prev_fluc * ratio_pct
    threshold_2 = avg_fluc / 2.0
    threshold_3 = state.current_price * 0.001 # 0.1%

    if current_abs_change > threshold_1 and current_abs_change > threshold_2 and current_abs_change > threshold_3:
        side = "YES" if net_change > 0 else "NO"

        # RSI/MACD Filter (Optional, but recommended given Condition 4 poor performance)
        # Add basic filter similar to others
        rsi = indicators['rsi']
        macd_tuple = indicators.get('macd', (0,0,0))
        hist = macd_tuple[2]
        macd_thresh = config.get("MACD_THRESHOLD", -1.0)

        is_valid = False
        if side == "YES":
            if rsi < 85 and hist > macd_thresh: is_valid = True
        else:
            if rsi > 15 and hist < -macd_thresh: is_valid = True

        if not is_valid:
            logger.info(f"Condition4: Filtered | Side:{side} | RSI:{rsi:.1f} | MACD:{hist:.3f}")
            return None

        return {
            "action": "trade",
            "side": side,
            "reason": f"Condition_4_FLUC_BREAK (Net:{current_abs_change:.2f} > {ratio_pct}*Prev({prev_fluc:.2f}) & > Avg/2({threshold_2:.2f}) & > 0.1%({threshold_3:.2f}))"
        }

    return None
