import os
import time
import json
import logging
import requests
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_typed_data

# 模拟 autoorder.py 的环境
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("Settle")

# 配置
CONFIG = {
    "CHAIN_ID": 137,
    "RPC_URL": "https://polygon.drpc.org", # Use reliable RPC
    "PRIVATE_KEY": os.getenv("POLY_PRIVATE_KEY"),
    "FUNDER": os.getenv("POLY_FUNDER"),
    "GAMMA_API": "https://gamma-api.polymarket.com",
}

if not CONFIG["PRIVATE_KEY"] or not CONFIG["FUNDER"]:
    raise ValueError("请设置 POLY_PRIVATE_KEY 和 POLY_FUNDER 环境变量")

# CTF 合约
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CTF_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"}
        ],
        "name": "redeemPositions",
        "outputs": [],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "id", "type": "uint256"}
        ],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    }
]

SAFE_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "nonce",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "data", "type": "bytes"},
            {"name": "operation", "type": "uint8"},
            {"name": "safeTxGas", "type": "uint256"},
            {"name": "baseGas", "type": "uint256"},
            {"name": "gasPrice", "type": "uint256"},
            {"name": "gasToken", "type": "address"},
            {"name": "refundReceiver", "type": "address"},
            {"name": "signatures", "type": "bytes"}
        ],
        "name": "execTransaction",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

def send_via_safe(w3, safe_address, signer_key, to_addr, data):
    """通过 Gnosis Safe 发送交易"""
    safe_contract = w3.eth.contract(address=safe_address, abi=SAFE_ABI)
    nonce = safe_contract.functions.nonce().call()
    logger.info(f"Safe Nonce: {nonce}")

    # 构建 Safe Transaction Data
    safe_tx = {
        "to": to_addr,
        "value": 0,
        "data": data,
        "operation": 0, # Call
        "safeTxGas": 0,
        "baseGas": 0,
        "gasPrice": 0,
        "gasToken": "0x0000000000000000000000000000000000000000",
        "refundReceiver": "0x0000000000000000000000000000000000000000",
        "nonce": nonce
    }

    # 构建 EIP-712 Typed Data
    domain_data = {
        "verifyingContract": safe_address,
        "chainId": CONFIG["CHAIN_ID"]
    }

    message_types = {
        "SafeTx": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "data", "type": "bytes"},
            {"name": "operation", "type": "uint8"},
            {"name": "safeTxGas", "type": "uint256"},
            {"name": "baseGas", "type": "uint256"},
            {"name": "gasPrice", "type": "uint256"},
            {"name": "gasToken", "type": "address"},
            {"name": "refundReceiver", "type": "address"},
            {"name": "nonce", "type": "uint256"}
        ]
    }

    # Sign the message
    signed_msg = w3.eth.account.sign_typed_data(
        signer_key,
        domain_data,
        message_types,
        safe_tx
    )

    signature = signed_msg.signature

    # Execute Transaction
    func = safe_contract.functions.execTransaction(
        safe_tx["to"],
        safe_tx["value"],
        safe_tx["data"],
        safe_tx["operation"],
        safe_tx["safeTxGas"],
        safe_tx["baseGas"],
        safe_tx["gasPrice"],
        safe_tx["gasToken"],
        safe_tx["refundReceiver"],
        signature
    )

    signer_addr = w3.eth.account.from_key(signer_key).address
    gas_estimate = func.estimate_gas({'from': signer_addr})
    logger.info(f"Safe Exec Gas Estimate: {gas_estimate}")

    tx = func.build_transaction({
        'from': signer_addr,
        'nonce': w3.eth.get_transaction_count(signer_addr),
        'gas': int(gas_estimate * 1.2),
        'gasPrice': w3.eth.gas_price,
        'chainId': CONFIG["CHAIN_ID"]
    })

    signed_tx = w3.eth.account.sign_transaction(tx, signer_key)
    raw_tx = getattr(signed_tx, 'rawTransaction', None) or getattr(signed_tx, 'raw_transaction', None)
    tx_hash = w3.eth.send_raw_transaction(raw_tx)

    return tx_hash

