# the-heat-mapper

## Architecture

```
┌─────────────────────┐
│  Bluetooth Sensors  │  (Xiaomi LYWSD03MMC with ATC firmware)
│  around the house   │
└─────────┬───────────┘
          │ Bluetooth LE advertisements
          ▼
┌─────────────────────┐
│  tinybox            │  Raspberry Pi Zero
│  ┌────────────────┐ │
│  │ LYWSD03MMC.py  │ │  Receives BLE, publishes to MQTT
│  │ (temperature   │ │
│  │  service)      │ │
│  └───────┬────────┘ │
└──────────┼──────────┘
           │ MQTT publish to blackbox:1883
           ▼
┌──────────────────────────────────────────────────┐
│  blackbox                      Raspberry Pi 4    │
│  ┌─────────────┐                                 │
│  │ mosquitto   │  MQTT broker (host service)     │
│  └──────┬──────┘                                 │
│         │ localhost:1883                         │
│         ▼                                        │
│  ┌─────────────┐                                 │
│  │ mqttgateway │  Subscribes to MQTT topics,     │
│  │ (container) │  exposes Prometheus metrics     │
│  └──────┬──────┘  on :9337                       │
│         │                                        │
│         ▼                                        │
│  ┌─────────────┐                                 │
│  │ prometheus  │  Scrapes mqttgateway:9337       │
│  │ (container) │  Stores time-series data        │
│  └──────┬──────┘                                 │
│         │                                        │
│         ▼                                        │
│  ┌─────────────┐                                 │
│  │ grafana     │  Visualizes data from           │
│  │ (container) │  Prometheus on :3000            │
│  └─────────────┘                                 │
└──────────────────────────────────────────────────┘
```

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

2. Install and run `mosquitto` (mqtt server):

    ```
    sudo apt install mosquitto mosquitto-clients
    ```

    See here for more details: https://pimylifeup.com/raspberry-pi-mosquitto-mqtt-server/

3. Edit mosquitto server:

    ```/etc/mosquitto/mosquitto.conf
    listener 1883
    allow_anonymous true
    ```

4. Restart mosquitto: `sudo systemctl restart mosquitto`

5. Run: `docker-compose up -d`


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

## Cheatsheet

Check whether `tinybox` sends data via mqtt to `blackbox`.

On `blackbox`, run:

```
$ mosquitto_sub -h localhost -t "#" -v 
prometheus/job/tinybox/node/livingroom/temperature 19.7
prometheus/job/tinybox/node/livingroom/humidity 23
prometheus/job/tinybox/node/livingroom/battery 21
prometheus/job/tinybox/node/livingroom {"temperature": 19.7, "humidity": 23, "voltage": 2.397, "calibratedHumidity": 23, "battery": 21, "timestamp": 1704807608, "sensor": "LivingRoom", "rssi": -69, "receiver": "tinybox"}
prometheus/job/tinybox/node/bathroom/temperature 20.3
prometheus/job/tinybox/node/bathroom/humidity 34
prometheus/job/tinybox/node/bathroom/battery 30
prometheus/job/tinybox/node/bathroom {"temperature": 20.3, "humidity": 34, "voltage": 2.478, "calibratedHumidity": 34, "battery": 30, "timestamp": 1704807609, "sensor": "Bathroom", "rssi": -82, "receiver": "tinybox"}
[...]
```

## Troubleshooting

If Grafana stops showing temperature data, debug each stage of the pipeline:

### 1. Check if tinybox is receiving Bluetooth data

On `tinybox`:

```bash
sudo journalctl -u temperature.service --since '10 minutes ago' --no-pager | tail -20
```

You should see lines like:
```
measurement. name=Kitchen, mac=A4:C1:38:54:F7:59, temperature=21.1, humidity=35, battery=79%, rssi=-57dbm
```

If no output: the Bluetooth service may need restarting:
```bash
sudo systemctl restart temperature.service
```

### 2. Check if MQTT messages arrive at blackbox

On `blackbox`:

```bash
mosquitto_sub -h localhost -t "#" -v
```

You should see messages flowing. If not, check mosquitto is running:
```bash
sudo systemctl status mosquitto
```

