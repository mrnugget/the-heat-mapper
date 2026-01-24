# the-heat-mapper

Home monitoring stack on Raspberry Pi 4 (`blackbox`) that collects temperature, humidity, and electricity data into Prometheus/Grafana.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  DATA SOURCES                                                                   │
├─────────────────────────────────────────────────────────────────────────────────┤
│  Xiaomi LYWSD03MMC BLE sensors → tinybox (Pi Zero) → MQTT                       │
│  Iskra SBZ17 electricity meters → USB IR readers → meter_publisher.py → MQTT   │
│  Pluggit ventilation outdoor temp → Home Assistant automation → MQTT           │
│  UniFi network stats → unpoller container → Prometheus                         │
└─────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  PIPELINE (all on blackbox)                                                     │
│                                                                                 │
│  mosquitto:1883 (host) → mqttgateway:9337 → prometheus:9090 → grafana:3000     │
│                                                                                 │
│  node-exporter:9100  ──────────────────────┘                                   │
│  unpoller:9130       ──────────────────────┘                                   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Services Status Check

```bash
# Docker containers
docker ps --format "table {{.Names}}\t{{.Status}}"

# Host services
sudo systemctl status mosquitto meter-light.service meter-heating.service

# Quick MQTT check (see 5 temperature messages)
mosquitto_sub -h localhost -t "prometheus/job/tinybox/#" -v -C 5

# Check electricity meter MQTT
mosquitto_sub -h localhost -t "prometheus/job/meter/#" -v -C 5
```

## File Reference

| File | Purpose |
|------|---------|
| `docker-compose.yaml` | Docker stack: prometheus, grafana, mqttgateway, node-exporter, unpoller |
| `prometheus/prometheus.yml` | Scrape config for Prometheus |
| `devices.ini` | Bluetooth sensor MAC addresses → copied to tinybox |
| `mqtt.ini` | MQTT broker config → copied to tinybox |
| `python/meter_publisher.py` | Reads SML electricity meters via IR, publishes to MQTT |
| `python/log_to_sheets.py` | Daily Google Sheets logger for meter readings |
| `meter-light.service` | Systemd unit for light meter (installed to /etc/systemd/system/) |
| `meter-heating.service` | Systemd unit for heating meter |
| `temperature.service` | Systemd unit for tinybox (not used on blackbox) |
| `grafana-dashboard-*.json` | Exported Grafana dashboards |
| `google-service-account-credentials.json` | Google API creds (not in git) |
| `.env` | UniFi poller credentials (not in git) |

## Bluetooth Temperature Sensors

10 Xiaomi LYWSD03MMC sensors with ATC firmware. Defined in `devices.ini`:

| Room | MAC | MQTT Topic |
|------|-----|------------|
| Hallway | A4:C1:38:50:35:84 | prometheus/job/tinybox/node/hallway |
| Outside | A4:C1:38:F8:65:A1 | prometheus/job/tinybox/node/outside |
| Office | A4:C1:38:C4:3C:D0 | prometheus/job/tinybox/node/office |
| Kitchen | A4:C1:38:54:F7:59 | prometheus/job/tinybox/node/kitchen |
| Master Bedroom | A4:C1:38:98:E2:67 | prometheus/job/tinybox/node/masterbedroom |
| Kid1 | A4:C1:38:38:BF:2C | prometheus/job/tinybox/node/kid1 |
| Bathroom | A4:C1:38:D6:40:11 | prometheus/job/tinybox/node/bathroom |
| Kid2 | A4:C1:38:23:06:BF | prometheus/job/tinybox/node/kid2 |
| Machine Room | A4:C1:38:FA:E4:91 | prometheus/job/tinybox/node/machineroom |
| Living Room | A4:C1:38:B8:10:D7 | prometheus/job/tinybox/node/livingroom |

### Adding a New Sensor

1. Flash sensor with ATC firmware
2. Add to `devices.ini`:
   ```ini
   [A4:C1:38:XX:XX:XX]
   sensorname=NewRoom
   topic=prometheus/job/tinybox/node/newroom
   ```
3. Deploy to tinybox:
   ```bash
   scp devices.ini pi@tinybox:/home/pi/devices.ini
   ssh pi@tinybox 'sudo systemctl restart temperature.service'
   ```

## Electricity Meters

Two Iskra SBZ17 meters read via Emlog USB IR optical readers.

