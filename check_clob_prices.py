from py_clob_client.client import ClobClient
import os
import json

def check_prices():
    host = "https://clob.polymarket.com"
    chain_id = 137
    key = os.getenv("POLY_PRIVATE_KEY")
    funder = os.getenv("POLY_FUNDER")

    # We need a valid token_id. Let's use one from the previous inspection
    # Token IDs for "Bitcoin Up or Down - February 16, 11:30AM-11:35AM ET"
    token_id = "31136039962616367566967064020359897612453237023569638936727980157195184199288"

    if not key:
        print("Missing POLY_PRIVATE_KEY")
        return

    try:
        client = ClobClient(host, key=key, chain_id=chain_id, signature_type=1, funder=funder)

        print(f"Checking get_price for token {token_id}...")
        try:
            price = client.get_price(token_id)
            print(f"get_price result: {price}")
        except Exception as e:
            print(f"get_price error: {e}")

        print(f"Checking get_last_trade_price for token {token_id}...")
        try:
            last = client.get_last_trade_price(token_id)
            print(f"get_last_trade_price result: {last}")
        except Exception as e:
            print(f"get_last_trade_price error: {e}")

    except Exception as e:
        print(f"Client init error: {e}")

if __name__ == "__main__":
    check_prices()