### 3. Check if mqttgateway is connected to the broker

On `blackbox`:

```bash
docker logs the-heat-mapper_mqttgateway_1 --tail 50
```

Look for errors like:
- `connection refused` - mqttgateway lost connection to mosquitto
- `Invalid topic: ... odd number of levels` - these warnings are normal for JSON summary messages

**Common fix**: If mqttgateway lost its MQTT connection, restart it:
```bash
docker restart the-heat-mapper_mqttgateway_1
```

### 4. Check if mqttgateway exposes metrics

On `blackbox`:

```bash
curl -s http://localhost:9337/metrics | grep temperature
```

You should see metrics like:
```
temperature{job="tinybox",node="kitchen"} 21.1
```

### 5. Check if Prometheus is scraping the data

On `blackbox`:

```bash
curl -s "http://localhost:9090/api/v1/query?query=temperature"
```

Or open http://blackbox:9090 in a browser and query `temperature`.

### Service status overview

Quick health check for all services on `blackbox`:

```bash
# Host service
sudo systemctl status mosquitto

# Docker containers
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "prometheus|grafana|mqttgateway"
```

On `tinybox`:

```bash
sudo systemctl status temperature.service
```

## Home Assistant Integration

The Pluggit ventilation system's outdoor temperature sensor is pushed from Home Assistant to Prometheus via MQTT. An automation in Home Assistant publishes `sensor.outdoor_t1` to `prometheus/job/pluggit/node/outdoor/temperature`, which `mqttgateway` picks up and exposes to Prometheus.

This allows the outdoor temperature to appear in Grafana alongside the Bluetooth temperature sensors.

## Electricity Meters (SML)

Two Iskra SBZ17 electricity meters are read via IR optical readers (Emlog USB) and published to MQTT.

### Architecture

```
┌─────────────────────┐
│  Iskra SBZ17        │  Electricity meters (Light + Heating)
│  Stromzähler        │
└─────────┬───────────┘
          │ Infrared (SML protocol, 9600 baud)
          ▼
┌─────────────────────┐
│  Emlog IR Lesekopf  │  USB optical reader
│  (per meter)        │
└─────────┬───────────┘
          │ /dev/serial/by-id/… (stable USB reader IDs)
          ▼
┌─────────────────────────────────────────────────┐
│  blackbox                                       │
│  ┌──────────────────┐                           │
│  │ meter_publisher  │  Python script (systemd)  │
│  │ (per meter)      │  Reads SML, publishes MQTT│
│  └────────┬─────────┘                           │
│           │ MQTT publish                        │
│           ▼                                     │
│  ┌─────────────┐                                │
│  │ mosquitto   │  → mqttgateway → prometheus    │
│  └─────────────┘                                │
└─────────────────────────────────────────────────┘
```

### Services

| Service | Port | Description |
|---------|------|-------------|
| `meter-light.service` | `/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_D20J9IXK-if00-port0` | Light (Licht) meter publisher |
| `meter-heating.service` | `/dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_DP05DBUI-if00-port0` | Heating (Heizung) meter publisher |

**Never assign meters by `/dev/ttyUSB0` or `/dev/ttyUSB1`: these numbers can swap
after a reboot.** The service files above are the source of truth for reader
assignments. The stable IDs identify the USB readers, not the meters: if a reader
is replaced or physically moved to another meter, verify and update the mapping.

### Recovery after the 2026-09-18 power cut

After reboot, both publishers were running but their readings were swapped.
The services were changed to the stable IDs above and installed in
`/etc/systemd/system/`. Both publishers were stopped before starting them with
the corrected assignments, so two processes would not read the same port.

At 19:20 CEST, live MQTT messages, Prometheus, and Home Assistant confirmed:

- Light: **30,034 kWh**, reader **D20J9IXK**.
- Heating: **21,527 kWh**, reader **DP05DBUI**.

These are historical reference readings, not fixed expected values. Incorrectly
labelled samples before the fix remain in history; consumption graphs using
`increase()` may show spikes while their time range includes the swap.

To verify after another reboot:

