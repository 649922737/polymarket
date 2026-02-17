import time
import json
import os
import threading
import requests
import logging
import websocket
from datetime import datetime, timedelta, timezone
from dateutil import parser as date_parser
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType, OrderArgs
from py_clob_client.order_builder.constants import BUY
from eth_account import Account
from decimal import Decimal
import strategy_executor
import settle
from binance_price import BinancePrice
from price_recorder import PriceRecorder

# ==================== 配置区 ====================
CONFIG = {
    "HOST": "https://clob.polymarket.com",
    "CHAIN_ID": 137,
    "RPC_URL": "https://polygon-rpc.com",
    "PRIVATE_KEY": os.getenv("POLY_PRIVATE_KEY"),
    "FUNDER": os.getenv("POLY_FUNDER"),
    "SIGNATURE_TYPE": int(os.getenv("POLY_SIGNATURE_TYPE", 1)),
    "GAMMA_API": "https://gamma-api.polymarket.com",
    # 切换到 Coinbase WS，因为它更贴近 Polymarket (UMA) 的结算源
    "COINBASE_WS": "wss://ws-feed.exchange.coinbase.com",
    "BINANCE_WS": "wss://stream.binance.com:9443/ws/btcusdt@trade",
    "ORDER_AMOUNT": float(os.getenv("POLY_ORDER_AMOUNT", 2.0)),
    "SIMULATION_MODE": False,  # 设为 True 则只打印日志不下单
    "PRICE_OFFSET": float(os.getenv("POLY_PRICE_OFFSET", 0.0)), # 价格偏移修正 (Coinbase - Polymarket)
    "SETTLE_INTERVAL": int(os.getenv("POLY_SETTLE_INTERVAL", 600)), # 结算间隔(秒)，默认 10 分钟
}

# CTF Contract (Conditional Tokens)
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CTF_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"}
        ],
        "name": "redeemPositions",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

if not CONFIG["PRIVATE_KEY"]:
    raise ValueError("未设置环境变量: POLY_PRIVATE_KEY")
if not CONFIG["FUNDER"]:
    raise ValueError("未设置环境变量: POLY_FUNDER")

# ==================== 日志初始化 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("PolyBot")

# ==================== 账户检查 ====================
try:
    derived_address = Account.from_key(CONFIG["PRIVATE_KEY"]).address
    logger.info(f"私钥对应地址 (Signer): {derived_address}")
    logger.info(f"配置下单地址 (Funder): {CONFIG['FUNDER']}")
    logger.info(f"下单金额 (Order Amount): {CONFIG['ORDER_AMOUNT']} USDC")
    logger.info(f"签名类型 (SignatureType): {CONFIG['SIGNATURE_TYPE']} (0=EOA, 1=Proxy, 2=Kernel)")

    if derived_address.lower() == CONFIG["FUNDER"].lower() and CONFIG["SIGNATURE_TYPE"] != 0:
        logger.warning("提示: Signer 与 Funder 相同，但签名类型不是 0 (EOA)。如果您没有使用代理钱包，请将 POLY_SIGNATURE_TYPE 设为 0。")
    if derived_address.lower() != CONFIG["FUNDER"].lower() and CONFIG["SIGNATURE_TYPE"] == 0:
        logger.warning("提示: Signer 与 Funder 不同，但签名类型是 0 (EOA)。这通常会导致签名无效。")
except Exception as e:
    logger.error(f"账户检查失败: {e}")

# ==================== 全局状态 ====================
class MarketState:
    def __init__(self):
        self.current_price = 0.0
        self.price_history = []
        self.active_market = None
        self.start_price = 0.0
        self.start_time = None
        self.has_traded = False
        self.last_log_time = 0
        self.last_price_update_time = time.time()
        self.reversal_count = 0
        self.last_side_sign = 0 # 1: > start_price, -1: < start_price
        self.last_recorded_minute = -1 # 用于防止重复记录同一分钟的价格

        # 初始化 PriceRecorder
        self.recorder = PriceRecorder()

        # 初始化 Binance
        try:
            self.binance = BinancePrice()
        except:
            self.binance = None

state = MarketState()

# ==================== 核心功能函数 ====================

