from py_clob_client.client import ClobClient
import os

try:
    client = ClobClient(host="https://clob.polymarket.com", chain_id=137, key=os.getenv("POLY_PRIVATE_KEY"))
    print("Methods available in ClobClient:")
    for m in dir(client):
        if not m.startswith("_"):
            print(m)
except Exception as e:
    print(f"Error: {e}")
