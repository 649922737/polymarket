import os
import json
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("MarketRecorder")

class MarketRecorder:
    def __init__(self, data_dir="market_data"):
        self.data_dir = data_dir
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

        # 暂时禁用自动清理，保留旧文件
        # self._cleanup_old_files(days_to_keep=2)

    def _cleanup_old_files(self, days_to_keep=2):
        """删除超过指定天数的旧文件"""
        try:
            now = datetime.now(timezone.utc)
            cutoff_date = now - timedelta(days=days_to_keep)

            for filename in os.listdir(self.data_dir):
                if not filename.endswith(".json"):
                    continue

                # 支持 fluctuations_ 和 net_changes_ 前缀
                if filename.startswith("fluctuations_"):
                    prefix = "fluctuations_"
                elif filename.startswith("net_changes_"):
                    prefix = "net_changes_"
                else:
                    continue

                try:
                    date_part = filename.replace(prefix, "").replace(".json", "")
                    file_date = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=timezone.utc)

                    if file_date.date() < cutoff_date.date():
                        file_path = os.path.join(self.data_dir, filename)
                        os.remove(file_path)
                        logger.info(f"已删除旧文件: {filename}")
                except Exception as e:
                    logger.warning(f"解析/删除文件 {filename} 失败: {e}")

        except Exception as e:
            logger.error(f"清理旧文件失败: {e}")

    def _get_file_path(self, dt, type_prefix="fluctuations_"):
        """根据日期获取文件路径 (按天分文件)"""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        date_str = dt.strftime("%Y-%m-%d")
        return os.path.join(self.data_dir, f"{type_prefix}{date_str}.json")

    def _record_value(self, cycle_start_time, value, type_prefix):
        """通用记录方法"""
        if value is None:
            return

        if cycle_start_time.tzinfo is None:
            cycle_start_time = cycle_start_time.replace(tzinfo=timezone.utc)
        else:
            cycle_start_time = cycle_start_time.astimezone(timezone.utc)

        file_path = self._get_file_path(cycle_start_time, type_prefix)

        # 记录使用的是周期开始时间 HH:MM:SS
        key = cycle_start_time.strftime("%H:%M:%S")

        try:
            data = {}
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    try:
                        data = json.load(f)
                    except json.JSONDecodeError:
                        data = {}

            # 只有当不存在或者值不同的时候才写入
            if key not in data or data[key] != float(value):
                data[key] = float(value)

                # 按时间排序 (key是 HH:MM:SS字符串，可以直接排序)
                sorted_data = dict(sorted(data.items()))

                with open(file_path, 'w') as f:
                    json.dump(sorted_data, f, indent=2)
                logger.debug(f"已记录 {type_prefix}: {key} -> {value}")

        except Exception as e:
            logger.error(f"记录 {type_prefix} 失败: {e}")

    def _get_value(self, cycle_start_time, type_prefix):
        """通用读取方法"""
        if cycle_start_time.tzinfo is None:
            cycle_start_time = cycle_start_time.replace(tzinfo=timezone.utc)
        else:
            cycle_start_time = cycle_start_time.astimezone(timezone.utc)

        file_path = self._get_file_path(cycle_start_time, type_prefix)
        key = cycle_start_time.strftime("%H:%M:%S")

        if not os.path.exists(file_path):
            return None

        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                return data.get(key)
        except Exception as e:
            logger.error(f"读取 {type_prefix} 失败: {e}")
            return None

    def record_fluctuation(self, cycle_start_time, fluctuation_value):
        self._record_value(cycle_start_time, fluctuation_value, "fluctuations_")

    def get_fluctuation(self, cycle_start_time):
        return self._get_value(cycle_start_time, "fluctuations_")

    def record_net_change(self, cycle_start_time, net_change_value):
        self._record_value(cycle_start_time, net_change_value, "net_changes_")

    def get_net_change(self, cycle_start_time):
        return self._get_value(cycle_start_time, "net_changes_")

# Alias for backward compatibility if needed, but we will update usages
FluctuationRecorder = MarketRecorder
