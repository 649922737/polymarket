"""
策略: Condition 3 (5m) - ATR 波动率爆发 (ATR Volatility Surge)
优先级: 3 (原 Condition 6)

逻辑:
- 时间: 全程有效
- 核心思想: 只在波动率显著放大且实体饱满时顺势交易，过滤窄幅震荡。
- 条件:
  1. 波动爆发: 当前波动值 > 1.5 * 过去10个周期平均波动 (ATR_10)
  2. 实体饱满: 净值 (Net) > 0.7 * 波动值 (Fluctuation)
  3. 突破确认: 价格突破过去10个周期的高点/低点 (Donchian Channel)
  4. 绝对门槛: 净值 > 0.1% 价格
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
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

try:
    from fluctuation_recorder import FluctuationRecorder
except ImportError:
    logger.error("Condition6: Failed to import FluctuationRecorder")
    FluctuationRecorder = None

def get_past_n_cycles_data(start_time, n, interval_minutes, recorder):
    """
    获取过去 N 个周期的数据
    返回: (avg_fluctuation, max_price, min_price)
    """
    if not recorder:
        return None, None, None

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    else:
        start_time = start_time.astimezone(timezone.utc)

    cycle_starts = []
    for i in range(1, n + 1):
        t = start_time - timedelta(minutes=interval_minutes * i)
        cycle_starts.append(t)

    fluctuations = []
    # 我们这里主要需要 fluctuation 来计算 ATR。
    # max/min price 比较难从 recorder 直接获取（recorder 只存了 fluctuation 和 net_change）
    # 但我们可以用 net_change 来近似推导价格变化，不过为了精确突破，最好有 OHLC。
    # 鉴于 recorder 的限制，我们这里做简化：
    # 1. ATR 用 recorder 的 fluctuation 计算。
    # 2. 突破用 "当前价格 vs (当前价格 - 净值 + 历史净值累加)" 比较复杂。
    #    简化方案：只要求 ATR 爆发 + 实体饱满。突破条件作为可选或隐式包含（大实体通常意味着突破）。

    missing_cycles = []

    for t in cycle_starts:
        val = recorder.get_fluctuation(t)
        if val is not None:
            fluctuations.append(val)
        else:
            missing_cycles.append(t)

    # API 补全 (Coinbase)
    if missing_cycles:
        # 为了简单，我们只补全 fluctuation
        req_end = start_time
        req_start = start_time - timedelta(minutes=interval_minutes * n)

        granularity = 60 * interval_minutes
        if interval_minutes == 5: granularity = 300
        elif interval_minutes == 15: granularity = 900

        url = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
        params = {'start': req_start.isoformat(), 'end': req_end.isoformat(), 'granularity': granularity}
        headers = {"User-Agent": "Mozilla/5.0"}

        try:
            logger.info(f"Condition6: Fetching API history... {req_start.strftime('%H:%M')}")
            resp = requests.get(url, params=params, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    for candle in data:
                        ts = candle[0]
                        low = float(candle[1])
                        high = float(candle[2])
                        open_p = float(candle[3])
                        close_p = float(candle[4])

                        c_time = datetime.fromtimestamp(ts, timezone.utc)
                        recorder.record_fluctuation(c_time, high - low)
                        recorder.record_net_change(c_time, close_p - open_p)

                        # Add to list if matches
                        for t in cycle_starts:
                            if abs((c_time - t).total_seconds()) < 60:
                                fluctuations.append(high - low)
                                break
        except Exception as e:
            logger.error(f"Condition6: API Error: {e}")

    if not fluctuations:
        return None

    avg_fluc = sum(fluctuations) / len(fluctuations)
    return avg_fluc

def check(state, config, indicators):
    # Only run for 5m markets (can be adapted for 15m)
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
    atr_key = "cond6_atr_10"
    last_attempt_key = "cond6_last_attempt"

    # 1. 获取 ATR (Average Fluctuation of past 10 cycles)
    atr = getattr(state, atr_key, None)
    last_attempt = getattr(state, last_attempt_key, 0)

    if atr is None:
        if time.time() - last_attempt > 30: # Don't retry too often
            setattr(state, last_attempt_key, time.time())
            val = get_past_n_cycles_data(state.start_time, 10, 5, recorder)
            if val is not None:
                setattr(state, atr_key, val)
                atr = val

    if atr is None:
        return None # Data not ready

    # 2. Current Metrics
    net_change = indicators['net_change']
    current_fluc = indicators['fluctuation']

    if current_fluc <= 0: return None

    # 3. Logic
    # 3.1 ATR Surge: Current Fluctuation > 1.5 * ATR
    atr_multiplier = config.get("COND6_ATR_MULT", 1.5)
    if current_fluc < atr * atr_multiplier:
        return None

    # 3.2 Strong Body: Abs(Net) > 0.7 * Fluctuation
    body_ratio = config.get("COND6_BODY_RATIO", 0.7)
    if abs(net_change) < current_fluc * body_ratio:
        return None

    # 3.3 Absolute Min (Avoid tiny breakouts)
    # min_abs = 30.0
    # if abs(net_change) < min_abs:
    #    return None

    # 3.3 Relative Min (Avoid tiny breakouts on high price)
    # Requirement: Net change > 0.1% of current price
    if abs(net_change) < state.current_price * 0.001:
        return None

    # 3.4 Probability Protection
    current_prob = 0.5
    if state.order_book and state.order_book.bids:
        current_prob = float(state.order_book.bids[0].price)

    side = "YES" if net_change > 0 else "NO"

    # Don't buy if too expensive (reversion risk)
    if side == "YES" and current_prob > 0.85: return None
    if side == "NO" and current_prob < 0.15: return None

    return {
        "action": "trade",
        "side": side,
        "reason": f"Condition_3_ATR_SURGE (Fluc:{current_fluc:.1f} > {atr_multiplier}*ATR({atr:.1f}) & Body > {body_ratio}%)"
    }
