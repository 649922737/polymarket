import os
from py_clob_client.client import ClobClient
import json

def debug_prob(token_id):
    host = "https://clob.polymarket.com"
    chain_id = 137
    key = os.getenv("POLY_PRIVATE_KEY")
    funder = os.getenv("POLY_FUNDER")
    sig_type = int(os.getenv("POLY_SIGNATURE_TYPE", 1))

    if not key or not funder:
        print("Missing env vars")
        return

    try:
        client = ClobClient(host, key=key, chain_id=chain_id, signature_type=sig_type, funder=funder)

        print(f"Fetching Orderbook for Token: {token_id}")
        ob = client.get_order_book(token_id)

        print("\n=== Order Book Raw Dump ===")
        # 尝试转为 dict 打印，或者直接打印对象属性
        try:
            # 假设 ob 是 OrderBookSummary 对象
            print(f"Asks: {ob.asks}")
            print(f"Bids: {ob.bids}")

            if ob.asks and len(ob.asks) > 0:
                print(f"\nBest Ask: {ob.asks[0].price} (Size: {ob.asks[0].size})")
            else:
                print("\nNo Asks found!")

        except Exception as e:
            print(f"Dump error: {e}")
            print(f"Raw Object: {ob}")

    except Exception as e:
        print(f"Client error: {e}")

if __name__ == "__main__":
    # 使用你日志里的 Token ID
    debug_prob("38484856447535969656886369981054577540986181214773356195167051379788989678932")
