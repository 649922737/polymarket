import requests
from datetime import datetime

def get_binance_klines(symbol="BTCUSDT", interval="1h", limit=300):
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

def analyze_market_environment():
    print(f"--- Market Environment Analysis ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ---")

    # 1. Fetch 1H data for EMA 200
    print("Fetching 1H data...")
    prices_1h = get_binance_klines(interval="1h", limit=300)

    if prices_1h:
        current_price_1h = prices_1h[-1]
        ema_200_1h = calculate_ema(prices_1h, 200)

        if ema_200_1h:
            print(f"1H Price: {current_price_1h:.2f}")
            print(f"1H EMA 200: {ema_200_1h:.2f}")

            if current_price_1h > ema_200_1h:
                status_1h = "BULLISH"
                print("1H Status: BULLISH (Above EMA 200)")
            else:
                status_1h = "BEARISH"
                print("1H Status: BEARISH (Below EMA 200)")
        else:
            print("Not enough data for 1H EMA 200")
            return
    else:
        print("Failed to get 1H data")
        return

    # 2. Fetch 15m data for EMA 21
    print("\nFetching 15m data...")
    prices_15m = get_binance_klines(interval="15m", limit=100)

    if prices_15m:
        current_price_15m = prices_15m[-1]
        ema_21_15m = calculate_ema(prices_15m, 21)

        if ema_21_15m:
            print(f"15m Price: {current_price_15m:.2f}")
            print(f"15m EMA 21: {ema_21_15m:.2f}")

            if current_price_15m > ema_21_15m:
                status_15m = "BULLISH"
                print("15m Status: BULLISH (Above EMA 21)")
            else:
                status_15m = "BEARISH"
                print("15m Status: BEARISH (Below EMA 21)")
        else:
            print("Not enough data for 15m EMA 21")
            return
    else:
        print("Failed to get 15m data")
        return

    # 3. Conclusion
    print("\n--- CONCLUSION ---")

    if status_1h == "BULLISH" and status_15m == "BULLISH":
        print("✅ CURRENT ENVIRONMENT: LONG (看多)")
        print("Reason: Both 1H (Above EMA 200) and 15m (Above EMA 21) are Bullish.")
    elif status_1h == "BEARISH" and status_15m == "BEARISH":
        print("🔻 CURRENT ENVIRONMENT: SHORT (看空)")
        print("Reason: Both 1H (Below EMA 200) and 15m (Below EMA 21) are Bearish.")
    else:
        print("⚠️ CURRENT ENVIRONMENT: NEUTRAL / MIXED (震荡/中性)")
        print("Reason: Conflict between 1H and 15m signals.")
        print(f"- 1H Trend: {status_1h}")
        print(f"- 15m Trend: {status_15m}")

if __name__ == "__main__":
    analyze_market_environment()
