import time
import os
import glob
import importlib.util
from datetime import datetime, timezone
import logging

logger = logging.getLogger("PolyBot")

# ==================== 策略配置 ====================
# 你可以在这里修改阈值
STRATEGY_CONFIG = {
    "VOL_THRESHOLD_PCT": 0.0015,   # 0.15% 波动门槛 (条件1)
    "NET_CHANGE_PCT": 0.0011,      # 0.1% 净变化门槛 (条件1)
    "BREAK_THRESHOLD_PCT": 0.001,  # 0.1% 突破门槛 (条件4)
    "REVERSAL_VOL_PCT": 0.0015,     # 0.15% 反转波动 (条件2)
    "REVERSAL_NET_PCT": 0.0009,    # 0.08% 反转后幅度 (条件2)
    "PREV_CYCLE_FLUC_PCT": 0.6,    # 60% 上个周期波动 (条件3)
    "PREV_CYCLE_MIN_ABS": 65.0,    # 最小绝对值 65 (条件3)
    "MIN_ABS_CHANGE": 80.0,        # 最小绝对涨跌幅 (USD)
    "MAX_PROB": 0.85,              # 最大概率 85%
    "MACD_THRESHOLD": -1.0         # MACD 阈值 (原来是 0)
}

# ==================== 策略加载器 ====================
_strategies = []

def load_strategies():
    """动态加载 strategies 目录下的所有条件文件"""
    global _strategies
    _strategies = []

    # 获取当前文件所在目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    strategies_dir = os.path.join(base_dir, "strategies")

    # 查找所有 condition*.py 文件
    pattern = os.path.join(strategies_dir, "condition*.py")
    files = sorted(glob.glob(pattern)) # 按文件名排序，保证 condition1 < condition2 < ...

    if not files:
        logger.warning(f"未在 {strategies_dir} 找到任何策略文件！")
        return

    for file_path in files:
        module_name = os.path.basename(file_path).replace(".py", "")
        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, "check"):
                _strategies.append({
                    "name": module_name,
                    "module": module
                })
                logger.info(f"已加载策略: {module_name} (Priority: {len(_strategies)})")
            else:
                logger.warning(f"策略文件 {module_name} 缺少 check 函数，跳过。")
        except Exception as e:
            logger.error(f"加载策略 {module_name} 失败: {e}")

# 初始化时加载一次
load_strategies()

# ==================== 指标函数 ====================

def calculate_rsi(data, window=14):
    if len(data) < window + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(data)):
        change = data[i] - data[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    if not gains: return 50.0

    recent_gains = gains[-window:]
    recent_losses = losses[-window:]

    avg_gain = sum(recent_gains) / window
    avg_loss = sum(recent_losses) / window

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_macd(data, slow=26, fast=12, signal=9):
    if len(data) < slow:
        return 0, 0, 0

    def get_ema(values, window):
        emas = []
        alpha = 2 / (window + 1)
        ema = sum(values[:window]) / window
        emas.append(ema)
        for price in values[window:]:
            ema = (price * alpha) + (ema * (1 - alpha))
            emas.append(ema)
        return emas

    ema_fast = get_ema(data, fast)
    ema_slow = get_ema(data, slow)

    offset = slow - fast
    ema_fast_aligned = ema_fast[offset:]

    macd_line = []
    for f, s in zip(ema_fast_aligned, ema_slow):
        macd_line.append(f - s)

    if len(macd_line) < signal:
        return macd_line[-1], 0, 0

    signal_line = get_ema(macd_line, signal)

    return macd_line[-1], signal_line[-1], (macd_line[-1] - signal_line[-1])

# ==================== 策略主逻辑 ====================

def execute_strategy(state, trigger_callback):
    """
    执行策略逻辑：
    1. 计算当前市场状态和指标
    2. 按顺序遍历所有已加载的策略
    3. 如果某个策略返回 trade 信号，立即触发并返回
    """
    if not state.active_market or state.current_price == 0 or state.has_traded:
        return

    # 使用 UTC 时间计算 elapsed
    now = datetime.now(timezone.utc)
    if state.start_time.tzinfo is None:
        start_t = state.start_time.replace(tzinfo=timezone.utc)
    else:
        start_t = state.start_time

    elapsed = (now - start_t).total_seconds()

    # 市场未开始或已经结束，返回
    if elapsed < 0 or elapsed > 300:
        return

    # 计算各项指标
    cur_p = state.current_price
    start_p = state.start_price

    # 将 start_price 加入计算范围，以正确反映从开盘以来的波动
    # 如果 price_history 为空，则使用 cur_p 和 start_p
    effective_history = state.price_history + [start_p] if state.price_history else [cur_p, start_p]

    max_p = max(effective_history)
    min_p = min(effective_history)

    fluctuation = max_p - min_p
    net_change = cur_p - start_p

    # 更新反转计数 (Crossing start_price)
    current_side = 1 if net_change > 0 else (-1 if net_change < 0 else 0)
    if state.last_side_sign != 0 and current_side != 0:
        if current_side != state.last_side_sign:
            state.reversal_count += 1
            logger.info(f"检测到反转! 当前计数: {state.reversal_count}, 方向: {current_side}")
    if current_side != 0:
        state.last_side_sign = current_side

    # 准备指标包 (Context)
    rsi_val = calculate_rsi(state.price_history)
    macd_val = calculate_macd(state.price_history)

    indicators = {
        "elapsed": elapsed,
        "fluctuation": fluctuation,
        "net_change": net_change,
        "rsi": rsi_val,
        "macd": macd_val
    }

    # --- 定时日志打印 (每 5 秒) ---
    if time.time() - state.last_log_time > 5:
        # 解包 MACD Hist
        hist = macd_val[2] if macd_val else 0
        logger.info(f"[{int(elapsed)}s] 现价:{cur_p:.1f} | 净变:{net_change:+.1f} | 波动:{fluctuation:.1f} | 反转:{state.reversal_count} | RSI:{rsi_val:.1f} | MACD:{hist:.3f}")
        state.last_log_time = time.time()

    # ========================== 动态执行策略 ==========================

    for strategy in _strategies:
        try:
            # 调用策略模块的 check 函数
            result = strategy["module"].check(state, STRATEGY_CONFIG, indicators)

            if result and result.get("action") == "trade":
                logger.info(f"★ 策略 [{strategy['name']}] 触发信号！原因: {result['reason']}")

                trigger_callback(
                    result["side"],
                    result["reason"],
                    cur_p,
                    net_change,
                    fluctuation,
                    size_multiplier=result.get("size_multiplier", 1.0)
                )
                return # 立即退出，不再检查后续低优先级策略

        except Exception as e:
            logger.error(f"策略 {strategy['name']} 执行出错: {e}")
