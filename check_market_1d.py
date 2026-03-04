import requests
from datetime import datetime

def get_binance_klines(symbol="BTCUSDT", interval="1d", limit=300):
    base_url = "https://api.binance.com"
    endpoint = "/api/v3/klines"

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    try:
        response = requests.get(base_url + endpoint, params=params)
        data = response.json()

        if not isinstance(data, list):
            print(f"Error format: {data}")
            return None

        # Format: [Open Time, Open, High, Low, Close, Volume, ...]
        # We need Close price (index 4)
        prices = [float(x[4]) for x in data]
        return prices

    except Exception as e:
        print(f"Error fetching data for {interval}: {e}")
        return None

def calculate_ema(prices, period):
    if not prices or len(prices) < period:
        return None

    # Initial SMA
    ema = sum(prices[:period]) / period
    multiplier = 2 / (period + 1)

    # Calculate EMA
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema

    return ema

def analyze_1d_environment():
    print(f"--- 1D Market Environment Analysis ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ---")

    # Fetch 1D data
    print("Fetching 1D data...")
    prices_1d = get_binance_klines(interval="1d", limit=300)

    if prices_1d:
        current_price = prices_1d[-1]
        ema_21 = calculate_ema(prices_1d, 21)
        ema_200 = calculate_ema(prices_1d, 200)

        print(f"Current Price (1D Close/Latest): {current_price:.2f}")

        if ema_21:
            print(f"1D EMA 21 (Short-term Trend): {ema_21:.2f}")
            if current_price > ema_21:
                print("-> Price is ABOVE EMA 21 (Short-term Bullish)")
            else:
                print("-> Price is BELOW EMA 21 (Short-term Bearish)")

        if ema_200:
            print(f"1D EMA 200 (Long-term Trend): {ema_200:.2f}")
            if current_price > ema_200:
                print("-> Price is ABOVE EMA 200 (Long-term Bullish/Bull Market)")
            else:
                print("-> Price is BELOW EMA 200 (Long-term Bearish/Bear Market)")

        print("\n--- CONCLUSION ---")
        if current_price > ema_21 and current_price > ema_200:
            print("✅ 1D View: STRONGLY BULLISH (强势看多)")
        elif current_price < ema_21 and current_price < ema_200:
            print("🔻 1D View: STRONGLY BEARISH (强势看空)")
        elif current_price > ema_200 and current_price < ema_21:
            print("⚠️ 1D View: BULLISH CORRECTION (多头回调)")
            print("长期看多 (Above EMA 200)，但短期日线回调 (Below EMA 21)")
        elif current_price < ema_200 and current_price > ema_21:
            print("⚠️ 1D View: BEARISH REBOUND (空头反弹)")
            print("长期看空 (Below EMA 200)，但短期日线反弹 (Above EMA 21)")

    else:
        print("Failed to get 1D data")

if __name__ == "__main__":
    analyze_1d_environment()