| Meter | Service | Port | MQTT Topic |
|-------|---------|------|------------|
| Light (Licht) | meter-light.service | /dev/ttyUSB0 | prometheus/job/meter/node/light/* |
| Heating (Heizung) | meter-heating.service | /dev/ttyUSB1 | prometheus/job/meter/node/heating/* |

**Metrics**: `total_kwh`, `total_export_kwh`, `power_w` (power requires PIN unlock from utility)

### Meter Publisher Script

`python/meter_publisher.py` - Uses smllib to parse SML protocol, publishes every 5s.

```bash
# Test manually
python3 python/meter_publisher.py --name test --port /dev/ttyUSB0

# View logs
sudo journalctl -u meter-light.service -f

# Restart
sudo systemctl restart meter-light.service meter-heating.service
```

### Installing Meter Service

```bash
sudo cp meter-light.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable meter-light.service
sudo systemctl start meter-light.service
```

## Google Sheets Logging

Daily meter readings logged to: https://docs.google.com/spreadsheets/d/11dOsZuRz0wvbhkFWGGZpq0Qjoq0gwsnVDfRx5Wk75sw

```bash
# Manual run
~/the-heat-mapper/venv/bin/python ~/the-heat-mapper/python/log_to_sheets.py

# Check cron
crontab -l | grep log_to_sheets

# View log
tail -20 sheets.log
```

**Cron** (05:00 daily): `0 5 * * * /home/pi/the-heat-mapper/venv/bin/python /home/pi/the-heat-mapper/python/log_to_sheets.py >> /home/pi/the-heat-mapper/sheets.log 2>&1`

## Docker Commands

```bash
# Start stack
docker-compose up -d

# View logs
docker-compose logs -f
docker logs the-heat-mapper_mqttgateway_1 --tail 50

# Restart a container
docker restart the-heat-mapper_mqttgateway_1

# Rebuild after docker-compose.yaml changes
docker-compose up -d --force-recreate
```

## Prometheus Queries

```promql
# Temperature by room
temperature{exported_job="tinybox"}

# Electricity meter reading
total_kwh{exported_job="meter", node="light"}

# Daily consumption
increase(total_kwh{exported_job="meter"}[1d])

# Humidity
humidity{exported_job="tinybox", node="bathroom"}
```

## URLs

| Service | URL |
|---------|-----|
| Grafana | http://blackbox:3000 |
| Prometheus | http://blackbox:9090 |
| mqttgateway metrics | http://blackbox:9337/metrics |

## Troubleshooting

### Temps not showing in Grafana

1. **Check tinybox**: `ssh pi@tinybox 'sudo journalctl -u temperature.service --since "10 min ago" | tail -20'`
2. **Check MQTT**: `mosquitto_sub -h localhost -t "prometheus/job/tinybox/#" -v`
3. **Check mqttgateway**: `docker logs the-heat-mapper_mqttgateway_1 --tail 50`
4. **Common fix**: `docker restart the-heat-mapper_mqttgateway_1`

### Meter not publishing

1. **Check USB**: `ls -la /dev/ttyUSB*`
2. **Check service**: `sudo systemctl status meter-light.service`
3. **Check logs**: `sudo journalctl -u meter-light.service --since "10 min ago"`
4. **Test manually**: `python3 python/meter_publisher.py --name test --port /dev/ttyUSB0`

### mqttgateway disconnected

The mqttgateway container connects to mosquitto via `host.docker.internal:1883`. If it loses connection:

```bash
docker restart the-heat-mapper_mqttgateway_1
```

## tinybox (Pi Zero) Reference

SSH: `ssh pi@tinybox`

Runs `temperature.service` which executes `/home/pi/MiTemperature2/LYWSD03MMC.py` to receive BLE advertisements and publish to MQTT.

```bash
# On tinybox
sudo systemctl status temperature.service
sudo journalctl -u temperature.service -f
sudo systemctl restart temperature.service
```

## Python Virtual Environment

```bash
# Activate
source ~/the-heat-mapper/venv/bin/activate

# Install new package
pip install <package>

# Dependencies for meter_publisher.py
pip install smllib paho-mqtt pyserial

# Dependencies for log_to_sheets.py
pip install gspread google-auth
```

## Related: Home Assistant

The Home Assistant config is at `~/homeassistantconfig/`. It has:
- Modbus sensors for Pluggit ventilation
- MQTT sensors for electricity meters
- Automation that pushes `sensor.outdoor_t1` to MQTT topic `prometheus/job/pluggit/node/outdoor/temperature`

See `~/homeassistantconfig/configuration.yaml` for sensor definitions.
