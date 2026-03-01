import os
import json
from datetime import datetime, timezone, timedelta
from fluctuation_recorder import FluctuationRecorder

# 模拟 UTC 时间 03:50:00 (对应日志 11:50 UTC+8)
# 这时候 Prev Cycle 应该是 03:45:00

target_time_str = "2026-03-01 03:45:00"
target_time = datetime.strptime(target_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

recorder = FluctuationRecorder(file_suffix="")

print(f"Checking fluctuation for {target_time} (UTC)...")
val = recorder.get_fluctuation(target_time)

print(f"Value read from recorder: {val}")

# 同时也读取一下文件内容确认
file_path = recorder._get_file_path(target_time)
print(f"File path: {file_path}")

if os.path.exists(file_path):
    with open(file_path, 'r') as f:
        data = json.load(f)
        key = target_time.strftime("%H:%M:%S")
        print(f"Raw value in file for key '{key}': {data.get(key)}")
else:
    print("File does not exist!")
