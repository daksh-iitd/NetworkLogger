#!/usr/bin/env bash
# Start/stop/check the server pipeline (InfluxDB, Grafana, Firestore listener).
#
#   server/nl.sh status                 what's running
#   server/nl.sh start|stop|restart [influxdb|grafana|listener]   (default: all)
#   server/nl.sh ensure                 start whatever isn't running (used by cron)
#   server/nl.sh logs <service>         follow a service's log
#   server/nl.sh load-history           load the old Storage CSVs (grafana_pipeline/firebase_csv_mirror)
#   server/nl.sh install-cron | uninstall-cron
set -uo pipefail

SERVER_DIR=$(cd "$(dirname "$0")" && pwd)
APP_DIR=$(dirname "$SERVER_DIR")
PIPELINE="$APP_DIR/grafana_pipeline"
RT="$APP_DIR/runtime"
SERVICES=(influxdb grafana listener)

[ -f "$RT/config.env" ] || { echo "Not set up yet — run server/setup.sh first" >&2; exit 1; }
# shellcheck disable=SC1091
source "$RT/config.env"
# Cron starts with an empty environment, so set the proxy here rather than relying on the login shell
export http_proxy="$PROXY" https_proxy="$PROXY" HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY"
export no_proxy="localhost,127.0.0.1,::1" NO_PROXY="localhost,127.0.0.1,::1"
export INFLUX_TOKEN
INFLUX_TOKEN=$(cat "$RT/secrets/influx_token")
INFLUX="http://127.0.0.1:$INFLUX_PORT"

stamp() { date '+%F %T'; }
pidfile() { echo "$RT/run/$1.pid"; }

is_running() {
  local pid
  pid=$(cat "$(pidfile "$1")" 2>/dev/null) || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  # Guard against a recycled pid belonging to something else
  case $1 in
    influxdb) grep -q influxd "/proc/$pid/cmdline" ;;
    grafana)  grep -q grafana "/proc/$pid/cmdline" ;;
    listener) grep -q firestore_listener "/proc/$pid/cmdline" ;;
  esac
}

wait_http() {  # url seconds
  for _ in $(seq "$2"); do curl -sf -o /dev/null "$1" && return 0; sleep 1; done
  return 1
}

launch() {  # name logfile command...
  local name=$1 log=$2; shift 2
  setsid nohup "$@" >> "$log" 2>&1 < /dev/null &
  echo $! > "$(pidfile "$name")"
}

start_one() {
  if is_running "$1"; then echo "$1: already running"; return 0; fi
  case $1 in
    influxdb)
      local influxd
      influxd=$(find "$RT/influxdb/dist" -type f -name influxd | head -1)
      launch influxdb "$RT/logs/influxdb.log" "$influxd" \
        --http-bind-address "127.0.0.1:$INFLUX_PORT" \
        --bolt-path "$RT/influxdb/data/influxdb.bolt" \
        --engine-path "$RT/influxdb/data/engine" \
        --sqlite-path "$RT/influxdb/data/influxd.sqlite" \
        --reporting-disabled --log-level warn
      wait_http "$INFLUX/health" 60 || { echo "influxdb: did not come up, see $RT/logs/influxdb.log"; return 1; }
      ;;
    grafana)
      is_running influxdb || start_one influxdb || return 1
      local bin home
      bin=$(find "$RT/grafana/dist" -type f -path '*/bin/grafana' | head -1)
      home=$(dirname "$(dirname "$bin")")
      launch grafana "$RT/logs/grafana.log" "$bin" server --homepath "$home" --config "$RT/grafana/custom.ini"
      wait_http "http://127.0.0.1:$GRAFANA_PORT/api/health" 120 \
        || { echo "grafana: did not come up, see $RT/logs/grafana.log and $RT/grafana/logs/"; return 1; }
      ;;
    listener)
      [ -f "$RT/secrets/firestore-key.json" ] || { echo "listener: no key at $RT/secrets/firestore-key.json"; return 1; }
      is_running influxdb || start_one influxdb || return 1
      launch listener "$RT/logs/listener.log" "$RT/venv/bin/python" -u "$PIPELINE/firestore_listener.py" \
        --key "$RT/secrets/firestore-key.json" --influx-url "$INFLUX"
      sleep 5
      is_running listener || { echo "listener: exited at start, see $RT/logs/listener.log"; tail -5 "$RT/logs/listener.log"; return 1; }
      ;;
  esac
  echo "$1: started (pid $(cat "$(pidfile "$1")"))"
}

stop_one() {
  if ! is_running "$1"; then echo "$1: not running"; rm -f "$(pidfile "$1")"; return 0; fi
  local pid
  pid=$(cat "$(pidfile "$1")")
  kill "$pid"
  for _ in $(seq 30); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
  kill -0 "$pid" 2>/dev/null && kill -9 "$pid"
  rm -f "$(pidfile "$1")"
  echo "$1: stopped"
}

targets() { if [ -n "${1:-}" ]; then echo "$1"; else echo "${SERVICES[@]}"; fi; }

cron_line_marker="# networklogger-watchdog"

case "${1:-status}" in
  status)
    for s in "${SERVICES[@]}"; do
      if is_running "$s"; then echo "$s: running (pid $(cat "$(pidfile "$s")"))"; else echo "$s: STOPPED"; fi
    done
    echo "listener last lines:"; tail -3 "$RT/logs/listener.log" 2>/dev/null | sed 's/^/  /'
    ;;
  start)   for s in $(targets "${2:-}"); do start_one "$s"; done ;;
  stop)    for s in $(targets "${2:-}"); do stop_one "$s"; done ;;
  restart) for s in $(targets "${2:-}"); do stop_one "$s"; start_one "$s"; done ;;
  ensure)
    # Quiet unless something had to be restarted, so the cron log stays small
    for s in "${SERVICES[@]}"; do
      [ "$s" = listener ] && [ ! -f "$RT/secrets/firestore-key.json" ] && continue
      is_running "$s" || { echo "[$(stamp)] $s was down, starting"; start_one "$s"; }
    done
    ;;
  logs)
    case "${2:-}" in
      influxdb|grafana|listener) tail -n 50 -f "$RT/logs/$2.log" ;;
      *) echo "usage: $0 logs influxdb|grafana|listener"; exit 1 ;;
    esac
    ;;
  load-history)
    "$RT/venv/bin/python" "$SERVER_DIR/load_history.py" --influx-url "$INFLUX" --mirror "$PIPELINE/firebase_csv_mirror"
    ;;
  install-cron)
    me="$SERVER_DIR/nl.sh"
    { crontab -l 2>/dev/null | grep -v "$cron_line_marker"
      echo "@reboot $me ensure >> $RT/logs/cron.log 2>&1 $cron_line_marker"
      echo "*/5 * * * * $me ensure >> $RT/logs/cron.log 2>&1 $cron_line_marker"
    } | crontab -
    echo "cron watchdog installed (every 5 min + at reboot):"; crontab -l | grep "$cron_line_marker"
    ;;
  uninstall-cron)
    crontab -l 2>/dev/null | grep -v "$cron_line_marker" | crontab -
    echo "cron watchdog removed"
    ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
