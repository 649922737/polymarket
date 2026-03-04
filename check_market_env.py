import requests
import pandas as pd
import numpy as np
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

        # Binance kline format:
        # [Open Time, Open, High, Low, Close, Volume, Close Time, ...]
        df = pd.DataFrame(data, columns=[
            "Open Time", "Open", "High", "Low", "Close", "Volume",
            "Close Time", "Quote Asset Volume", "Number of Trades",
            "Taker Buy Base Asset Volume", "Taker Buy Quote Asset Volume", "Ignore"
        ])

        df["Close"] = pd.to_numeric(df["Close"])
        df["Open Time"] = pd.to_datetime(df["Open Time"], unit='ms')

        return df
    except Exception as e:
        print(f"Error fetching data for {interval}: {e}")
        return None

def calculate_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def analyze_market_environment():
    print(f"--- Market Environment Analysis ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ---")

    # 1. Fetch 1H data for EMA 200
    print("Fetching 1H data...")
    df_1h = get_binance_klines(interval="1h", limit=300)

    if df_1h is not None:
        df_1h["EMA_200"] = calculate_ema(df_1h["Close"], 200)
        current_price_1h = df_1h["Close"].iloc[-1]
        ema_200_1h = df_1h["EMA_200"].iloc[-1]

        print(f"1H Price: {current_price_1h:.2f}")
        print(f"1H EMA 200: {ema_200_1h:.2f}")

        if current_price_1h > ema_200_1h:
            status_1h = "BULLISH (Above EMA 200)"
        else:
            status_1h = "BEARISH (Below EMA 200)"
        print(f"1H Status: {status_1h}")
    else:
        print("Failed to get 1H data")
        return

    # 2. Fetch 15m data for EMA 21
    print("\nFetching 15m data...")
    df_15m = get_binance_klines(interval="15m", limit=100)

    if df_15m is not None:
        df_15m["EMA_21"] = calculate_ema(df_15m["Close"], 21)
        current_price_15m = df_15m["Close"].iloc[-1]
        ema_21_15m = df_15m["EMA_21"].iloc[-1]

        print(f"15m Price: {current_price_15m:.2f}")
        print(f"15m EMA 21: {ema_21_15m:.2f}")

        if current_price_15m > ema_21_15m:
            status_15m = "BULLISH (Above EMA 21)"
        else:
            status_15m = "BEARISH (Below EMA 21)"
        print(f"15m Status: {status_15m}")
    else:
        print("Failed to get 15m data")
        return

    # 3. Conclusion
    print("\n--- CONCLUSION ---")
    is_long_env = (current_price_1h > ema_200_1h) and (current_price_15m > ema_21_15m)
    is_short_env = (current_price_1h < ema_200_1h) and (current_price_15m < ema_21_15m)

    if is_long_env:
        print("✅ CURRENT ENVIRONMENT: LONG (看多)")
        print("Reason: 1H Price > EMA 200 AND 15m Price > EMA 21")
    elif is_short_env:
        print("🔻 CURRENT ENVIRONMENT: SHORT (看空)")
        print("Reason: 1H Price < EMA 200 AND 15m Price < EMA 21")
    else:
        print("⚠️ CURRENT ENVIRONMENT: NEUTRAL / MIXED (震荡/中性)")
        print("Reason: Signals are conflicting.")
        if current_price_1h > ema_200_1h:
            print("- 1H is Bullish")
        else:
            print("- 1H is Bearish")

        if current_price_15m > ema_21_15m:
            print("- 15m is Bullish")
        else:
            print("- 15m is Bearish")

if __name__ == "__main__":
    analyze_market_environment()
