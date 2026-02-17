import os
import requests
import json
from py_clob_client.client import ClobClient
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

def find_market_and_verify():
    # 1. 模拟 find_btc_market
    now_utc = datetime.now(timezone.utc)
    ts = int(now_utc.timestamp())
    current_window_start = ts - (ts % 300)

    # 查找当前和下一个窗口
    slugs = [
        f"btc-updown-5m-{current_window_start}",
        f"btc-updown-5m-{current_window_start + 300}"
    ]

    found_market = None
    gamma_api = "https://gamma-api.polymarket.com"

    for slug in slugs:
        print(f"Searching for market: {slug}")
        url = f"{gamma_api}/markets?slug={slug}"
        try:
            resp = requests.get(url)
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                found_market = data[0]
                print(f"Found Market: {found_market['question']} (ID: {found_market['id']})")
                break
        except Exception as e:
            print(f"API Error: {e}")

    if not found_market:
        print("No active BTC market found via Gamma API.")
        return

    # 2. 解析 Token IDs
    raw_ids = found_market.get('clobTokenIds')
    if isinstance(raw_ids, str):
        token_ids = json.loads(raw_ids)
    else:
        token_ids = raw_ids

    print(f"Token IDs: {token_ids}")

    # 3. 验证每个 Token 的 Order Book
    host = "https://clob.polymarket.com"
    chain_id = 137
    key = os.getenv("POLY_PRIVATE_KEY")
    funder = os.getenv("POLY_FUNDER")
    sig_type = int(os.getenv("POLY_SIGNATURE_TYPE", 1))

    client = ClobClient(host, key=key, chain_id=chain_id, signature_type=sig_type, funder=funder)

    for i, tid in enumerate(token_ids):
        print(f"\n--- Checking Token [{i}] ID: {tid} ---")
        try:
            ob = client.get_order_book(tid)
            if ob.asks:
                # 验证排序
                first = ob.asks[0].price
                last = ob.asks[-1].price
                min_p = min([float(x.price) for x in ob.asks])
                print(f"Asks Count: {len(ob.asks)}")
                print(f"First Ask: {first} | Last Ask: {last}")
                print(f"Real Min Price: {min_p}")
            else:
                print("Order Book exists but NO ASKS.")
        except Exception as e:
            print(f"Get OrderBook Failed: {e}")

if __name__ == "__main__":
    find_market_and_verify()
