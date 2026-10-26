#!/usr/bin/env bash
# One-time setup of the live pipeline on the lab server — no Docker, no sudo.
# Everything goes into <app dir>/runtime (next to server/ and grafana_pipeline/):
#   InfluxDB 2.9.1 on 127.0.0.1:8087, Grafana 13.2.2 on 127.0.0.1:3300,
#   firestore_listener.py in a Python venv, and a cron watchdog that keeps all three running.
#
#   bash server/setup.sh
#
# Safe to re-run: finished steps are skipped, existing data and passwords are kept.
set -euo pipefail

SERVER_DIR=$(cd "$(dirname "$0")" && pwd)
APP_DIR=$(dirname "$SERVER_DIR")
PIPELINE="$APP_DIR/grafana_pipeline"
RT="$APP_DIR/runtime"

INFLUX_VERSION=2.9.1
GRAFANA_VERSION=13.2.2
INFLUX_URL_DL="https://dl.influxdata.com/influxdb/releases/influxdb2-${INFLUX_VERSION}_linux_amd64.tar.gz"
GRAFANA_URL_DL="https://dl.grafana.com/oss/release/grafana-${GRAFANA_VERSION}.linux-amd64.tar.gz"
PROXY_DEFAULT="http://proxy62.iitd.ac.in:3128"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# ── 0. Checks ────────────────────────────────────────────────────────────────
say "Checking prerequisites"
[ -f "$PIPELINE/firestore_listener.py" ] || fail "$PIPELINE/firestore_listener.py not found — copy grafana_pipeline/ next to server/ first (see server/README.md)"
for cmd in python3 curl tar crontab; do command -v $cmd >/dev/null || fail "'$cmd' is not installed"; done
[ "$(uname -m)" = "x86_64" ] || fail "expected an x86_64 machine, got $(uname -m)"

mkdir -p "$RT"/{influxdb/data,grafana/data,grafana/logs,grafana/plugins,grafana/provisioning/datasources,grafana/provisioning/dashboards,secrets,logs,run,downloads}
chmod 700 "$RT" "$RT/secrets"

if [ ! -f "$RT/config.env" ]; then
  PROXY="${https_proxy:-${HTTPS_PROXY:-$PROXY_DEFAULT}}"
  cat > "$RT/config.env" <<EOF
# Read by server/nl.sh (also from cron, which has none of your login environment)
PROXY=$PROXY
INFLUX_PORT=8087
GRAFANA_PORT=3300
EOF
fi
# shellcheck disable=SC1091
source "$RT/config.env"
export http_proxy="$PROXY" https_proxy="$PROXY" HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY"
export no_proxy="localhost,127.0.0.1,::1" NO_PROXY="localhost,127.0.0.1,::1"

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 https://firestore.googleapis.com || true)
[ "$code" != "000" ] || fail "can't reach firestore.googleapis.com through $PROXY"
echo "Proxy $PROXY OK (Google answered $code)"

# ── 1. Downloads ─────────────────────────────────────────────────────────────
fetch() {  # url dest-dir
  local url=$1 dest=$2 file="$RT/downloads/$(basename "$1")"
  if [ -n "$(ls -A "$dest" 2>/dev/null)" ]; then echo "already unpacked: $dest"; return; fi
  if [ ! -f "$file" ]; then
    curl -fL --retry 3 -o "$file.part" "$url" || fail "download failed: $url"
    mv "$file.part" "$file"
  fi
  mkdir -p "$dest" && tar -xzf "$file" -C "$dest"
}
say "Downloading InfluxDB $INFLUX_VERSION and Grafana $GRAFANA_VERSION (skipped if present)"
fetch "$INFLUX_URL_DL" "$RT/influxdb/dist"
fetch "$GRAFANA_URL_DL" "$RT/grafana/dist"
INFLUXD=$(find "$RT/influxdb/dist" -type f -name influxd | head -1)
GRAFANA_BIN=$(find "$RT/grafana/dist" -type f -path '*/bin/grafana' | head -1)
[ -x "$INFLUXD" ] || fail "influxd binary not found in the InfluxDB download"
[ -x "$GRAFANA_BIN" ] || fail "grafana binary not found in the Grafana download"
echo "influxd: $INFLUXD"
echo "grafana: $GRAFANA_BIN"

# ── 2. Python environment ────────────────────────────────────────────────────
say "Python environment for the listener"
[ -x "$RT/venv/bin/python" ] || python3 -m venv "$RT/venv"
"$RT/venv/bin/pip" install -q --upgrade pip
"$RT/venv/bin/pip" install -q google-cloud-firestore influxdb-client requests
"$RT/venv/bin/python" -c "import google.cloud.firestore, influxdb_client" && echo "packages OK"

