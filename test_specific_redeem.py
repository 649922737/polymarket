import os
import time
import json
import logging
import requests
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_typed_data

# 模拟环境
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("SpecificRedeem")

# 配置
CONFIG = {
    "CHAIN_ID": 137,
    "RPC_URL": "https://polygon.drpc.org",
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

def redeem_specific_market(mid, my_side):
    """尝试赎回特定市场"""
    mid = str(mid)
    my_side = my_side.upper()

    logger.info(f"正在检查市场 {mid} (我持有的方向: {my_side})...")

    # 1. 初始化 Web3
    w3 = Web3(Web3.HTTPProvider(CONFIG.get("RPC_URL", "https://polygon-rpc.com")))
    if not w3.is_connected():
        logger.error("无法连接到 Polygon RPC")
        return

    account = w3.eth.account.from_key(CONFIG["PRIVATE_KEY"])

    # 确定检查余额的地址 (优先使用 Proxy)
    check_address = account.address
    if CONFIG["FUNDER"] and CONFIG["FUNDER"].lower() != account.address.lower():
        logger.info(f"使用代理钱包地址检查余额: {CONFIG['FUNDER']}")
        try:
            check_address = Web3.to_checksum_address(CONFIG["FUNDER"])
        except:
            check_address = CONFIG["FUNDER"]
    else:
        logger.info(f"使用 EOA 地址: {account.address}")

    ctf_contract = w3.eth.contract(address=CTF_ADDRESS, abi=CTF_ABI)

    try:
        # 2. 查询市场详情
        url = f"{CONFIG['GAMMA_API']}/markets/{mid}"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            logger.error(f"获取市场信息失败: {resp.status_code}")
            return

        market = resp.json()
        logger.info(f"市场问题: {market.get('question')}")

        if not market.get('closed'):
            logger.warning(f"市场尚未关闭 (closed={market.get('closed')})，无法赎回。")
            return

        # 3. 检查赢家
        raw_prices = market.get('outcomePrices', '[]')
        if isinstance(raw_prices, str):
            prices = json.loads(raw_prices)
        else:
            prices = raw_prices

        logger.info(f"最终价格: {prices}")

        # 寻找赢家 Index (Price > 0.9)
        winner_index = -1
        for i, p in enumerate(prices):
            try:
                if float(p) > 0.9:
                    winner_index = i
                    break
            except: pass

        if winner_index == -1:
            logger.warning("市场已关闭但未决出胜负 (无价格 > 0.9)。")
            return

        # 4. 检查链上余额 (使用 API Token IDs)
        condition_id_str = market.get('conditionId')
        raw_clob_token_ids = market.get('clobTokenIds')

        if isinstance(raw_clob_token_ids, str):
            try:
                clob_token_ids = json.loads(raw_clob_token_ids)
            except:
                clob_token_ids = []
        else:
            clob_token_ids = raw_clob_token_ids or []

        logger.info(f"API Token IDs: {clob_token_ids}")

        if not condition_id_str or not clob_token_ids:
            logger.error("无 conditionId 或 clobTokenIds")
            return

        condition_id_bytes = w3.to_bytes(hexstr=condition_id_str)
        parent_collection_id = b'\x00' * 32

        target_index_set = None
        target_balance = 0

        # Token ID Map: i -> Token ID -> Index Set (1 << i)
        for i, token_id_str in enumerate(clob_token_ids):
            try:
                position_id_int = int(token_id_str)
                idx_set = 1 << i # 假设 Token ID 顺序对应 Index Set 顺序 (0 -> 1, 1 -> 2)

                logger.info(f"Checking Token ID (Index {i}): {position_id_int}")

                # 检查 correct address
                balance = ctf_contract.functions.balanceOf(check_address, position_id_int).call()
                logger.info(f"  Index {i} (Set {idx_set}): Balance = {balance}")

                if balance > 0:
                    target_index_set = idx_set
                    target_balance = balance
            except Exception as e:
                logger.warning(f"查询失败: {e}")

        if target_index_set is None:
            logger.warning("⚠️ 链上未发现任何持仓余额！(可能已赎回、未成交或账户错误)")
            return

        logger.info(f"✅ 找到持仓! Index Set: {target_index_set} (Balance: {target_balance})")

        # 验证赢家
        my_held_index = 0 if target_index_set == 1 else 1
        if my_held_index != winner_index:
            logger.warning(f"⚠️ 警告: 我们持有的是 Index {my_held_index}，但赢家是 Index {winner_index}。")
            logger.warning("这通常意味着我们输了，合约可能会成功执行但 payout 为 0。")
        else:
            logger.info("✅ 确认: 我们持有的是赢家份额。")

        # 5. 构造交易
        if check_address != account.address:
            logger.info("检测到代理钱包，正在构建 Safe Transaction...")

            # 构造 redeemPositions 的 data
            temp_func = ctf_contract.functions.redeemPositions(
                USDC_ADDRESS,
                parent_collection_id,
                condition_id_bytes,
                [target_index_set]
            )
            redeem_tx = temp_func.build_transaction({
                'from': check_address,
                'gas': 100000,
                'gasPrice': 1000000000,
                'nonce': 0,
                'chainId': CONFIG["CHAIN_ID"]
            })
            redeem_data = redeem_tx['data']

            try:
                tx_hash = send_via_safe(w3, check_address, CONFIG["PRIVATE_KEY"], CTF_ADDRESS, redeem_data)
                logger.info(f"✅ Gnosis Safe 交易已发送: {tx_hash.hex()}")
                logger.info(f"Explorer: https://polygonscan.com/tx/{tx_hash.hex()}")
                return
            except Exception as e:
                logger.error(f"Safe Transaction 失败: {e}")
                return

        func = ctf_contract.functions.redeemPositions(
            USDC_ADDRESS,
            parent_collection_id,
            condition_id_bytes,
            [target_index_set]
        )

        try:
            # 尝试估算 Gas
            gas_estimate = func.estimate_gas({'from': account.address})
            logger.info(f"Gas 估算成功: {gas_estimate}")

            tx = func.build_transaction({
                'from': account.address,
                'nonce': w3.eth.get_transaction_count(account.address),
                'gas': int(gas_estimate * 1.2),
                'gasPrice': w3.eth.gas_price,
                'chainId': CONFIG["CHAIN_ID"]
            })

            logger.info("正在发送赎回交易...")
            signed_tx = w3.eth.account.sign_transaction(tx, CONFIG["PRIVATE_KEY"])

            raw_tx = getattr(signed_tx, 'rawTransaction', None) or getattr(signed_tx, 'raw_transaction', None)

            if not raw_tx:
                logger.error("无法获取 raw transaction bytes")
                return

            tx_hash = w3.eth.send_raw_transaction(raw_tx)
            logger.info(f"✅ 领取奖励交易已发送: {tx_hash.hex()}")
            logger.info(f"Explorer: https://polygonscan.com/tx/{tx_hash.hex()}")

        except Exception as e:
            if "execution reverted" in str(e):
                logger.warning(f"无法赎回 (可能余额为0或已领取): {e}")
            elif "insufficient funds" in str(e):
                logger.error(f"❌ Gas 费不足: {e}")
                logger.info("请向账户充值少量 MATIC/POL。")
            else:
                logger.error(f"赎回交易失败: {e}")

    except Exception as e:
        logger.error(f"处理异常: {e}")

if __name__ == "__main__":
    redeem_specific_market(1379642, "YES")
