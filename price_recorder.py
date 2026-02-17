import os
import json
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("PriceRecorder")

class PriceRecorder:
    def __init__(self, data_dir="price_data"):
        self.data_dir = data_dir
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

        # 自动清理旧文件 (保留最近 2 天)
        self._cleanup_old_files(days_to_keep=2)

        # 内存缓存，减少文件读取
        self.cache = {}
        self.current_date_str = None

    def _cleanup_old_files(self, days_to_keep=2):
        """删除超过指定天数的旧文件"""
        try:
            now = datetime.now(timezone.utc)
            cutoff_date = now - timedelta(days=days_to_keep)

            for filename in os.listdir(self.data_dir):
                if not filename.startswith("prices_") or not filename.endswith(".json"):
                    continue

                # 解析日期: prices_2026-02-16.json
                try:
                    date_part = filename.replace("prices_", "").replace(".json", "")
                    file_date = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=timezone.utc)

                    if file_date.date() < cutoff_date.date():
                        file_path = os.path.join(self.data_dir, filename)
                        os.remove(file_path)
                        logger.info(f"已删除旧价格文件: {filename}")
                except Exception as e:
                    logger.warning(f"解析/删除文件 {filename} 失败: {e}")

        except Exception as e:
            logger.error(f"清理旧文件失败: {e}")

    def _get_file_path(self, dt):
        """根据日期获取文件路径 (按天分文件)"""
        # 确保是 UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        date_str = dt.strftime("%Y-%m-%d")
        return os.path.join(self.data_dir, f"prices_{date_str}.json"), date_str

    def _load_cache(self, dt):
        """加载指定日期的文件到内存"""
        file_path, date_str = self._get_file_path(dt)

        # 如果已经加载了该日期，直接返回
        if self.current_date_str == date_str and self.cache:
            return

        self.current_date_str = date_str
        self.cache = {}

        if os.path.exists(file_path):
            try:
                with open(file_path, 'r') as f:
                    self.cache = json.load(f)
            except Exception as e:
                logger.error(f"加载价格文件失败: {e}")

    def record_price(self, dt, price):
        """记录指定时间点的价格"""
        if not price or price <= 0:
            return

        # 确保是 UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        # 归一化到分钟 (00秒)
        # 实际上我们记录的是“当时”的价格，可以作为那一分钟的 Open Price
        key = dt.strftime("%H:%M:00") # Key 只存时间，日期在文件名里

        # 加载/刷新缓存
        self._load_cache(dt)

        # 如果已经有了，就不覆盖？或者覆盖？
        # 通常我们希望记录最接近整点的第一个价格，所以如果有了就不覆盖
        if key not in self.cache:
            self.cache[key] = float(price)
            logger.info(f"💾 本地记录价格: {dt.strftime('%Y-%m-%d %H:%M:%S')} -> {price}")
            self._save_file(dt)

    def _save_file(self, dt):
        """保存内存缓存到文件"""
        file_path, _ = self._get_file_path(dt)
        try:
            with open(file_path, 'w') as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            logger.error(f"保存价格文件失败: {e}")

    def get_price(self, dt):
        """获取指定时间点的价格"""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        key = dt.strftime("%H:%M:00")

        # 重新加载缓存以防跨天或未加载
        self._load_cache(dt)

        price = self.cache.get(key)
        if price:
            return float(price)
        return None

# 测试
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pr = PriceRecorder()

    now = datetime.now(timezone.utc)
    pr.record_price(now, 50000.0)

    p = pr.get_price(now)
    print(f"Read back: {p}")
