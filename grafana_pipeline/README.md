# NetworkLogger -> InfluxDB -> Grafana pipeline

Local visualization setup: pulls session CSVs from Firebase Storage, loads
them into a local InfluxDB, and Grafana reads from InfluxDB.

## Services (installed via Homebrew)
- InfluxDB 2.x:  http://localhost:8086  (org: networklogger; admin password is whatever was set at install — not stored here)
- Grafana:       http://localhost:3000  (login: admin / admin — change on first login)

Start/stop:
    brew services start influxdb@2
    brew services start grafana
    brew services stop influxdb@2
    brew services stop grafana

## Re-syncing new session data
Every time new sessions are uploaded to Firebase Storage, re-run:

    python3 -m venv venv          # first time only
    ./venv/bin/pip install influxdb-client requests   # first time only
    ./venv/bin/python pull_and_load_influx.py --influx-token <TOKEN>

The InfluxDB API token is in ~/.influxdbv2/configs under [default] -> token.
The script re-downloads any CSV not already present in ./firebase_csv_mirror/
and skips ones it already has, but it does NOT dedupe already-written InfluxDB
points — re-running after a session's CSV already changed (e.g. more rows
appended before upload) will insert duplicate points for the same timestamps
if the file changed and was re-downloaded. Safe to re-run for genuinely new
files; for now, delete the corresponding folder under firebase_csv_mirror/ if
you need to force a specific file to be re-pulled.

## Current workflow (bucket `network_logs_v2`, map dashboard)

The bucket's REST listing now returns 403, so fetch with the service-account key and load
from the local mirror instead:

    ./venv/bin/python fetch_logs.py --key <service-account-key>.json
    ./venv/bin/python pull_and_load_influx.py --influx-token <TOKEN> \
        --mirror firebase_csv_mirror --bucket network_logs_v2

Loading from the mirror also: corrects session timestamps (session ids are stamped at
upload, i.e. the session's end), skips rows re-uploaded in a later session, drops invalid
readings (Int.MAX_VALUE, the −44 dBm / −3 dB "no measurement" pair, emulator GPS), and tags
every point with `op` = Jio / Vi from the MCC/MNC. Re-running is safe; if a tag's meaning
changes, delete and recreate `network_logs_v2` first (tag changes create new series).

**NetworkLogger Map** dashboard — http://localhost:3000/d/networklogger-map — Geomap panels
for RSRP (Jio, Vi) and serving band, filterable by operator, band and device. It's generated
by `dashboards/make_map_dashboard.py`; after editing, re-run it and copy
`dashboards/network_logger_map.json` into `/opt/homebrew/etc/grafana/dashboards/`.

## Dashboard
"NetworkLogger Overview" dashboard is provisioned automatically at:
  /opt/homebrew/etc/grafana/dashboards/network_logger.json
Data source config:
  /opt/homebrew/etc/grafana/conf/provisioning/datasources/influxdb.yaml (see actual path used during setup: /opt/homebrew/opt/grafana/share/grafana/conf/provisioning/)

Editing either file and restarting Grafana (`brew services restart grafana`)
picks up changes. Panels: RSRP over time, DL/UL throughput, battery %, and
signal-strength distribution — filterable by deviceId and testerName via
dashboard variables at the top.
