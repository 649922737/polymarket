import csv
import json
import requests
import time
import logging
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger()

def analyze_pnl():
    trades = []
    # Read CSV
    with open('trade_history.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append(row)

    logger.info(f"Total trades logged: {len(trades)}")

    # Filter for unique markets (assuming one trade per market for now)
    # If multiple trades per market, we need to handle that.
    # Logic: Group by market_id
    market_trades = defaultdict(list)
    for t in trades:
        market_trades[t['market_id']].append(t)

    # We will analyze the last 50 markets to save time/API
    market_ids = list(market_trades.keys())
    # recent_market_ids = market_ids[-50:]
    # Analyze ALL for better stats, but handle rate limits
    recent_market_ids = market_ids

    logger.info(f"Analyzing {len(recent_market_ids)} markets...")

    stats = {
        "Condition_1": {"wins": 0, "total": 0, "pnl": 0.0},
        "Condition_2": {"wins": 0, "total": 0, "pnl": 0.0},
        "Condition_3": {"wins": 0, "total": 0, "pnl": 0.0},
        "Condition_4": {"wins": 0, "total": 0, "pnl": 0.0},
        "Condition_5": {"wins": 0, "total": 0, "pnl": 0.0},
        "Other": {"wins": 0, "total": 0, "pnl": 0.0},
    }

    processed_count = 0

    for mid in recent_market_ids:
        try:
            # Check cache or local logic? No, just API
            url = f"https://gamma-api.polymarket.com/markets/{mid}"
            resp = requests.get(url, timeout=5)

            if resp.status_code != 200:
                logger.warning(f"Failed to fetch market {mid}: {resp.status_code}")
                continue

            m = resp.json()
            if not m.get('closed'):
                # logger.info(f"Market {mid} not closed yet.")
                continue

            outcome_prices = json.loads(m.get('outcomePrices', '[]'))
            # Assume Binary: ["0", "1"] or ["1", "0"] or ["0.5", "0.5"] (void)

            winner = None
            if len(outcome_prices) >= 2:
                p0 = float(outcome_prices[0])
                p1 = float(outcome_prices[1])
                if p0 > 0.9: winner = "NO" # Index 0 usually NO/Down? Wait.
                elif p1 > 0.9: winner = "YES" # Index 1 usually YES/Up?

            # Need to verify outcome index mapping.
            # Usually Index 0 is NO/Down, Index 1 is YES/Up.
            # Let's check outcomes list if available
            outcomes = json.loads(m.get('outcomes', '["No", "Yes"]'))

            if winner is None:
                # Loop to find which index has 1
                for idx, p_str in enumerate(outcome_prices):
                    if float(p_str) > 0.9:
                        # Map index to "YES"/"NO"
                        # Standard Polymarket Binary: 0=No, 1=Yes.
                        # But sometimes it's "Down"/"Up".
                        label = outcomes[idx].upper()
                        if label in ["YES", "UP"]: winner = "YES"
                        elif label in ["NO", "DOWN"]: winner = "NO"
                        break

            if not winner:
                continue # Void or unresolved

            # Check our trades on this market
            for t in market_trades[mid]:
                side = t['side'] # YES or NO
                condition_raw = t['condition']

                # Classify Condition
                cond_key = "Other"
                if "Condition_1" in condition_raw: cond_key = "Condition_1"
                elif "Condition_2" in condition_raw: cond_key = "Condition_2"
                elif "Condition_3" in condition_raw: cond_key = "Condition_3"
                elif "Condition_4" in condition_raw: cond_key = "Condition_4"
                elif "Condition_5" in condition_raw: cond_key = "Condition_5"

                cost = float(t.get('amount', 2.0)) # Default 2.0

                # Calculate PnL
                # If Win: Return ~2.0 USDC (minus fees/slippage? No, pay out is 1.0 per share)
                # Wait, Cost is USDC spent.
                # If we bought X shares. Return is X * 1.0 (if win) or 0 (if loss).
                # We need to know 'size' (Shares) to calc exact profit.
                # CSV has 'amount' which is usually Cost (Target Spend).
                # Earlier logic: Size = Amount / 0.99.
                # So Shares ~= Amount.
                # Profit = (Shares * 1.0) - Cost.
                # If Shares ~= Cost, Profit is close to 0??
                # No!
                # Cost = Shares * PricePaid.
                # If Price was 0.50. Cost = 2.0. Shares = 4.0.
                # Win: Get 4.0. Profit = 4.0 - 2.0 = +2.0.
                # Loss: Get 0. Profit = -2.0.

                # BUT, our bot buys at MARKET (High Limit).
                # poly_price in CSV is the 'prob' (Best Ask) at trigger time.
                # approximate_price = float(t['poly_price'])
                # estimated_shares = cost / approximate_price

                approx_price = float(t.get('poly_price', 0.5))
                if approx_price == 0: approx_price = 0.5

                est_shares = cost / approx_price

                if side == winner:
                    # WIN
                    pnl = est_shares - cost
                    stats[cond_key]["wins"] += 1
                else:
                    # LOSS
                    pnl = -cost

                stats[cond_key]["total"] += 1
                stats[cond_key]["pnl"] += pnl

            processed_count += 1
            if processed_count % 10 == 0:
                print(f"Processed {processed_count} markets...")

            # Rate limit
            time.sleep(0.2)

        except Exception as e:
            logger.error(f"Error processing {mid}: {e}")

    # Report
    print("\n" + "="*60)
    print(f"{'Strategy':<15} | {'Win Rate':<10} | {'Trades':<6} | {'Est. PnL (USDC)':<15}")
    print("-" * 60)

    total_pnl = 0
    total_trades = 0

    for k, s in sorted(stats.items()):
        if s['total'] == 0: continue
        win_rate = (s['wins'] / s['total']) * 100
        print(f"{k:<15} | {win_rate:6.2f}%    | {s['total']:<6} | {s['pnl']:+.2f}")
        total_pnl += s['pnl']
        total_trades += s['total']

    print("-" * 60)
    print(f"{'TOTAL':<15} | {(total_pnl/total_trades if total_trades else 0):6.2f} (Avg)| {total_trades:<6} | {total_pnl:+.2f}")
    print("="*60)

if __name__ == "__main__":
    analyze_pnl()
