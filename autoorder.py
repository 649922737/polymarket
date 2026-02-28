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
    "COINBASE_WS": "wss://ws-feed.exchange.coinbase.com",
    "BINANCE_WS": "wss://stream.binance.com:9443/ws/btcusdt@trade",
    "ORDER_AMOUNT": float(os.getenv("POLY_ORDER_AMOUNT", 3.0)),
    "ORDER_AMOUNT_15M": float(os.getenv("POLY_ORDER_AMOUNT_15M", 2.0)),
    "SIMULATION_MODE": False,
    "PRICE_OFFSET": float(os.getenv("POLY_PRICE_OFFSET", 0.0)),
    "SETTLE_INTERVAL": int(os.getenv("POLY_SETTLE_INTERVAL", 600)),
}

CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

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
except Exception as e:
    logger.error(f"账户检查失败: {e}")

# ==================== 全局状态类 ====================
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
        self.last_side_sign = 0
        self.last_recorded_minute = -1
        self.market_type = "5m" # Default

        # 初始化 PriceRecorder
        self.recorder = PriceRecorder()

        # 初始化 Binance
        try:
            self.binance = BinancePrice()
        except:
            self.binance = None

# ==================== 核心功能函数 ====================

def get_market_start_time(question):
    """解析市场标题以获取起始时间"""
    try:
        if "Up or Down" in question:
            try:
                time_part = question.split(' - ')[-1].strip()
                if "AM-" not in time_part and "PM-" not in time_part:
                     if "ET" in time_part:
                         date_str = time_part.split(',')[0].strip()
                         time_str = time_part.split(',')[1].replace('ET', '').strip()
                         full_str = f"{date_str} {datetime.now().year} {time_str}"
                         for fmt in ['%B %d %Y %I%p', '%B %d %Y %I:%M%p']:
                             try:
                                 dt = datetime.strptime(full_str, fmt)
                                 dt_utc = dt.replace(tzinfo=timezone(timedelta(hours=-5))).astimezone(timezone.utc)
                                 return dt_utc
                             except:
                                 continue

                date_str = time_part.split(',')[0].strip()
                time_range = time_part.split(',')[1].strip()
                start_time_str = time_range.split('-')[0].strip()

                full_str = f"{date_str} {datetime.now().year} {start_time_str}"
                dt_et = datetime.strptime(full_str, '%B %d %Y %I:%M%p')
                dt_utc = dt_et.replace(tzinfo=timezone(timedelta(hours=-5))).astimezone(timezone.utc)
                # logger.info(f"解析时间: {full_str} -> {dt_et} (ET) -> {dt_utc} (UTC)")
                return dt_utc
            except ValueError:
                pass

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

def get_coinbase_open_price(dt):
    """获取指定时间点 (UTC) 的 Coinbase BTC-USD 开盘价"""
    if not dt: return None
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    else: dt = dt.astimezone(timezone.utc)

    start_str = dt.isoformat()
    end_str = (dt + timedelta(minutes=1)).isoformat()

    url = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
    params = {'start': start_str, 'end': end_str, 'granularity': 60}
    headers = {"User-Agent": "Mozilla/5.0"}

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    open_price = float(data[0][3])
                    logger.info(f"获取历史价格成功 ({dt}): {open_price}")
                    return open_price
                else:
                    logger.warning(f"Coinbase 返回数据为空 (尝试 {attempt+1})")
            else:
                logger.warning(f"Coinbase API Error: {resp.status_code} (尝试 {attempt+1})")
        except Exception as e:
            logger.warning(f"获取 Coinbase 历史价格异常: {e}")
        if attempt < max_retries - 1: time.sleep(2)
    return None

def log_order_to_file(market_id, condition, side, price, poly_price, amount, start_price, trigger_price, market_type="5m"):
    try:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        suffix = "_15m" if market_type == "15m" else ""
        filename = f"trade_history{suffix}_{date_str}.csv"
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

        file_exists = os.path.isfile(filename)
        with open(filename, "a") as f:
            if not file_exists:
                f.write("timestamp,market_id,condition,side,limit_price,poly_price,amount,start_price,trigger_price\n")
            line = f"{timestamp},{market_id},{condition},{side},{price},{poly_price},{amount},{start_price},{trigger_price}\n"
            f.write(line)
    except Exception as e:
        logger.error(f"写入日志失败: {e}")

