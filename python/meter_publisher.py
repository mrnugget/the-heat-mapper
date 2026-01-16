#!/usr/bin/env python3
"""
SML Stromzähler Publisher für MQTT/Prometheus/Home Assistant

Liest Iskra SBZ17 Zähler via IR-Lesekopf und published Daten via MQTT.
"""

import time
import json
import signal
import sys
from smllib import SmlStreamReader
import serial
import paho.mqtt.client as mqtt

# Konfiguration via Kommandozeile oder Defaults
import argparse

parser = argparse.ArgumentParser(description='SML Stromzähler Publisher')
parser.add_argument('--name', default='light', help='Name des Zählers (z.B. light, heating)')
parser.add_argument('--port', default='/dev/ttyUSB0', help='Serial Port')
parser.add_argument('--baud', type=int, default=9600, help='Baudrate')
parser.add_argument('--interval', type=int, default=5, help='Polling Intervall in Sekunden')
args = parser.parse_args()

METER_NAME = args.name
SERIAL_PORT = args.port
SERIAL_BAUD = args.baud
MQTT_BROKER = 'localhost'
MQTT_PORT = 1883

# MQTT Topics (kompatibel mit mqttgateway für Prometheus)
MQTT_BASE_TOPIC = f'prometheus/job/meter/node/{METER_NAME}'
# Zusätzlich für Home Assistant (JSON payload)
MQTT_HA_TOPIC = f'home/meter/{METER_NAME}'

# Polling Intervall in Sekunden
POLL_INTERVAL = args.interval

OBIS_MAP = {
    "1-0:1.8.0*255": ("total_kwh", "kWh", "Gesamtverbrauch"),
    "1-0:2.8.0*255": ("total_export_kwh", "kWh", "Einspeisung"),
    "1-0:16.7.0*255": ("power_w", "W", "Aktuelle Leistung"),
    "1-0:36.7.0*255": ("power_l1_w", "W", "Leistung L1"),
    "1-0:56.7.0*255": ("power_l2_w", "W", "Leistung L2"),
    "1-0:76.7.0*255": ("power_l3_w", "W", "Leistung L3"),
}

running = True

def signal_handler(sig, frame):
    global running
    print("\nBeende...")
    running = False

def read_meter(ser):
    """Liest SML-Daten vom Zähler und gibt Dict mit Werten zurück."""
    stream = SmlStreamReader()
    
    # Buffer leeren und neue Daten lesen
    ser.reset_input_buffer()
    data = ser.read(3000)
    
    if not data:
        return None
        
    stream.add(data)
    results = {}
    
    while True:
        sml_frame = stream.get_frame()
        if not sml_frame:
            break
            
        try:
            parsed = sml_frame.parse_frame()
            for msg in parsed:
                if hasattr(msg, 'message_body') and hasattr(msg.message_body, 'val_list'):
                    for entry in msg.message_body.val_list:
                        obis = entry.obis.obis_code if hasattr(entry.obis, 'obis_code') else str(entry.obis)
                        
                        if obis not in OBIS_MAP:
                            continue
                            
                        value = entry.value
                        if value is None or not isinstance(value, (int, float)):
                            continue
                            
                        scaler = entry.scaler if hasattr(entry, 'scaler') and entry.scaler else 0
                        unit = entry.unit if hasattr(entry, 'unit') else None
                        
                        value = value * (10 ** scaler)
                        
                        # Wh zu kWh konvertieren für Zählerstände
                        if unit == 30:  # Wh
                            value = value / 1000
                            
                        metric_name, _, _ = OBIS_MAP[obis]
                        results[metric_name] = round(value, 3)
                        
        except Exception as e:
            print(f"Parse-Fehler: {e}")
            
    return results if results else None

def publish_metrics(client, metrics):
    """Published Metriken via MQTT."""
    timestamp = int(time.time())
    
    # Einzelne Topics für Prometheus/mqttgateway
    for metric_name, value in metrics.items():
        topic = f"{MQTT_BASE_TOPIC}/{metric_name}"
        client.publish(topic, str(value), retain=True)
        
    # JSON Payload für Home Assistant
    payload = {
        **metrics,
        "timestamp": timestamp,
    }
    client.publish(MQTT_HA_TOPIC, json.dumps(payload), retain=True)
    
    print(f"[{time.strftime('%H:%M:%S')}] Published: {metrics}")

def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print(f"Starte Stromzähler-Publisher [{METER_NAME}]...")
    print(f"Serial: {SERIAL_PORT} @ {SERIAL_BAUD}")
    print(f"MQTT: {MQTT_BROKER}:{MQTT_PORT} -> {MQTT_BASE_TOPIC}")
    print()
    
    # MQTT Client
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
    except Exception as e:
        print(f"MQTT Verbindungsfehler: {e}")
        sys.exit(1)
        
    # Serial Port
    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=5)
    except Exception as e:
        print(f"Serial Port Fehler: {e}")
        sys.exit(1)
        
    print("Verbunden. Lese Zähler...\n")
    
    while running:
        try:
            metrics = read_meter(ser)
            if metrics:
                publish_metrics(client, metrics)
            else:
                print(f"[{time.strftime('%H:%M:%S')}] Keine Daten empfangen")
                
        except Exception as e:
            print(f"Fehler: {e}")
            
        time.sleep(POLL_INTERVAL)
        
    ser.close()
    client.loop_stop()
    client.disconnect()
    print("Beendet.")

if __name__ == "__main__":
    main()
