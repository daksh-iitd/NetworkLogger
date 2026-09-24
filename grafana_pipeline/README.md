# NetworkLogger -> InfluxDB -> Grafana pipeline

Local visualization setup: pulls session CSVs from Firebase Storage, loads
them into a local InfluxDB, and Grafana reads from InfluxDB.

## Services (installed via Homebrew)
- InfluxDB 2.x:  http://localhost:8086  (login: admin / networklogger123, org: networklogger)
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

## Dashboard
"NetworkLogger Overview" dashboard is provisioned automatically at:
  /opt/homebrew/etc/grafana/dashboards/network_logger.json
Data source config:
  /opt/homebrew/etc/grafana/conf/provisioning/datasources/influxdb.yaml (see actual path used during setup: /opt/homebrew/opt/grafana/share/grafana/conf/provisioning/)

Editing either file and restarting Grafana (`brew services restart grafana`)
picks up changes. Panels: RSRP over time, DL/UL throughput, battery %, and
signal-strength distribution — filterable by deviceId and testerName via
dashboard variables at the top.
