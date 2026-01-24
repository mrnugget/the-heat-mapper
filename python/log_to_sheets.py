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
MQTT_TOPIC_LIGHT = "prometheus/job/meter/node/light/total_kwh"
MQTT_TOPIC_HEATING = "prometheus/job/meter/node/heating/total_kwh"

def get_meter_reading(topic):
    """Get current meter reading via mosquitto_sub."""
    import subprocess
    result = subprocess.run(
        ["mosquitto_sub", "-h", "localhost", "-t", topic, "-C", "1", "-W", "10"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to read MQTT topic {topic}: {result.stderr}")
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

    reading_light = get_meter_reading(MQTT_TOPIC_LIGHT)
    reading_heating = get_meter_reading(MQTT_TOPIC_HEATING)
    today = datetime.now().strftime("%d.%m.%Y")

    row = [today, int(reading_light), int(reading_heating)]
    sheet.append_row(row, value_input_option="USER_ENTERED")

    print(f"Logged: {today} - Licht: {int(reading_light)} kWh, Heizung: {int(reading_heating)} kWh")

if __name__ == "__main__":
    main()