def get_market_start_time(question):
    """解析市场标题以获取起始时间"""
    try:
        # 格式1: "Bitcoin Up or Down - February 15, 8:35AM-8:40AM ET"
        if "Up or Down" in question:
            # 分割出时间部分: "February 15, 8:35AM-8:40AM ET"
            try:
                time_part = question.split(' - ')[-1].strip()
                # 处理只有单个时间点的情况 "February 16, 8AM ET"
                if "AM-" not in time_part and "PM-" not in time_part:
                     # 尝试解析 "February 16, 8AM ET"
                     # 先检查是否包含 "ET"
                     if "ET" in time_part:
                         date_str = time_part.split(',')[0].strip()
                         time_str = time_part.split(',')[1].replace('ET', '').strip()
                         full_str = f"{date_str} {datetime.now().year} {time_str}"
                         # 尝试多种时间格式
                         for fmt in ['%B %d %Y %I%p', '%B %d %Y %I:%M%p']:
                             try:
                                 dt = datetime.strptime(full_str, fmt)
                                 # ET (UTC-5) to UTC
                                 dt_utc = dt.replace(tzinfo=timezone(timedelta(hours=-5))).astimezone(timezone.utc)
                                 return dt_utc
                             except:
                                 continue

                # 处理时间段 "February 15, 8:35AM-8:40AM ET"
                date_str = time_part.split(',')[0].strip() # "February 15"
                time_range = time_part.split(',')[1].strip() # "8:35AM-8:40AM ET"
                start_time_str = time_range.split('-')[0].strip() # "8:35AM"

                full_str = f"{date_str} {datetime.now().year} {start_time_str}"
                dt_et = datetime.strptime(full_str, '%B %d %Y %I:%M%p')
                # ET (UTC-5) to UTC
                dt_utc = dt_et.replace(tzinfo=timezone(timedelta(hours=-5))).astimezone(timezone.utc)
                logger.info(f"解析时间: {full_str} -> {dt_et} (ET) -> {dt_utc} (UTC)")
                return dt_utc
            except ValueError:
                pass

        # 格式2: "Bitcoin above $XX,XXX at 8:30PM ET?" (旧格式)
        if ' at ' in question:
            parts = question.split(' at ')
            time_str = parts[-1].split(' ET')[0].strip()
            now = datetime.now()
            full_time_str = f"{now.strftime('%Y-%m-%d')} {time_str}"
            dt = datetime.strptime(full_time_str, '%Y-%m-%d %I:%M%p')
            return dt

        return None
    except Exception as e:
        logger.error(f"解析时间失败 ({question}): {e}")
        return None

def find_btc_market():
    """发现当前活跃的 5 分钟 BTC 市场 (通过Slug直接查询)"""
    try:
        # 1. 优先检查当前锁定市场是否仍然有效
        if state.active_market:
            # 检查时间是否结束
            now_utc = datetime.now(timezone.utc)
            start_time = state.start_time
            if start_time and start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)

            if start_time:
                elapsed = (now_utc - start_time).total_seconds()
                # 如果市场还在 300s 窗口内，或者还没开始(负数)，保持锁定
                # 注意：这里放宽到 310s，避免临界点跳变
                if elapsed < 310:
                    return state.active_market
                else:
                    logger.info(f"当前锁定市场已过期 (Elapsed={elapsed:.1f}s)，解除锁定。")
            else:
                logger.warning("当前市场无 StartTime，无法锁定，重新搜索...")

        # 2. 如果没有锁定或已结束，寻找新市场
        # 计算当前 UTC 时间对应的 5分钟窗口 Start TS
        now_utc = datetime.now(timezone.utc)
        ts = int(now_utc.timestamp())
        current_window_start = ts - (ts % 300)

        # 如果当前窗口已过大半 (比如 > 290s)，则查找下一个窗口
        elapsed = ts - current_window_start
        target_ts = current_window_start
        if elapsed > 290:
            target_ts += 300

        # 尝试查询 Current 和 Next
        for search_ts in [target_ts, target_ts + 300]:
            slug = f"btc-updown-5m-{search_ts}"
            url = f"{CONFIG['GAMMA_API']}/markets?slug={slug}"

            try:
                resp = requests.get(url)
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    m = data[0]
                    # 再次确认是 Active
                    if m.get('active') and not m.get('closed'):
                        return m
            except:
                pass

    except Exception as e:
        logger.error(f"查找市场失败: {e}")
    return None

