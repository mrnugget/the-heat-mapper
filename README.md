# the-heat-mapper


## Raspberry Pi 4 - `blackbox`

This machine acts as the server and stores data and hosts services.

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

## Raspberry Pi Zero - `tinybox`

This RPi Zero acts as a "satellite".

It receives temperature/humidity signals via Bluetooth and forwards
to `blackbox`.

### Run

1. Copy the following three files over to `tinybox`:

- `devices.ini`
- `mqtt.ini`
- `temperature.service`

```bash
scp devices.ini pi@tinybox:/home/pi/devices.ini
scp mqtt.ini pi@tinybox:/home/pi/mqtt.ini
scp temperature.service pi@tinybox:/home/pi/temperature.service
```

Or clone them over

2. Install dependencies and enable bluetooth stuff:


```bash
sudo apt install tmux git python3 bluez python3-pip bluetooth libbluetooth-dev
sudo pip3 install bluepy requests pybluez paho-mqtt
sudo setcap cap_net_raw,cap_net_admin+eip $(eval readlink -f `which python3`)
```

3. Clone fork of `MiTemperature2`:

```bash
git clone git@github.com:mrnugget/MiTemperature2.git
cd MiTemperature2
git checkout mrn/simplify
```

Make sure it works:

```bash
sudo /home/pi/MiTemperature2/LYWSD03MMC.py --atc --devicelistfile /home/pi/devices.ini -odl --mqttconfigfile /home/pi/mqtt.ini
```

4. Enable service systemw-wide:

```bash
sudo cp temperature.service /etc/systemd/system/temperature.service
sudo systemctl daemon-reload
sudo systemctl enable temperature.service
sudo systemctl start temperature.service
sudo systemctl status temperature.service
```
