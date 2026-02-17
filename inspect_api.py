import requests
import json
from datetime import datetime, timezone

def inspect_active():
    # 获取当前的活跃市场
    now_utc = datetime.now(timezone.utc)
    ts = int(now_utc.timestamp())
    current_window_start = ts - (ts % 300)
    slug = f"btc-updown-5m-{current_window_start}"

    url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
    print(f"Querying: {url}")

    try:
        resp = requests.get(url)
        data = resp.json()
        if data and isinstance(data, list) and len(data) > 0:
            market = data[0]
            print(json.dumps(market, indent=2))

            print("-" * 30)
            print(f"Question: {market.get('question')}")
            print(f"Description: {market.get('description')}")
        else:
            print("No active market found with this slug. Trying generic search...")
            # 备选：随便找个 active 的
            url2 = "https://gamma-api.polymarket.com/markets?active=true&limit=1&tag_id=1" # tag 1 usually crypto
            resp2 = requests.get(url2)
            data2 = resp2.json()
            if data2:
                print(json.dumps(data2[0], indent=2))

    except Exception as e:
        print(e)

    # Check CLOB API as well
    print("-" * 30)
    print("Checking CLOB API for market details...")
    if 'market' in locals():
        try:
             # Just query by condition ID as it's common
             cond_id = market.get('conditionId')
             if cond_id:
                 clob_url = f"https://clob.polymarket.com/markets/{cond_id}"
                 print(f"Querying CLOB: {clob_url}")
                 r = requests.get(clob_url)
                 if r.status_code == 200:
                     print(json.dumps(r.json(), indent=2))
                 else:
                     print(f"CLOB Error: {r.status_code} {r.text}")
        except Exception as e:
            print(f"CLOB Check Error: {e}")

if __name__ == "__main__":
    inspect_active()