# ==================== 辅助函数: 获取 Coinbase 历史价格 ====================
def get_coinbase_open_price(dt):
    """获取指定时间点 (UTC) 的 Coinbase BTC-USD 开盘价"""
    if not dt: return None

    # 确保时间是 UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    # 请求当分钟的 Candle
    start_str = dt.isoformat()
    end_str = (dt + timedelta(minutes=1)).isoformat()

    url = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
    params = {
        'start': start_str,
        'end': end_str,
        'granularity': 60
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
    }

    # 重试机制 (最多 3 次)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10) # 增加超时时间到 10s

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    candle = data[0]
                    open_price = float(candle[3])
                    logger.info(f"获取历史价格成功 ({dt}): {open_price}")
                    return open_price
                else:
                    # 数据为空可能还没生成，稍等再试
                    logger.warning(f"Coinbase 返回数据为空 (尝试 {attempt+1}/{max_retries})")
            else:
                logger.warning(f"Coinbase API Error: {resp.status_code} {resp.text} (尝试 {attempt+1}/{max_retries})")

        except Exception as e:
            logger.warning(f"获取 Coinbase 历史价格异常: {e} (尝试 {attempt+1}/{max_retries})")

        # 失败后等待 1-2 秒再重试
        if attempt < max_retries - 1:
            time.sleep(2)

    logger.error("多次尝试获取 Coinbase 历史价格失败，放弃。")
    return None

