import requests
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger("Binance")

class BinancePrice:
    def __init__(self):
        self.base_url = "https://api.binance.com"
        self.symbol = "BTCUSDT"

    def get_historical_price(self, dt):
        """获取指定时间点 (UTC) 的 Binance K 线开盘价及波动"""
        if not dt: return None, 0

        # 确保时间是 UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        # Binance API 需要毫秒时间戳
        ts = int(dt.timestamp() * 1000)

        url = f"{self.base_url}/api/v3/klines"
        params = {
            'symbol': self.symbol,
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
                    # 检查时间戳误差 (60s 内)
                    candle_ts = candle[0]
                    if abs(candle_ts - ts) < 60000:
                        open_price = float(candle[1])
                        high_price = float(candle[2])
                        low_price = float(candle[3])
                        fluctuation = high_price - low_price

                        logger.info(f"Binance 历史数据 ({dt}): Open={open_price}, Fluc={fluctuation}")
                        return open_price, fluctuation
                    else:
                        logger.warning(f"Binance 返回时间不匹配: Req={ts}, Res={candle_ts}")
                else:
                    logger.warning(f"Binance 返回空数据 ({dt})")
            else:
                logger.warning(f"Binance API Error: {resp.status_code} {resp.text}")

        except Exception as e:
            logger.error(f"Binance 请求异常: {e}")

        return None, 0

    def get_latest_price(self):
        """获取当前最新价格"""
        url = f"{self.base_url}/api/v3/ticker/price"
        params = {'symbol': self.symbol}

        try:
            resp = requests.get(url, params=params, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                price = float(data['price'])
                return price
            else:
                logger.warning(f"Binance Ticker Error: {resp.status_code}")
        except Exception as e:
            logger.error(f"Binance Ticker Exception: {e}")

        return None

if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)
    bp = BinancePrice()

    # 1. 测试最新价
    print(f"最新价: {bp.get_latest_price()}")

    # 2. 测试 5 分钟前的历史价
    now = datetime.now(timezone.utc)
    ts = int(now.timestamp())
    last_5m = ts - (ts % 300)
    dt_5m = datetime.fromtimestamp(last_5m, tz=timezone.utc)

    print(f"历史开盘价 ({dt_5m}): {bp.get_historical_price(dt_5m)}")