```bash
ls -l /dev/serial/by-id/
systemctl show meter-light.service meter-heating.service -p Id -p ExecStart -p ActiveState
# -R excludes retained messages: verify newly published readings.
timeout 30 mosquitto_sub -h localhost -t 'prometheus/job/meter/node/+/total_kwh' -R -v -C 4
curl -fsSG --data-urlencode 'query=total_kwh{exported_job="meter",node=~"light|heating"}' \
  http://localhost:9090/api/v1/query
```

Compare each labelled reading with its physical meter or known pre-reboot reading;
service uptime and fresh timestamps alone do not prove the assignments are right.

### MQTT Topics

```
prometheus/job/meter/node/light/total_kwh        # Zählerstand Licht (kWh)
prometheus/job/meter/node/light/total_export_kwh # Einspeisung Licht (kWh)
prometheus/job/meter/node/heating/total_kwh      # Zählerstand Heizung (kWh)
prometheus/job/meter/node/heating/total_export_kwh
home/meter/light                                  # JSON payload for HA
home/meter/heating
```

### Prometheus Queries

```promql
# Current meter reading
total_kwh{exported_job="meter", node="light"}

# Daily consumption
increase(total_kwh{exported_job="meter"}[1d])

# Weekly consumption per meter
increase(total_kwh{exported_job="meter", node="light"}[7d])
```

### Commands

```bash
# Check service status
sudo systemctl status meter-light.service
sudo systemctl status meter-heating.service

# View logs
sudo journalctl -u meter-light.service -f

# Test the light reader manually; never open a port already used by its service.
sudo systemctl stop meter-light.service
python3 /home/pi/the-heat-mapper/python/meter_publisher.py --name test --port /dev/serial/by-id/usb-FTDI_FT230X_Basic_UART_D20J9IXK-if00-port0
# After stopping the manual test with Ctrl-C:
sudo systemctl start meter-light.service

# Check MQTT messages
mosquitto_sub -h localhost -t "prometheus/job/meter/#" -v
```

### Installing or updating the meter services

Both readers are connected. If replacing one, identify its new stable ID and
update the corresponding service file and mapping above before installing.

```bash
# Inspect stable IDs, not USB enumeration order.
ls -l /dev/serial/by-id/

# Install both checked-in units, then reload systemd.
sudo cp /home/pi/the-heat-mapper/meter-{light,heating}.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable meter-light.service meter-heating.service
# Stop BOTH before starting either when changing assignments.
sudo systemctl stop meter-light.service meter-heating.service
sudo systemctl start meter-light.service meter-heating.service
```

### Grafana Dashboard

- **URL:** http://blackbox:3000/d/electricity-meter/stromzahler
- **File:** `grafana-dashboard-electricity.json`

### Files

| File | Purpose |
|------|---------|
| `python/meter_publisher.py` | SML reader + MQTT publisher script |
| `python/log_to_sheets.py` | Daily Google Sheets logger |
| `meter-light.service` | Systemd service for light meter |
| `meter-heating.service` | Systemd service for heating meter |
| `grafana-dashboard-electricity.json` | Grafana dashboard |
| `google-service-account-credentials.json` | Google API credentials (not in git) |

## Google Sheets Logging

Meter readings are logged daily to a Google Sheet for long-term tracking.

- **Sheet:** https://docs.google.com/spreadsheets/d/11dOsZuRz0wvbhkFWGGZpq0Qjoq0gwsnVDfRx5Wk75sw
- **Schedule:** Daily at 05:00 via cron
- **Script:** `python/log_to_sheets.py`

### Setup

1. Create a Google Cloud service account at https://console.cloud.google.com/apis/credentials
2. Enable the **Google Sheets API** in the project
3. Download the JSON key and save as `google-service-account-credentials.json`
4. Share the Google Sheet with the service account email (as Editor)

### Manual Run

```bash
~/the-heat-mapper/venv/bin/python ~/the-heat-mapper/python/log_to_sheets.py
```

### Cron Job

```
0 5 * * * /home/pi/the-heat-mapper/venv/bin/python /home/pi/the-heat-mapper/python/log_to_sheets.py >> /home/pi/the-heat-mapper/sheets.log 2>&1
```
