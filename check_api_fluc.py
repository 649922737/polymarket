import requests
from datetime import datetime, timezone, timedelta

# Target: 2026-03-01 11:45:00 UTC
target_time = datetime(2026, 3, 1, 11, 45, 0, tzinfo=timezone.utc)
start_str = target_time.isoformat()
end_str = (target_time + timedelta(minutes=5)).isoformat() # 5m candle

url = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
params = {'start': start_str, 'end': end_str, 'granularity': 300} # 5m
headers = {"User-Agent": "Mozilla/5.0"}

print(f"Fetching from Coinbase: {start_str} to {end_str}")
resp = requests.get(url, params=params, headers=headers)

if resp.status_code == 200:
    data = resp.json()
    if data:
        candle = data[0] # [time, low, high, open, close, volume]
        high = float(candle[2])
        low = float(candle[1])
        fluc = high - low
        print(f"Candle: {candle}")
        print(f"Fluctuation (High-Low): {fluc:.2f}")
    else:
        print("No data returned")
else:
    print(f"Error: {resp.status_code} {resp.text}")
