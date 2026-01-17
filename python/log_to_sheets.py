#!/usr/bin/env python3
"""
Log electricity meter readings to Google Sheets.
Reads current meter value from MQTT and appends a row to the sheet.

Requires:
  - Service account JSON key at ~/the-heat-mapper/google-credentials.json
  - Sheet shared with the service account email
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "11dOsZuRz0wvbhkFWGGZpq0Qjoq0gwsnVDfRx5Wk75sw"
CREDENTIALS_PATH = Path(__file__).parent.parent / "google-service-account-credentials.json"
MQTT_TOPIC = "prometheus/job/meter/node/light/total_kwh"

def get_meter_reading():
    """Get current meter reading via mosquitto_sub."""
    import subprocess
    result = subprocess.run(
        ["mosquitto_sub", "-h", "localhost", "-t", MQTT_TOPIC, "-C", "1", "-W", "10"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to read MQTT: {result.stderr}")
    return float(result.stdout.strip())

def main():
    if not CREDENTIALS_PATH.exists():
        print(f"Error: Credentials not found at {CREDENTIALS_PATH}")
        print("Create a service account at https://console.cloud.google.com/apis/credentials")
        print("Download the JSON key and save it as google-credentials.json")
        sys.exit(1)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)

    sheet = gc.open_by_key(SPREADSHEET_ID).sheet1

    reading = get_meter_reading()
    today = datetime.now().strftime("%d.%m.%Y")

    row = [today, int(reading), ""]  # Date, Licht, Heizung (empty for now)
    sheet.append_row(row, value_input_option="USER_ENTERED")

    print(f"Logged: {today} - Licht: {int(reading)} kWh")

if __name__ == "__main__":
    main()
