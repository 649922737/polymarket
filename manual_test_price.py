import time
import requests
import logging
from datetime import datetime, timedelta, timezone

# 配置日志以显示详细信息
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("TestBot")

def get_coinbase_open_price(dt):
    """获取指定时间点 (UTC) 的 Coinbase BTC-USD 开盘价 (带重试机制)"""
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
            logger.info(f"正在请求 Coinbase API... (尝试 {attempt+1}/{max_retries})")
            resp = requests.get(url, params=params, headers=headers, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    candle = data[0]
                    # Candle 格式: [time, low, high, open, close, volume]
                    open_price = float(candle[3])
                    logger.info(f"获取历史价格成功 ({dt}): {open_price}")
                    return open_price
                else:
                    logger.warning(f"Coinbase 返回数据为空 (可能时间点太新，K线未生成)")
            else:
                logger.warning(f"Coinbase API Error: {resp.status_code} {resp.text}")

        except Exception as e:
            logger.warning(f"请求异常: {e}")

        # 失败后等待
        if attempt < max_retries - 1:
            time.sleep(2)

    logger.error("多次尝试获取失败。")
    return None

if __name__ == "__main__":
    # 1. 指定测试时间点
    # 用户遇到的问题时间: 2026-02-16 16:05:00 UTC
    dt_target = datetime(2026, 2, 16, 17, 00, 0, tzinfo=timezone.utc)

    print(f"--- 测试时间点: {dt_target} ---")
    price = get_coinbase_open_price(dt_target)

    if not price:
        print("⚠️ Coinbase 获取失败，尝试 Binance...")
        # 简单的 Binance 测试逻辑
        url = "https://api.binance.com/api/v3/klines"
        ts = int(dt_target.timestamp() * 1000)
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
                if isinstance(data, list) and len(data) > 0:
                    candle = data[0]
                    price = float(candle[1])
                    print(f"✅ Binance 获取成功: {price}")
        except Exception as e:
            print(f"❌ Binance 获取也失败: {e}")

    if price:
        print(f"✅ 成功获取价格: {price}")
    else:
        print("❌ 获取价格失败")