def settle_positions():
    """定期结算盈利 (基于本地记录 + Web3 + Proxy)"""
    try:
        logger.info("正在检查可领取奖励...")

        # 1. 读取本地交易记录
        history_file = "trade_history.csv"
        if not os.path.exists(history_file):
            logger.info("无交易记录。")
            return

        # 获取所有交易过的 Market ID
        my_markets = set()
        with open(history_file, 'r') as f:
            lines = f.readlines()
            if len(lines) > 1:
                for line in lines[1:]:
                    parts = line.strip().split(',')
                    if len(parts) >= 4:
                        mid = parts[1]
                        my_markets.add(mid)

        logger.info(f"本地记录中共有 {len(my_markets)} 个参与市场。")

        # 2. 读取已赎回记录 (避免重复)
        redeemed_file = "redeemed_history.json"
        redeemed_ids = set()
        if os.path.exists(redeemed_file):
            try:
                with open(redeemed_file, 'r') as f:
                    redeemed_ids = set(json.load(f))
            except:
                pass

        # 3. 初始化 Web3
        w3 = Web3(Web3.HTTPProvider(CONFIG.get("RPC_URL")))
        if not w3.is_connected():
            logger.error("无法连接到 Polygon RPC")
            return

        account = w3.eth.account.from_key(CONFIG["PRIVATE_KEY"])
        ctf_contract = w3.eth.contract(address=CTF_ADDRESS, abi=CTF_ABI)

        # 确定检查地址
        check_address = account.address
        if CONFIG["FUNDER"] and CONFIG["FUNDER"].lower() != account.address.lower():
            logger.info(f"使用代理钱包地址检查余额: {CONFIG['FUNDER']}")
            try:
                check_address = Web3.to_checksum_address(CONFIG["FUNDER"])
            except:
                check_address = CONFIG["FUNDER"]
        else:
            logger.info(f"使用 EOA 地址: {account.address}")

        # 4. 遍历市场并检查
        new_redeemed = False

        for mid in my_markets:
            if mid in redeemed_ids:
                continue

            try:
                logger.info(f"检查市场 {mid}...")
                # 查询市场详情
                url = f"{CONFIG['GAMMA_API']}/markets/{mid}"
                resp = requests.get(url, timeout=5)
                if resp.status_code != 200:
                    logger.warning(f"获取市场信息失败: {resp.status_code}")
                    continue

                market = resp.json()
                if not market.get('closed'):
                    continue

                # 检查赢家
                raw_prices = market.get('outcomePrices', '[]')
                if isinstance(raw_prices, str):
                    prices = json.loads(raw_prices)
                else:
                    prices = raw_prices

                # 寻找赢家 Index (Price > 0.9)
                winner_index = -1
                for i, p in enumerate(prices):
                    try:
                        if float(p) > 0.9:
                            winner_index = i
                            break
                    except: pass

                if winner_index == -1:
                    logger.info(f"市场 {mid} 已关闭但未决出胜负 (Prices: {prices})")
                    continue

                # 检查余额 (使用 API Token IDs)
                clob_token_ids = market.get('clobTokenIds', [])
                if isinstance(clob_token_ids, str):
                    try:
                        clob_token_ids = json.loads(clob_token_ids)
                    except:
                        clob_token_ids = []

                if not clob_token_ids:
                    logger.warning(f"市场 {mid} 无 Token IDs")
                    continue

                # 遍历 Token IDs 寻找余额
                found_winnings = False

                for i, token_id_str in enumerate(clob_token_ids):
                    try:
                        position_id_int = int(token_id_str)
                        # 检查 correct address
                        balance = ctf_contract.functions.balanceOf(check_address, position_id_int).call()

                        if balance > 0:
                            logger.info(f"Market {mid} | Index {i} | Balance: {balance}")

                            # 只有当我们持有赢家份额时才赎回
                            if i == winner_index:
                                logger.info(f"🎉 发现可领取赢家份额! Market {mid}")

                                # 准备赎回
                                condition_id_str = market.get('conditionId')
                                condition_id_bytes = w3.to_bytes(hexstr=condition_id_str)
                                parent_collection_id = b'\x00' * 32
                                index_set = 1 << i # Index set for outcome i

                                # 构造 redeemPositions 数据
                                temp_func = ctf_contract.functions.redeemPositions(
                                    USDC_ADDRESS,
                                    parent_collection_id,
                                    condition_id_bytes,
                                    [index_set]
                                )

                                tx_hash = None

                                if check_address != account.address:
                                    # Safe
                                    redeem_tx = temp_func.build_transaction({
                                        'from': check_address,
                                        'gas': 100000,
                                        'gasPrice': w3.eth.gas_price,
                                        'nonce': 0,
                                        'chainId': CONFIG["CHAIN_ID"]
                                    })
                                    redeem_data = redeem_tx['data']

                                    try:
                                        tx_hash = send_via_safe(w3, check_address, CONFIG["PRIVATE_KEY"], CTF_ADDRESS, redeem_data)
                                    except Exception as e:
                                        logger.error(f"Safe 交易发送失败: {e}")
                                else:
                                    # EOA
                                    gas_estimate = temp_func.estimate_gas({'from': account.address})
                                    tx = temp_func.build_transaction({
                                        'from': account.address,
                                        'nonce': w3.eth.get_transaction_count(account.address),
                                        'gas': int(gas_estimate * 1.2),
                                        'gasPrice': w3.eth.gas_price,
                                        'chainId': CONFIG["CHAIN_ID"]
                                    })
                                    signed_tx = w3.eth.account.sign_transaction(tx, CONFIG["PRIVATE_KEY"])
                                    raw_tx = getattr(signed_tx, 'rawTransaction', None) or getattr(signed_tx, 'raw_transaction', None)
                                    tx_hash = w3.eth.send_raw_transaction(raw_tx)

                                if tx_hash:
                                    logger.info(f"✅ 赎回交易已发送: {tx_hash.hex()}")
                                    found_winnings = True
                                    time.sleep(5)

                            else:
                                logger.info(f"持有输家份额 (Index {i} != Winner {winner_index})，不赎回。")
                                # 即使输了，也算处理过了吗？
                                # 如果我们只持有输家份额，那就没有东西可赎回，标记为已处理
                                found_winnings = True # 标记为 True 以便添加到 redeemed_ids

                    except Exception as e:
                        logger.error(f"检查余额/赎回失败: {e}")

                # 如果我们检查了所有 Token 并处理了(赢了赎回，输了跳过)，或者根本没余额
                # 标记为已完成
                # 如果没余额，也标记为已完成
                redeemed_ids.add(mid)
                new_redeemed = True

            except Exception as e:
                logger.error(f"检查市场 {mid} 异常: {e}")

        # 保存已赎回记录
        if new_redeemed:
            with open(redeemed_file, 'w') as f:
                json.dump(list(redeemed_ids), f)
            logger.info("已更新 redeemed_history.json")
        else:
            logger.info("没有新的可赎回市场。")

    except Exception as e:
        logger.error(f"结算流程失败: {e}")

if __name__ == "__main__":
    settle_positions()