# ── 3. Secrets ───────────────────────────────────────────────────────────────
say "Passwords and tokens (kept if they already exist)"
gen() { [ -f "$RT/secrets/$1" ] || "$RT/venv/bin/python" -c "import secrets; print(secrets.token_urlsafe($2))" > "$RT/secrets/$1"; }
gen influx_token 48
gen influx_admin_password 18
gen grafana_admin_password 18
chmod 600 "$RT"/secrets/*

# ── 4. Grafana config ────────────────────────────────────────────────────────
say "Writing Grafana configuration"
# Grafana is reachable from the campus network (http://<server>:3300) and anyone who
# opens it can view the dashboards without logging in, read-only. To keep it private
# to SSH tunnels again, set GRAFANA_BIND=127.0.0.1 in runtime/config.env and re-run.
GRAFANA_BIND=${GRAFANA_BIND:-0.0.0.0}
cp "$RT/grafana/custom.ini" "$RT/grafana/custom.ini.prev" 2>/dev/null || true
cat > "$RT/grafana/custom.ini" <<EOF
[server]
http_addr = $GRAFANA_BIND
http_port = $GRAFANA_PORT

[auth.anonymous]
enabled = $([ "$GRAFANA_BIND" = 127.0.0.1 ] && echo false || echo true)
org_name = Main Org.
org_role = Viewer
hide_version = true

[paths]
data = $RT/grafana/data
logs = $RT/grafana/logs
plugins = $RT/grafana/plugins
provisioning = $RT/grafana/provisioning

[security]
admin_user = admin
admin_password = \$__file{$RT/secrets/grafana_admin_password}

[users]
allow_sign_up = false

[log]
mode = file

[analytics]
reporting_enabled = false
check_for_updates = false
check_for_plugin_updates = false
EOF

# Same uid as the Mac data source, so the dashboard JSON works unchanged
cat > "$RT/grafana/provisioning/datasources/influxdb.yaml" <<EOF
apiVersion: 1
datasources:
  - name: InfluxDB - NetworkLogger
    uid: P7C70A67DE99A08E6
    type: influxdb
    access: proxy
    url: http://127.0.0.1:$INFLUX_PORT
    isDefault: true
    jsonData:
      version: Flux
      organization: networklogger
      defaultBucket: network_logs_v2
    secureJsonData:
      token: \${INFLUX_TOKEN}
EOF

cat > "$RT/grafana/provisioning/dashboards/networklogger.yaml" <<EOF
apiVersion: 1
providers:
  - name: NetworkLogger
    orgId: 1
    folder: NetworkLogger
    type: file
    updateIntervalSeconds: 30
    options:
      path: $PIPELINE/dashboards
EOF

# ── 5. InfluxDB: start and create org/bucket/token on first run ──────────────
say "Starting InfluxDB"
"$SERVER_DIR/nl.sh" start influxdb
INFLUX="http://127.0.0.1:$INFLUX_PORT"
if curl -s "$INFLUX/api/v2/setup" | grep -q '"allowed": *true'; then
  say "First run: creating InfluxDB org 'networklogger' and bucket 'network_logs_v2' (180 days)"
  "$RT/venv/bin/python" - "$INFLUX" "$RT/secrets" <<'EOF'
import json, sys, urllib.request
url, secrets = sys.argv[1], sys.argv[2]
read = lambda name: open(f"{secrets}/{name}").read().strip()
body = {"username": "admin", "password": read("influx_admin_password"), "org": "networklogger",
        "bucket": "network_logs_v2", "retentionPeriodSeconds": 180 * 24 * 3600, "token": read("influx_token")}
req = urllib.request.Request(f"{url}/api/v2/setup", json.dumps(body).encode(), {"Content-Type": "application/json"})
urllib.request.urlopen(req)
print("InfluxDB initialised")
EOF
else
  echo "InfluxDB already initialised"
fi

# ── 6. Grafana + listener ────────────────────────────────────────────────────
if [ -f "$RT/grafana/custom.ini.prev" ] && ! cmp -s "$RT/grafana/custom.ini" "$RT/grafana/custom.ini.prev"; then
  say "Grafana configuration changed: restarting Grafana"
  "$SERVER_DIR/nl.sh" restart grafana
else
  say "Starting Grafana"
  "$SERVER_DIR/nl.sh" start grafana
fi
rm -f "$RT/grafana/custom.ini.prev"

if [ -f "$RT/secrets/firestore-key.json" ]; then
  say "Starting the Firestore listener"
  "$SERVER_DIR/nl.sh" start listener
else
  printf '\n\033[33mNo Firestore key yet: copy it to %s and run: server/nl.sh start listener\033[0m\n' "$RT/secrets/firestore-key.json"
fi

# ── 7. Cron watchdog ─────────────────────────────────────────────────────────
say "Installing cron watchdog (restarts anything that stopped, also after a reboot)"
"$SERVER_DIR/nl.sh" install-cron \
  || printf '\n\033[33mCould not install the cron job (cron may be disabled for your account); services still run, but won'"'"'t restart on their own.\033[0m\n'

say "Done"
"$SERVER_DIR/nl.sh" status
cat <<EOF

Open the dashboards from your Mac through an SSH tunnel:
  ssh -N -L $GRAFANA_PORT:127.0.0.1:$GRAFANA_PORT <you>@<server>
  then http://localhost:$GRAFANA_PORT/d/networklogger-live
EOF
if [ "$GRAFANA_BIND" != 127.0.0.1 ]; then
  cat <<EOF

Shareable on the campus network (view-only, no login), if the firewall allows port $GRAFANA_PORT:
  http://<server name>:$GRAFANA_PORT/d/networklogger-live
  http://<server name>:$GRAFANA_PORT/d/networklogger-map
Test from another machine on campus:  nc -vz <server name> $GRAFANA_PORT
EOF
fi
cat <<EOF

To edit dashboards, use Sign in (top right): user admin, password from
  cat $RT/secrets/grafana_admin_password
EOF