# ==================== Bot Runner Class ====================

class BotRunner(threading.Thread):
    def __init__(self, market_type="5m"):
        super().__init__()
        self.market_type = market_type
        self.name = f"BotRunner-{market_type}"
        self.interval_sec = 300 if market_type == "5m" else 900
        self.state = MarketState()
        self.state.market_type = market_type
        self.daemon = True
        self.client = None

        subdir = None if market_type == "5m" else "15m"
        self.strategies = strategy_executor.load_strategies(subdir)
        logger.info(f"[{self.name}] Initialized with {len(self.strategies)} strategies (dir: {subdir or 'root'})")

        self.last_scan_log_time = 0
        self.last_settle_time = time.time()

    def update_price(self, price):
        self.state.current_price = price
        self.state.last_price_update_time = time.time()

        # 仅 5m runner 负责记录 raw price，避免冲突
        if self.market_type == "5m":
            now_utc = datetime.now(timezone.utc)
            if now_utc.minute % 5 == 0 and now_utc.second < 15:
                minute_key = now_utc.strftime("%Y%m%d%H%M")
                if self.state.last_recorded_minute != minute_key:
                    self.state.recorder.record_price(now_utc, price)
                    self.state.last_recorded_minute = minute_key

        if self.state.active_market:
            self.state.price_history.append(self.state.current_price)
            if len(self.state.price_history) > 1000: self.state.price_history.pop(0)

    def find_market(self):
        try:
            # 1. Check current
            if self.state.active_market:
                now_utc = datetime.now(timezone.utc)
                start_time = self.state.start_time
                if start_time and start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=timezone.utc)

                if start_time:
                    elapsed = (now_utc - start_time).total_seconds()
                    # Allow 10s buffer
                    if elapsed < self.interval_sec + 10:
                        return self.state.active_market
                    else:
                        logger.info(f"[{self.name}] Market expired (Elapsed={elapsed:.1f}s).")

            # 2. Find new
            now_utc = datetime.now(timezone.utc)
            ts = int(now_utc.timestamp())
            current_window_start = ts - (ts % self.interval_sec)

            elapsed = ts - current_window_start
            target_ts = current_window_start
            if elapsed > (self.interval_sec - 10):
                target_ts += self.interval_sec

            slug_type = self.market_type
            # 尝试 Current 和 Next
            for search_ts in [target_ts, target_ts + self.interval_sec]:
                slug = f"btc-updown-{slug_type}-{search_ts}"
                url = f"{CONFIG['GAMMA_API']}/markets?slug={slug}"

                try:
                    resp = requests.get(url, timeout=5)
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        m = data[0]
                        if m.get('active') and not m.get('closed'):
                            return m
                except:
                    pass
        except Exception as e:
            logger.error(f"[{self.name}] Find market failed: {e}")
        return None

    def get_market_probability(self, token_id):
        try:
            if not self.client:
                self.client = ClobClient(
                    host=CONFIG["HOST"],
                    key=CONFIG["PRIVATE_KEY"],
                    chain_id=CONFIG["CHAIN_ID"],
                    signature_type=CONFIG["SIGNATURE_TYPE"],
                    funder=CONFIG["FUNDER"]
                )
                try:
                    creds = self.client.derive_api_key()
                    self.client.set_api_creds(creds)
                except: pass

            ob = self.client.get_order_book(token_id)
            if ob and ob.asks and len(ob.asks) > 0:
                best_ask_obj = min(ob.asks, key=lambda x: float(x.price))
                return float(best_ask_obj.price)
            return 0.99
        except Exception as e:
            logger.error(f"[{self.name}] Get prob failed: {e}")
            return 0.99

    def trigger_trade(self, side, reason, price, net, fluc, size_multiplier=1.0):
        logger.warning(f"[{self.name}] 触发: {reason} | {side} | {size_multiplier}x")

        # 记录 15m 策略的所有触发信号 (无论成功与否)
        if self.market_type == "15m":
            try:
                log_file = "trigger_history_15m.csv"
                file_exists = os.path.isfile(log_file)
                with open(log_file, "a") as f:
                    if not file_exists:
                        f.write("Time,MarketID,Side,BTC_Price,Net,Fluc,Reason,Multiplier\n")

                    mid = self.state.active_market['id'] if self.state.active_market else "Unknown"
                    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    f.write(f"{now_str},{mid},{side},{price},{net},{fluc},{reason},{size_multiplier}\n")
            except Exception as ex:
                logger.error(f"[{self.name}] 记录触发日志失败: {ex}")

        if CONFIG["SIMULATION_MODE"]:
            self.state.has_traded = True
            logger.info("模拟模式：跳过实际下单。")
            return

        try:
            raw_ids = self.state.active_market.get('clobTokenIds')
            raw_outcomes = self.state.active_market.get('outcomes')

            if isinstance(raw_ids, str): token_ids = json.loads(raw_ids)
            else: token_ids = raw_ids

            yes_index = 1
            no_index = 0
            if raw_outcomes:
                try:
                    outcomes = json.loads(raw_outcomes) if isinstance(raw_outcomes, str) else raw_outcomes
                    for i, label in enumerate(outcomes):
                        l = label.lower()
                        if l == "yes" or l == "up": yes_index = i
                        elif l == "no" or l == "down": no_index = i
                except: pass

            token_id = token_ids[yes_index] if side == "YES" else token_ids[no_index]

            prob = self.get_market_probability(token_id)
            logger.info(f"[{self.name}] Prob: {prob:.4f}")

            if prob >= strategy_executor.STRATEGY_CONFIG["MAX_PROB"]:
                logger.warning(f"概率过高 ({prob:.2f}), 放弃。")
                self.state.has_traded = True
                return

            limit_price = 0.99
            tick_size_str = str(self.state.active_market.get("tickSize", "0.01"))
            decimals = len(tick_size_str.split(".")[1]) if "." in tick_size_str else 2

            safe_prob = prob if prob > 0.01 else 0.01

            # 根据市场类型选择基础下单金额
            base_amount = CONFIG["ORDER_AMOUNT_15M"] if self.market_type == "15m" else CONFIG["ORDER_AMOUNT"]
            target_amount = base_amount * size_multiplier

            size_val = round(target_amount / safe_prob, decimals)

            order_args = OrderArgs(price=limit_price, size=size_val, side=BUY, token_id=token_id)

            sig_types = [2, 1, 0]
            if CONFIG["SIGNATURE_TYPE"] not in sig_types: sig_types.insert(0, CONFIG["SIGNATURE_TYPE"])

            last_error = None
            for sig_type in sig_types:
                max_retries = 3
                current_error = None
                for attempt in range(max_retries):
                    try:
                        logger.info(f"[{self.name}] 下单 (Sig={sig_type}, Att={attempt+1})...")
                        funder = CONFIG["FUNDER"] if sig_type != 0 else None
                        temp_client = ClobClient(
                            host=CONFIG["HOST"], key=CONFIG["PRIVATE_KEY"], chain_id=CONFIG["CHAIN_ID"],
                            signature_type=sig_type, funder=funder
                        )
                        try:
                            creds = temp_client.derive_api_key()
                            temp_client.set_api_creds(creds)
                        except: pass

                        signed = temp_client.create_order(order_args)
                        resp = temp_client.post_order(signed)
                        logger.info(f"[{self.name}] 下单成功: {resp}")

                        log_order_to_file(
                            self.state.active_market['id'], reason, side, limit_price, prob,
                            target_amount, self.state.start_price, price, self.market_type
                        )

                        self.client = temp_client
                        CONFIG["SIGNATURE_TYPE"] = sig_type
                        self.state.has_traded = True
                        return

                    except Exception as e:
                        current_error = e
                        err_str = str(e).lower()
                        is_retry = False
                        delay = 1.0

                        if "425" in err_str or "service not ready" in err_str:
                            is_retry = True
                        elif "429" in err_str:
                            is_retry = True; delay = 2.0
                        elif "400" in err_str or "bad request" in err_str:
                            is_retry = True

                        if is_retry and attempt < max_retries - 1:
                            logger.warning(f"[{self.name}] 下单错误 ({err_str})，重试...")
                            time.sleep(delay)
                            continue

                        logger.warning(f"[{self.name}] 下单失败: {e}")
                        break

                if current_error: last_error = current_error

            logger.error(f"[{self.name}] 所有尝试失败: {last_error}")
            self.state.has_traded = True

        except Exception as e:
            logger.error(f"[{self.name}] 下单异常: {e}")
            self.state.has_traded = True

    def run(self):
        logger.info(f"{self.name} started.")
        while True:
            # 1. 寻找市场
            m = self.find_market()
            if m:
                if not self.state.active_market or m['id'] != self.state.active_market['id']:
                    self.state.active_market = m
                    self.state.start_time = get_market_start_time(m['question'])

                    hist_price = get_coinbase_open_price(self.state.start_time)
                    if not hist_price:
                        # 尝试从本地记录读取 (5m bot 负责写入，15m bot 也可以读取)
                        hist_price = self.state.recorder.get_price(self.state.start_time)

                    if not hist_price:
                        logger.error(f"[{self.name}] 未能获取开盘价，跳过。")
                        self.state.active_market = None
                        self.state.start_time = None
                        time.sleep(5)
                        continue

                    offset = CONFIG.get("PRICE_OFFSET", 0.0)
                    self.state.start_price = hist_price - offset
                    self.state.price_history = [self.state.current_price]
                    self.state.has_traded = False
                    self.state.reversal_count = 0
                    self.state.last_side_sign = 0
                    logger.info(f"[{self.name}] 新市场: {m['question']} (Start: {self.state.start_price})")
            else:
                if time.time() - self.last_scan_log_time > 30:
                    logger.info(f"[{self.name}] Scanning...")
                    self.last_scan_log_time = time.time()

            # 2. 执行策略
            strategy_executor.execute_strategy(self.state, self.strategies, self.trigger_trade)

            # 3. 清理过期
            if self.state.active_market:
                now_utc = datetime.now(timezone.utc)
                start_time = self.state.start_time
                if start_time and start_time.tzinfo is None: start_time = start_time.replace(tzinfo=timezone.utc)

                if start_time:
                    elapsed = (now_utc - start_time).total_seconds()
                    if elapsed > self.interval_sec + 10:
                        logger.info(f"[{self.name}] 市场结束。")
                        self.state.active_market = None

            # 4. 结算 (Global logic, just call from one runner or separate?)
            # Let's run settlement only on 5m runner to avoid race
            if self.market_type == "5m":
                if time.time() - self.last_settle_time > CONFIG["SETTLE_INTERVAL"]:
                    try:
                        logger.info("执行自动结算...")
                        settle.settle_positions()
                    except Exception as e:
                        logger.error(f"Settlement failed: {e}")
                    self.last_settle_time = time.time()

            time.sleep(0.5)

