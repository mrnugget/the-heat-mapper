#!/usr/bin/env python3
"""
SML-Stromzähler-Auslese-Skript für Iskra SBZ17
"""

from smllib import SmlStreamReader
import serial
import sys

OBIS_NAMES = {
    "1-0:96.50.1*1": "Hersteller",
    "1-0:96.1.0*255": "Zähler-ID",
    "1-0:1.8.0*255": "Bezug (kWh)",
    "1-0:1.8.1*255": "Bezug Tarif 1 (kWh)",
    "1-0:1.8.2*255": "Bezug Tarif 2 (kWh)",
    "1-0:2.8.0*255": "Einspeisung (kWh)",
    "1-0:16.7.0*255": "Aktuelle Leistung (W)",
    "1-0:36.7.0*255": "Leistung L1 (W)",
    "1-0:56.7.0*255": "Leistung L2 (W)",
    "1-0:76.7.0*255": "Leistung L3 (W)",
}

UNIT_NAMES = {
    30: "Wh",
    27: "W",
    33: "A",
    35: "V",
}

def read_meter(port='/dev/ttyUSB0', baud=9600):
    ser = serial.Serial(port, baud, timeout=5)
    stream = SmlStreamReader()
    
    # Lese genug Daten für ein komplettes Frame
    data = ser.read(3000)
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
                        value = entry.value
                        scaler = entry.scaler if hasattr(entry, 'scaler') and entry.scaler else 0
                        unit = entry.unit if hasattr(entry, 'unit') else None
                        
                        if value is not None and isinstance(value, (int, float)):
                            value = value * (10 ** scaler)
                            # Wh zu kWh konvertieren
                            if unit == 30:  # Wh
                                value = value / 1000
                                
                        results[obis] = {
                            'value': value,
                            'unit': UNIT_NAMES.get(unit, unit),
                            'name': OBIS_NAMES.get(obis, obis)
                        }
        except Exception as e:
            pass
    
    ser.close()
    return results

def main():
    print("=== Stromzähler Iskra SBZ17 ===\n")
    
    try:
        data = read_meter()
        
        for obis, info in sorted(data.items()):
            name = info['name']
            value = info['value']
            unit = info['unit'] or ''
            
            if isinstance(value, float):
                print(f"{name:30} {value:>12.3f} {unit}")
            else:
                print(f"{name:30} {value}")
                
    except serial.SerialException as e:
        print(f"Fehler beim Öffnen von /dev/ttyUSB0: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Fehler: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
