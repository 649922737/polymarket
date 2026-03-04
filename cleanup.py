import os
import glob
from datetime import datetime, timedelta

def cleanup_old_files():
    # Keep last 7 days (today is 2026-03-02)
    cutoff_date = datetime.strptime("2026-02-23", "%Y-%m-%d")

    print(f"Cleaning up files older than {cutoff_date.strftime('%Y-%m-%d')}...\n")

    patterns = [
        "trade_history_*.csv",
        "market_data/fluctuations_*.json",
        "market_data/net_changes_*.json",
    ]

    deleted_count = 0

    for pattern in patterns:
        files = glob.glob(pattern)
        for f in files:
            # Extract date from filename
            # Format usually: trade_history_YYYY-MM-DD.csv or trade_history_15m_YYYY-MM-DD.csv
            # fluctuations_YYYY-MM-DD.json
            try:
                import re
                match = re.search(r'(\d{4}-\d{2}-\d{2})', f)
                if match:
                    date_str = match.group(1)
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")

                    if file_date < cutoff_date:
                        print(f"Deleting: {f}")
                        os.remove(f)
                        deleted_count += 1
            except Exception as e:
                print(f"Error checking {f}: {e}")

    print(f"\nCleanup complete. Deleted {deleted_count} files.")

if __name__ == "__main__":
    cleanup_old_files()
