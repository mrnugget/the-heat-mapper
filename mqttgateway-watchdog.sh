#!/usr/bin/env bash
set -euo pipefail

# Watchdog for the-heat-mapper mqttgateway.
#
# Failure mode it guards against: when the Mosquitto broker restarts or the
# connection drops, the mqttgateway container keeps running (so `restart: always`
# never triggers) but silently stops processing meter messages. The exported
# Prometheus values then freeze, which shows up as missing consumption in Grafana.
#
# Detection: the gateway exposes `mqtt_<metric>_last_pushed_timestamp` per series.
# Each meter in METER_NODES is checked separately. If one is older than MAX_AGE
# seconds (or missing), we check whether the broker still receives fresh messages
# for it. Only then is the gateway at fault, so we restart the container to make
# it re-subscribe. If the broker has nothing fresh either, the meter/publisher is
# the problem and a gateway restart would not help, so we only log it.

CONTAINER="the-heat-mapper_mqttgateway_1"
METRICS_URL="http://localhost:9337/metrics"
MAX_AGE="${MAX_AGE:-300}"   # seconds; meters publish every ~5s
METER_NODES="${METER_NODES:-light heating}"
LOG_PREFIX="[mqttgateway-watchdog]"

ts="$(date '+%Y-%m-%d %H:%M:%S')"

metrics="$(curl -sf --max-time 10 "$METRICS_URL" || true)"
if [[ -z "$metrics" ]]; then
  echo "$ts $LOG_PREFIX cannot scrape $METRICS_URL; restarting $CONTAINER"
  docker restart "$CONTAINER" >/dev/null
  exit 0
fi

now="$(date +%s)"
stale=()

for node in $METER_NODES; do
  # Last-pushed timestamp for this meter (0 if the series is missing).
  last="$(printf '%s\n' "$metrics" \
    | grep -E "^mqtt_total_kwh_last_pushed_timestamp\{job=\"meter\",node=\"${node}\"\}" \
    | awk '{printf "%d", $2+0}' || true)"
  age=$(( now - ${last:-0} ))
  (( age > MAX_AGE )) || continue

  # -R ignores the retained message, so this only succeeds on a fresh publish.
  if mosquitto_sub -h localhost -t "prometheus/job/meter/node/${node}/total_kwh" -R -C 1 -W 30 >/dev/null 2>&1; then
    stale+=("${node}(${age}s)")
  else
    echo "$ts $LOG_PREFIX ${node} stale (${age}s) but no fresh MQTT messages either; meter/publisher problem, not restarting"
  fi
done

if (( ${#stale[@]} > 0 )); then
  echo "$ts $LOG_PREFIX gateway stale for ${stale[*]} (> ${MAX_AGE}s) while broker has fresh data; restarting $CONTAINER"
  docker restart "$CONTAINER" >/dev/null
  echo "$ts $LOG_PREFIX restart issued"
fi
# Healthy: stay quiet to keep the log small (cron noise off).
