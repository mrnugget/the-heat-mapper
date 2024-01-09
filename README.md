# the-heat-mapper

Just a collection of stuff I need for collecting some temperature/humidity readings on a Raspberry Pi 4

## Raspberry Pi 4 - `blackbox`

On this machine:

- `prometheus`
- `grafana`
- `node-exporter`
- `mqttgateway`
- `unpoller`

### Run

1. Create `.env` file and fill with content of 1Password: https://start.1password.com/open/i?a=LVMZ2X55UFETRCHMOI7BONYOIM&v=ze3dzps36q2jt7zlvdduwhv3pi&i=7jyrhe5hiqglsbupu3btyeqgau&h=team-ball.1password.com

    ```
    UNIFI_USER=thorstenball
    UNIFI_PASS=<PW>
    UNIFI_URL=https://192.168.1.10:8443
    ```
2. Run: `docker-compose up -d`

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

### gomijia2

Config: `gomijia2.conf`

```
sudo cp gomijia2.service /etc/systemd/system/
sudo systemctl enable gomijia2
sudo systemctl start gomijia2
```

