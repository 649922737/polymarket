import csv
import os
from datetime import datetime

def migrate_history():
    source_file = "trade_history.csv"
    if not os.path.exists(source_file):
        print(f"{source_file} not found.")
        return

    print(f"Migrating {source_file}...")

    with open(source_file, 'r') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    files_created = set()

    for row in rows:
        ts_str = row['timestamp']
        try:
            # Parse timestamp "YYYY-MM-DD HH:MM:SS"
            dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            date_str = dt.strftime("%Y-%m-%d")
            target_file = f"trade_history_{date_str}.csv"

            # Check if we need to write header
            file_exists = os.path.exists(target_file)

            # If we haven't touched this file in this run, and it exists,
            # we assume it might be pre-existing or created by previous run.
            # But since we are migrating, we should append.

            with open(target_file, 'a', newline='') as tf:
                writer = csv.DictWriter(tf, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                    files_created.add(target_file)

                writer.writerow(row)

        except Exception as e:
            print(f"Error processing row {row}: {e}")

    print(f"Migration complete. Data distributed to {len(files_created)} files.")

    # Rename original file
    backup_file = "trade_history_backup.csv"
    os.rename(source_file, backup_file)
    print(f"Renamed original file to {backup_file}")

if __name__ == "__main__":
    migrate_history()
