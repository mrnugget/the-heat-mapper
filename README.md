# the-heat-mapper

Just a collection of stuff I need for collecting some temperature/humidity readings on a Raspberry Pi 4

### `dht22.py`

Reads temp/humidity from DHT22 connected on pin = 12.

Requirements:

```
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install python3-pip
sudo python3 -m pip install --upgrade pip setuptools wheel
sudo pip3 install Adafruit_DHT
```

Run:

```
python3 dht22.py
```