def get_binance_open_price(dt):
    """获取指定时间点 (UTC) 的 Binance BTCUSDT 开盘价 (作为备选)"""
    if not dt: return None

    # 确保时间是 UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    # Binance API 需要时间戳 (毫秒)
    ts = int(dt.timestamp() * 1000)

    url = "https://api.binance.com/api/v3/klines"
    params = {
        'symbol': 'BTCUSDT',
        'interval': '1m',
        'startTime': ts,
        'limit': 1
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # 格式: [Open Time, Open, High, Low, Close, Volume, Close Time, ...]
            if isinstance(data, list) and len(data) > 0:
                candle = data[0]
                # 检查时间戳是否匹配 (Binance 返回的是该 K 线起始时间)
                # 允许 1 分钟内的误差
                candle_ts = candle[0]
                if abs(candle_ts - ts) < 60000:
                    open_price = float(candle[1])
                    logger.info(f"Binance 获取历史价格成功 ({dt}): {open_price}")
                    return open_price
                else:
                    logger.warning(f"Binance 返回数据时间不匹配:Req={ts}, Res={candle_ts}")
            else:
                logger.warning("Binance 返回数据为空")
        else:
            logger.warning(f"Binance API Error: {resp.status_code} {resp.text}")

    except Exception as e:
        logger.warning(f"获取 Binance 历史价格异常: {e}")

    return None

# ==================== 指标计算 ====================
# 指标计算已移至 strategy_executor.py


def calculate_macd(data, slow=26, fast=12, signal=9):
    if len(data) < slow:
        return 0, 0, 0

    # 计算 EMA 序列
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

    # 对齐长度
    # ema_fast 长度会比 ema_slow 长 (slow-fast)
    # 我们只关心最后的值，但为了计算 Signal 线，需要 MACD 序列

    # 重新计算，只取最后一段有效重叠区
    min_len = min(len(ema_fast), len(ema_slow))
    # 但由于起始点不同，ema_fast[i] 和 ema_slow[j] 对应的时间点需要对齐
    # get_ema 返回的列表第0个元素对应 data[window-1]

    # data: [0, 1, ..., fast-1, ..., slow-1, ...]
    # ema_fast[0] corresponds to data[fast-1]
    # ema_slow[0] corresponds to data[slow-1]

    # 对齐：ema_fast 需要切掉前 (slow - fast) 个元素
    offset = slow - fast
    ema_fast_aligned = ema_fast[offset:]

    macd_line = []
    for f, s in zip(ema_fast_aligned, ema_slow):
        macd_line.append(f - s)

    if len(macd_line) < signal:
        return macd_line[-1], 0, 0

    signal_line = get_ema(macd_line, signal)

    return macd_line[-1], signal_line[-1], (macd_line[-1] - signal_line[-1])

def log_order_to_file(market_id, condition, side, price, poly_price, amount, start_price, trigger_price):
    try:
        filename = "trade_history.csv"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 检查是否需要写入表头
        file_exists = os.path.isfile(filename)

        with open(filename, "a") as f:
            if not file_exists:
                f.write("timestamp,market_id,condition,side,limit_price,poly_price,amount,start_price,trigger_price\n")

            line = f"{timestamp},{market_id},{condition},{side},{price},{poly_price},{amount},{start_price},{trigger_price}\n"
            f.write(line)
    except Exception as e:
        logger.error(f"写入日志失败: {e}")

# ==================== WebSocket 价格流 (Coinbase Only) ====================

ws_fail_count = 0

def on_message(ws, message):
    try:
        data = json.loads(message)
        price = 0.0

        # Coinbase 格式: {"type": "ticker", "price": "...", ...}
        if data.get('type') == 'ticker' and 'price' in data:
            price = float(data['price'])

        if price > 0:
            state.current_price = price
            state.last_price_update_time = time.time()

            # --- 本地价格记录逻辑 ---
            # 每逢 5 分钟整点 (0, 5, 10...) 记录一次
            # 我们只在每分钟的前 10 秒内尝试记录，确保抓取的是“Open Price”附近的
            now_utc = datetime.now(timezone.utc)
            if now_utc.minute % 5 == 0 and now_utc.second < 15:
                # 检查这一分钟是否已经记录过
                current_minute_id = now_utc.minute
                # 注意：跨小时分钟数会重复，但加上日期/小时判断太繁琐，简单判断即可
                # 只要分钟变了就可以。或者用完整时间戳判断？
                # state.last_recorded_minute 存的是 minute 整数
                # 为了防止小时切换时的重复，我们可以存完整字符串
                minute_key = now_utc.strftime("%Y%m%d%H%M")

                if state.last_recorded_minute != minute_key:
                    state.recorder.record_price(now_utc, price)
                    state.last_recorded_minute = minute_key

            if state.active_market:
                state.price_history.append(state.current_price)
                if len(state.price_history) > 1000: state.price_history.pop(0)
    except Exception as e:
        logger.error(f"处理 WS 消息失败: {e}")

def on_open(ws):
    global ws_fail_count
    logger.info(f"WS Connected (coinbase). Subscribing...")
    ws_fail_count = 0 # 重置失败计数
    msg = {
        "type": "subscribe",
        "product_ids": ["BTC-USD"],
        "channels": ["ticker"]
    }
    ws.send(json.dumps(msg))

def start_ws():
    global ws_fail_count
    while True:
        try:
            url = CONFIG["COINBASE_WS"]
            logger.info(f"正在连接 WS (coinbase): {url}")

            ws = websocket.WebSocketApp(
                url,
                on_message=on_message,
                on_open=on_open,
                on_error=lambda ws, e: logger.error(f"WS Error: {e}"),
                on_close=lambda *args: logger.warning("WS Closed"),
            )
            # 使用 ping_interval 保持连接活跃
            ws.run_forever(ping_interval=30, ping_timeout=10)

            # 连接断开
            ws_fail_count += 1

        except Exception as e:
            logger.error(f"WS 运行异常: {e}")
            ws_fail_count += 1

        # 退避重连逻辑
        if ws_fail_count <= 3:
            sleep_time = 5
        elif ws_fail_count <= 6:
            sleep_time = 10
        else:
            sleep_time = 20

        logger.warning(f"WS 连接断开 (Fail Count: {ws_fail_count})，{sleep_time}秒后重连...")
        time.sleep(sleep_time)

threading.Thread(target=start_ws, daemon=True).start()

# ==================== 策略逻辑 ====================

def run_strategy():
    # 调用 strategy_executor 中的逻辑
    # 我们需要传递 trigger_trade 作为回调函数
    strategy_executor.execute_strategy(state, trigger_trade)

def get_market_probability(token_id):
    """获取指定 Token 的市场最佳卖一价 (Buy Probability)"""
    try:
        global client
        if 'client' not in globals():
            client = ClobClient(
                host=CONFIG["HOST"],
                key=CONFIG["PRIVATE_KEY"],
                chain_id=CONFIG["CHAIN_ID"],
                signature_type=CONFIG["SIGNATURE_TYPE"],
                funder=CONFIG["FUNDER"]
            )
            # 尝试派生 API Key
            try:
                creds = client.derive_api_key()
                client.set_api_creds(creds)
            except: pass

        # 获取 Orderbook
        ob = client.get_order_book(token_id)

        if ob and ob.asks and len(ob.asks) > 0:
            # 找出价格最低的 ask (SDK 返回可能是降序，所以必须手动 min)
            best_ask_obj = min(ob.asks, key=lambda x: float(x.price))
            best_ask = float(best_ask_obj.price)

            # 调试日志
            if best_ask >= 0.90:
                raw_prices = [x.price for x in ob.asks[:5]]
                logger.warning(f"检测到高价 Ask ({best_ask})。Raw Asks(Top5): {raw_prices}")

            return best_ask

        logger.warning(f"Orderbook 无 Asks。Token: {token_id}")
        return 0.99 # 如果没有 Ask，返回高概率以阻止购买 (保守策略)
    except Exception as e:
        logger.error(f"获取概率失败: {e}")
        return 0.99 # 出错时保守返回高概率

def get_market_probability(token_id):
    """获取指定 Token 的市场最佳卖一价 (Buy Probability)"""
    try:
        global client
        if 'client' not in globals():
            client = ClobClient(
                host=CONFIG["HOST"],
                key=CONFIG["PRIVATE_KEY"],
                chain_id=CONFIG["CHAIN_ID"],
                signature_type=CONFIG["SIGNATURE_TYPE"],
                funder=CONFIG["FUNDER"]
            )
            # 尝试派生 API Key
            try:
                creds = client.derive_api_key()
                client.set_api_creds(creds)
            except: pass

        # 获取 Orderbook
        ob = client.get_order_book(token_id)

        if ob and ob.asks and len(ob.asks) > 0:
            # 找出价格最低的 ask (SDK 返回可能是降序，所以必须手动 min)
            best_ask_obj = min(ob.asks, key=lambda x: float(x.price))
            best_ask = float(best_ask_obj.price)

            # 调试日志
            if best_ask >= 0.90:
                raw_prices = [x.price for x in ob.asks[:5]]
                logger.warning(f"检测到高价 Ask ({best_ask})。Raw Asks(Top5): {raw_prices}")

            return best_ask

        logger.warning(f"Orderbook 无 Asks。Token: {token_id}")
        return 0.99 # 如果没有 Ask，返回高概率以阻止购买 (保守策略)
    except Exception as e:
        logger.error(f"获取概率失败: {e}")
        return 0.99 # 出错时保守返回高概率

def trigger_trade(side, reason, price, net, fluc, size_multiplier=1.0):
    logger.warning("!" * 40)
    logger.warning(f"触发信号: {reason} | 方向: {side} | 倍率: {size_multiplier}x")
    logger.warning(f"价格细节: 现价={price:.2f}, 净变={net:.2f}, 波动={fluc:.2f}")
    logger.warning("!" * 40)

    if CONFIG["SIMULATION_MODE"]:
        state.has_traded = True
        logger.info("模拟模式：跳过实际下单。")
        return

    try:
        # 获取 Token ID (动态识别 YES/NO 索引)
        raw_ids = state.active_market.get('clobTokenIds')
        raw_outcomes = state.active_market.get('outcomes')

        if isinstance(raw_ids, str):
            token_ids = json.loads(raw_ids)
        else:
            token_ids = raw_ids

        # 默认顺序: 0=NO, 1=YES (这是大多数 Binary 市场的默认)
        yes_index = 1
        no_index = 0

        # 尝试根据 outcomes 动态解析
        # 例如: ["Up", "Down"] -> Up是YES(0), Down是NO(1)
        if raw_outcomes:
            try:
                if isinstance(raw_outcomes, str):
                    outcomes = json.loads(raw_outcomes)
                else:
                    outcomes = raw_outcomes

                for i, label in enumerate(outcomes):
                    l = label.lower()
                    if l == "yes" or l == "up":
                        yes_index = i
                    elif l == "no" or l == "down":
                        no_index = i
            except Exception as e:
                logger.error(f"解析 outcomes 失败: {e}, 使用默认顺序")

        token_id = token_ids[yes_index] if side == "YES" else token_ids[no_index]

        # --- 概率检查 ---
        prob = get_market_probability(token_id)
        logger.info(f"当前市场概率 (Best Ask): {prob:.4f}")

        if prob >= strategy_executor.STRATEGY_CONFIG["MAX_PROB"]:
            logger.warning(f"概率过高 ({prob:.2f} >= {strategy_executor.STRATEGY_CONFIG['MAX_PROB']}), 放弃下单。")
            state.has_traded = True # 标记已处理，避免重复触发
            return

        logger.info(f"正在向 Polymarket 发送 {side} 订单 (Token: {token_id})...")

        # ------------------------------------------------------------------
        # 下单逻辑
        # ------------------------------------------------------------------
        limit_price = 0.99
        tick_size_str = str(state.active_market.get("tickSize", "0.01"))
        decimals = 2
        if "." in tick_size_str:
            decimals = len(tick_size_str.split(".")[1])

        target_spend = CONFIG["ORDER_AMOUNT"] * size_multiplier
        size_val = target_spend / limit_price
        size_val = round(size_val, decimals)

        order_args = OrderArgs(
            price=limit_price,
            size=size_val,
            side=BUY,
            token_id=token_id,
        )

        # 自动重试不同的 Signature Type
        # 优先尝试 Type 2 (Kernel)，因为日志显示该类型成功率最高
        sig_types_to_try = [2, 1, 0]

        # 如果当前配置的类型不在列表中，也加入尝试
        if CONFIG["SIGNATURE_TYPE"] not in sig_types_to_try:
             sig_types_to_try.insert(0, CONFIG["SIGNATURE_TYPE"])

        last_error = None
        global client

        for sig_type in sig_types_to_try:
            try:
                logger.info(f"尝试下单 (SignatureType={sig_type})...")
                funder_arg = CONFIG["FUNDER"]
                if sig_type == 0:
                    funder_arg = None

                temp_client = ClobClient(
                    host=CONFIG["HOST"],
                    key=CONFIG["PRIVATE_KEY"],
                    chain_id=CONFIG["CHAIN_ID"],
                    signature_type=sig_type,
                    funder=funder_arg
                )

                try:
                    creds = temp_client.derive_api_key()
                    temp_client.set_api_creds(creds)
                except Exception as e:
                    logger.warning(f"API Key 派生异常 (可忽略): {e}")

                signed_order = temp_client.create_order(order_args)
                resp = temp_client.post_order(signed_order)

                logger.info(f"下单成功: {resp}")

                # 记录到文件
                log_order_to_file(
                    state.active_market['id'],
                    reason,
                    side,
                    limit_price,
                    prob,
                    target_spend,
                    state.start_price,
                    price
                )

                client = temp_client
                CONFIG["SIGNATURE_TYPE"] = sig_type
                state.has_traded = True
                return

            except Exception as e:
                logger.warning(f"下单失败 (Type={sig_type}): {e}")
                last_error = e
                continue

        logger.error(f"所有签名类型尝试均失败。最后错误: {last_error}")
        state.has_traded = True # 即使失败也标记，避免无限重试

    except Exception as e:
        logger.error(f"下单流程异常: {e}")
        state.has_traded = True

# ==================== 结算逻辑 ====================

def settle_positions():
    """定期结算盈利 (使用 test_settle.py 的逻辑)"""
    if CONFIG["SIMULATION_MODE"]:
        return

    try:
        # 使用外部模块的 settlement 逻辑
        # 这支持 Proxy Wallet 和 Gnosis Safe 自动执行
        logger.info("执行自动结算 (调用 settle)...")
        settle.settle_positions()
    except Exception as e:
        logger.error(f"External settlement failed: {e}")

# ==================== 主循环 ====================

def main():
    global ws_fail_count
    logger.info("脚本已启动，正在连接coinbase WebSocket...")
    # 等待第一次价格数据
    wait_start = time.time()
    while state.current_price == 0:
        time.sleep(1)
        if time.time() - wait_start > 10:
             logger.warning("等待 WebSocket 价格数据中... (已等待 10s)")
             wait_start = time.time() # 重置提醒计时

    logger.info(f"已获取初始价格: {state.current_price}")

    last_settle_time = time.time()
    last_scan_log_time = 0

    while True:
        # 心跳检查
        if time.time() - state.last_price_update_time > 10:
            logger.warning(f"警告: 超过10秒未收到 WebSocket 价格更新。")
            # 备用价格源 (Binance) - 暂时注释掉
            # logger.warning(f"警告: 超过10秒未收到 WebSocket 价格更新。尝试使用 Binance...")
            # if state.binance:
            #     bp_price = state.binance.get_latest_price()
            #     if bp_price and bp_price > 0:
            #         state.current_price = bp_price
            #         state.last_price_update_time = time.time()
            #         logger.info(f"成功从 Binance 获取价格: {bp_price}")
            #
            #         if state.active_market:
            #             state.price_history.append(state.current_price)
            #             if len(state.price_history) > 1000: state.price_history.pop(0)
            #     else:
            #         logger.error("Binance 获取失败或返回无效价格。")
            # else:
            #      logger.error("Binance 模块未初始化。")

        # 1. 检查/寻找市场
        m = find_btc_market()
        if m:
            # 如果是新市场，初始化状态
            if not state.active_market or m['id'] != state.active_market['id']:
                ws_fail_count = 0 # 发现新市场，重置 WS 重连计数
                state.active_market = m
                state.start_time = get_market_start_time(m['question'])

                # 1. 优先尝试获取 Coinbase 历史开盘价 (API)
                hist_price = get_coinbase_open_price(state.start_time)

                # 2. 如果 API 失败，尝试从本地记录获取
                if not hist_price:
                    logger.warning("Coinbase API 获取失败，尝试查找本地记录...")
                    hist_price = state.recorder.get_price(state.start_time)
                    if hist_price:
                        logger.info(f"✅ 从本地文件命中开盘价: {hist_price}")
                    else:
                        logger.warning("本地无对应时间点的记录。")

                # 3. 备用: Binance (暂时注释掉)
                # if not hist_price:
                #     logger.warning("Coinbase & 本地记录均失败。尝试使用 Binance 历史K线价格...")
                #     if state.binance:
                #         # 使用 Binance 获取历史 K 线开盘价
                #         bp_price = state.binance.get_historical_price(state.start_time)
                #         if bp_price:
                #             hist_price = bp_price
                #             logger.info(f"使用 Binance 历史价格 ({bp_price}) 作为开盘价。")
                #         else:
                #             logger.error("Binance 历史价格获取失败。")
                #     else:
                #         logger.error("Binance 模块未初始化。")

                if not hist_price:
                    logger.error("未能获取开盘价 (Coinbase API & 本地记录均失败)，跳过当前市场监控。")
                    # 重置状态，等待下一次循环重新发现
                    state.active_market = None
                    state.start_time = None
                    time.sleep(5)
                    continue

                # 成功获取
                # 应用 Price Offset (Polymarket 通常比 Coinbase 低)
                offset = CONFIG.get("PRICE_OFFSET", 0.0)
                state.start_price = hist_price - offset

                logger.info(f"使用历史开盘价: {hist_price} (Offset: -{offset}) -> {state.start_price}")

                state.price_history = [state.current_price]
                state.has_traded = False
                state.reversal_count = 0
                state.last_side_sign = 0
                logger.info(f"监控新市场: {m['question']}")
                logger.info(f"设定起始价: {state.start_price}")
        else:
            if time.time() - last_scan_log_time > 10:
                logger.info("正在扫描符合条件的 BTC 市场...")
                last_scan_log_time = time.time()

        # 2. 执行策略
        run_strategy()

        # 3. 市场结算清理
        if state.active_market:
            # 同样使用 UTC 计算
            now_utc = datetime.now(timezone.utc)
            start_time = state.start_time
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)

            elapsed = (now_utc - start_time).total_seconds()
            if elapsed > 310: # 5分钟市场结束
                logger.info("当前市场监控结束，准备寻找下一个...")
                state.active_market = None
                ws_fail_count = 0 # 重置 WS 重连计数，开始新周期

        # 4. 定期结算
        if time.time() - last_settle_time > CONFIG["SETTLE_INTERVAL"]:
            settle_positions()
            last_settle_time = time.time()

        time.sleep(0.5)

if __name__ == "__main__":
    main()