# ==================== WS & Main ====================

runners = []

def on_message(ws, message):
    try:
        data = json.loads(message)
        if data.get('type') == 'ticker' and 'price' in data:
            price = float(data['price'])
            for r in runners:
                r.update_price(price)
    except Exception as e:
        logger.error(f"WS Msg Error: {e}")

ws_fail_count = 0
def on_open(ws):
    global ws_fail_count
    logger.info("WS Connected.")
    ws_fail_count = 0
    ws.send(json.dumps({"type": "subscribe", "product_ids": ["BTC-USD"], "channels": ["ticker"]}))

def start_ws():
    global ws_fail_count
    while True:
        try:
            logger.info(f"Connecting WS: {CONFIG['COINBASE_WS']}")
            ws = websocket.WebSocketApp(
                CONFIG['COINBASE_WS'],
                on_message=on_message,
                on_open=on_open,
                on_error=lambda ws, e: logger.error(f"WS Error: {e}"),
                on_close=lambda *args: logger.warning("WS Closed")
            )
            ws.run_forever(ping_interval=30, ping_timeout=10)
            ws_fail_count += 1
        except Exception as e:
            logger.error(f"WS Exception: {e}")
            ws_fail_count += 1

        sleep_time = min(20, 5 * (ws_fail_count if ws_fail_count <=3 else 4))
        time.sleep(sleep_time)

def main():
    # 启动 WS
    threading.Thread(target=start_ws, daemon=True).start()

    # 启动 Runners
    logger.info("Starting Bot Runners...")
    runner_5m = BotRunner("5m")
    runner_15m = BotRunner("15m")

    runners.append(runner_5m)
    runners.append(runner_15m)

    for r in runners:
        r.start()

    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
