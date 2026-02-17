import os
import requests

CONFIG = {
    "FUNDER": os.getenv("POLY_FUNDER"),
    "HOST": "https://clob.polymarket.com"
}

def check_clob_positions():
    if not CONFIG["FUNDER"]:
        print("Set POLY_FUNDER env var")
        return

    # 尝试多种路径
    paths = [
        f"/positions?user={CONFIG['FUNDER']}",
        f"/balance?user={CONFIG['FUNDER']}",
        f"/account?user={CONFIG['FUNDER']}"
    ]

    for p in paths:
        url = CONFIG["HOST"] + p
        print(f"Checking {url}...")
        try:
            resp = requests.get(url)
            print(f"Status: {resp.status_code}")
            if resp.status_code == 200:
                print(resp.text[:500])
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    check_clob_positions()
