import os
import requests
import json
from eth_account import Account

# ==================== 配置 ====================
RPC_URL = "https://polygon-rpc.com"

# 两个 USDC 地址
USDC_BRIDGED = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174" # USDC.e
USDC_NATIVE  = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359" # USDC

# Polymarket CTF Exchange 合约地址
CTF_EXCHANGE = "0x4D97DCd97eC945f40cF65F87097ACE5EA0476045"

def rpc_call(method, params):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1
    }
    try:
        resp = requests.post(RPC_URL, json=payload, timeout=5)
        return resp.json()
    except Exception as e:
        return {}

def get_balance(wallet, token_addr):
    # balanceOf(address) -> 70a08231...
    data = "0x70a08231" + wallet[2:].lower().zfill(64)
    res = rpc_call("eth_call", [{"to": token_addr, "data": data}, "latest"])
    hex_val = res.get("result", "0x0")
    if hex_val is None: hex_val = "0x0"
    return int(hex_val, 16) / 1000000  # USDC 6 decimals

def get_allowance(owner, spender, token_addr):
    # allowance(address,address) -> dd62ed3e...
    data = "0xdd62ed3e" + owner[2:].lower().zfill(64) + spender[2:].lower().zfill(64)
    res = rpc_call("eth_call", [{"to": token_addr, "data": data}, "latest"])
    hex_val = res.get("result", "0x0")
    if hex_val is None: hex_val = "0x0"
    return int(hex_val, 16) / 1000000

def check_address(label, addr):
    if not addr: return
    print(f"\n🔍 检查地址 ({label}): {addr}")

    # 1. 检查 Matic (Gas)
    res = rpc_call("eth_getBalance", [addr, "latest"])
    matic = int(res.get("result", "0x0"), 16) / 10**18
    print(f"   ⛽ MATIC 余额: {matic:.4f}")

    # 2. 检查 Bridged USDC
    bal_e = get_balance(addr, USDC_BRIDGED)
    allow_e = get_allowance(addr, CTF_EXCHANGE, USDC_BRIDGED)
    print(f"   💰 USDC.e (Bridged): 余额={bal_e:,.2f} | 授权={allow_e:,.2f}")

    # 3. 检查 Native USDC
    bal_n = get_balance(addr, USDC_NATIVE)
    allow_n = get_allowance(addr, CTF_EXCHANGE, USDC_NATIVE)
    print(f"   💰 USDC (Native):    余额={bal_n:,.2f} | 授权={allow_n:,.2f}")

def main():
    private_key = os.getenv("POLY_PRIVATE_KEY")
    funder_env = os.getenv("POLY_FUNDER")

    signer_addr = None
    if private_key:
        try:
            signer_addr = Account.from_key(private_key).address
        except:
            print("❌ 私钥格式错误")

    print("=" * 50)
    print("Polymarket 资金深度检查")
    print("=" * 50)

    if signer_addr:
        check_address("Signer / EOA", signer_addr)

    if funder_env and (funder_env.lower() != (signer_addr or "").lower()):
        check_address("Funder / Proxy", funder_env)
    elif not funder_env:
        print("\n❌ 未设置 POLY_FUNDER 环境变量")

    # 额外检查用户提供的地址
    manual_addr = "0x4d530fb3981763e1acb2d12fe9217bae36312204"
    if manual_addr.lower() != (signer_addr or "").lower() and manual_addr.lower() != (funder_env or "").lower():
        check_address("User Provided", manual_addr)

    print("\n" + "=" * 50)
    print("分析建议:")
    print("1. Polymarket 主要使用 USDC.e (Bridged)。")
    print("2. 下单时使用的是 Funder 地址的余额。")
    print("3. 如果 Funder 是 Proxy，确保 Proxy 有钱且已授权。")
    print("4. 如果用 EOA 下单 (SignatureType=0)，资金必须在 Signer 地址。")
    print("=" * 50)

if __name__ == "__main__":
    main()
