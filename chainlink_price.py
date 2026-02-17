from web3 import Web3
import time
import logging

# 配置日志
logger = logging.getLogger("Chainlink")

# Polygon RPC (可以使用 autoorder.py 中的 CONFIG["RPC_URL"])
# 这里为了独立测试，先写死一个公共 RPC，实际集成时会用配置
DEFAULT_RPC = "https://polygon.drpc.org"

# Chainlink WBTC/USD Price Feed (Polygon)
# 注意：原 BTC/USD 地址 0xc907... 已失效，改为 WBTC/USD
FEED_ADDRESS = "0xDE31F8bFBD8c84b5360CFACCa3539B938dd78ae6"

ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"internalType": "uint80", "name": "roundId", "type": "uint80"},
            {"internalType": "int256", "name": "answer", "type": "int256"},
            {"internalType": "uint256", "name": "startedAt", "type": "uint256"},
            {"internalType": "uint256", "name": "updatedAt", "type": "uint256"},
            {"internalType": "uint80", "name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint80", "name": "_roundId", "type": "uint80"}],
        "name": "getRoundData",
        "outputs": [
            {"internalType": "uint80", "name": "roundId", "type": "uint80"},
            {"internalType": "int256", "name": "answer", "type": "int256"},
            {"internalType": "uint256", "name": "startedAt", "type": "uint256"},
            {"internalType": "uint256", "name": "updatedAt", "type": "uint256"},
            {"internalType": "uint80", "name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    }
]

class ChainlinkPrice:
    def __init__(self, rpc_url=None):
        self.rpc_url = rpc_url or DEFAULT_RPC
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        self.contract = None
        self.decimals = 8 # BTC/USD 默认为 8

        if self.w3.is_connected():
            try:
                # 自动处理 Checksum
                checksum_addr = self.w3.to_checksum_address(FEED_ADDRESS)
                logger.info(f"Connecting to Chainlink Feed: {checksum_addr}")

                # Debug: 检查 RPC 和 ChainID
                chain_id = self.w3.eth.chain_id
                logger.info(f"Connected to Chain ID: {chain_id}")
                if chain_id != 137:
                    logger.warning(f"警告: 当前连接的 ChainID 是 {chain_id}，而 Polygon Mainnet 应该是 137！")

                # Debug: 检查合约是否存在
                code = self.w3.eth.get_code(checksum_addr)
                if code == b'' or code == '0x':
                    logger.error(f"严重错误: 地址 {checksum_addr} 上没有合约代码！请检查地址或网络。")
                    raise ValueError("Contract code not found")

                self.contract = self.w3.eth.contract(address=checksum_addr, abi=ABI)
                self.decimals = self.contract.functions.decimals().call()
                logger.info(f"Chainlink initialized. Decimals: {self.decimals}")
            except Exception as e:
                logger.error(f"Chainlink init failed: {e}")
        else:
            logger.error("Chainlink RPC Connection failed")

    def get_latest_price(self):
        """获取最新的 BTC 价格"""
        if not self.contract:
            return None

        try:
            # latestRoundData 返回: (roundId, answer, startedAt, updatedAt, answeredInRound)
            data = self.contract.functions.latestRoundData().call()
            # ... (保持原样)
            raw_price = data[1]
            updated_at = data[3]
            price = float(raw_price) / (10 ** self.decimals)
            return price
        except Exception as e:
            logger.error(f"获取 Chainlink 价格失败: {e}")
            return None

    def get_historical_price(self, target_dt):
        """获取指定时间点 (UTC) 附近的 Chainlink 历史价格"""
        if not self.contract:
            return None

        # 确保 timestamp 是 int
        if hasattr(target_dt, 'timestamp'):
            target_ts = int(target_dt.timestamp())
        else:
            target_ts = int(target_dt) if isinstance(target_dt, (int, float)) else int(time.time())

        try:
            # 1. 获取最新 Round
            latest_data = self.contract.functions.latestRoundData().call()
            latest_round_id = latest_data[0]
            latest_ts = latest_data[3]

            # 如果最新时间比目标时间还早，那只能返回最新价 (说明链上很久没更新了，或者还没到那个时间)
            if latest_ts <= target_ts:
                logger.info(f"Chainlink 最新数据时间 {latest_ts} <= 目标时间 {target_ts}，直接使用最新价。")
                return float(latest_data[1]) / (10 ** self.decimals)

            # 2. 往回回溯查找
            # 我们假设 BTC 更新频率较高，回溯 50 个 Round 通常能覆盖 1-2 小时
            # 如果回溯太多 RPC 会慢，所以设置一个上限
            check_round_id = latest_round_id

            logger.info(f"正在回溯 Chainlink Round (Current={check_round_id}, TargetTS={target_ts})...")

            for i in range(50):
                check_round_id -= 1
                try:
                    # getRoundData(roundId)
                    round_data = self.contract.functions.getRoundData(check_round_id).call()
                    round_ts = round_data[3]
                    round_price = float(round_data[1]) / (10 ** self.decimals)

                    # 找到第一个 <= target_ts 的点
                    if round_ts <= target_ts:
                        logger.info(f"Chainlink 历史命中: Round={check_round_id}, TS={round_ts}, Price={round_price}")
                        return round_price

                    # 如果还没找到，继续循环

                except Exception as e:
                    logger.warning(f"回溯 Chainlink Round {check_round_id} 失败: {e}")
                    # 如果 RoundID 不存在或报错，停止回溯
                    break

            logger.warning(f"回溯 50 个 Round 后仍未找到 <= {target_ts} 的数据。")
            return None

        except Exception as e:
            logger.error(f"获取 Chainlink 历史价格异常: {e}")
            return None

# 测试运行
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cp = ChainlinkPrice()
    p = cp.get_latest_price()
    print(f"当前 Chainlink 价格: {p}")
