#!/usr/bin/env python3

import Adafruit_DHT as dht_sensor
import time

def get_temperature_readings():
    humidity, temperature = dht_sensor.read_retry(dht_sensor.DHT22, 12)
    humidity = format(humidity, ".2f") + "%"
    temperature = format(temperature, ".2f") + "C"
    return {"temperature": temperature, "humidity": humidity}

while True:
    print(get_temperature_readings())
    time.sleep(30)
