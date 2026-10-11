import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import logging
from app.sheets.client import GoogleSheetsClient
from app.sheets.masters import MastersService

logging.basicConfig(level=logging.INFO)

def main():
    client = GoogleSheetsClient()
    if not client.is_connected:
        print("Google Sheets client not connected – check credentials.")
        return
    service = MastersService()
    service.refresh_all()
    # Access internal cache for demonstration purposes
    cache = service._cache
    for sede, rows in cache.items():
        print(f"{sede}: {len(rows)} records loaded")

if __name__ == "__main__":
    main()
