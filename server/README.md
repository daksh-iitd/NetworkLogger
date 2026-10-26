# NetworkLogger live pipeline on the lab server

Runs the same pipeline as the Mac (Firestore → `firestore_listener.py` → InfluxDB → Grafana)
on the lab server, without Docker or sudo. The Mac setup in `grafana_pipeline/` is not
changed; these scripts only read the listener, its loaders and the dashboard JSON from it.

```
/scratch/NetworkLoggerApp/
├── grafana_pipeline/      ← copied from the Mac (listener, loaders, dashboards, CSV mirror)
├── server/                ← these scripts
└── runtime/               ← created by setup.sh, private to your account (chmod 700)
    ├── influxdb/          InfluxDB 2.9.1 binary + data        127.0.0.1:8087
    ├── grafana/           Grafana 13.2.2 binary + data        port 3300, campus view-only
    ├── venv/              Python packages for the listener
    ├── secrets/           Firestore key, InfluxDB token, passwords
    ├── logs/              influxdb.log, grafana.log, listener.log, cron.log
    └── config.env         proxy and ports
```

InfluxDB listens on 127.0.0.1 only. Grafana listens on port 3300 on the network (port 3000 is
taken by someone else on this server), so people on the IITD network can open the dashboards
**view-only without logging in**; editing needs the `admin` login. To make Grafana private again
(SSH tunnel only), add `GRAFANA_BIND=127.0.0.1` to `runtime/config.env` and re-run `server/setup.sh`. Traffic to Google goes through the IITD proxy
(`proxy62.iitd.ac.in:3128`, taken from your login environment at setup).

## 1. Choose the Firestore key

The listener needs a service-account JSON key, copied to `runtime/secrets/firestore-key.json`
in step 2. The current deployment uses the project's `firebase-adminsdk` key from the repo
root. That key can change anything in the project, so on a shared server a read-only key is
safer — to switch later, copy the new key over the same file and run `server/nl.sh restart listener`:

1. console.cloud.google.com → project **android-telecom-monitoring** → **IAM & Admin → Service Accounts → Create service account**, name `grafana-listener`
2. Role: **Cloud Datastore Viewer** → Done
3. Open the account → **Keys → Add key → Create new key → JSON** → it downloads, e.g. `grafana-listener.json`

## 2. Copy the files to the server (from the Mac)

Replace `SERVER` with what you normally `ssh` to (e.g. `daksh@tejas.cse.iitd.ac.in`).

```bash
cd ~/Documents/MTP-1/Android-Telecom-Monitoring-App-main
rsync -av --exclude venv --exclude graph_env --exclude influx_data --exclude __pycache__ \
      grafana_pipeline server SERVER:/scratch/NetworkLoggerApp/
ssh SERVER 'mkdir -p -m 700 /scratch/NetworkLoggerApp/runtime/secrets'
scp android-telecom-monitoring-firebase-adminsdk-*.json \
    SERVER:/scratch/NetworkLoggerApp/runtime/secrets/firestore-key.json   # or the read-only key
```

## 3. Run the setup (on the server)

```bash
cd /scratch/NetworkLoggerApp
bash server/setup.sh
```

It downloads InfluxDB and Grafana (~250 MB, through the proxy), creates the Python venv,
generates passwords, creates the `networklogger` org and the `network_logs_v2` bucket
(180-day retention), starts all three services and installs a cron job that restarts
anything that stops (checked every 5 minutes and after a reboot). Re-running it is safe.

Optional — load the old Storage CSV sessions (copied with `grafana_pipeline/firebase_csv_mirror`):

```bash
server/nl.sh load-history
```

Files without session metadata (a few of the earliest uploads) are skipped and listed, since
their rows can't be dated and would fall outside the bucket's 180-day retention.

## 4. Open the dashboards

**Anyone on the IITD network** (campus or VPN), no login:
http://tejas.cse.iitd.ac.in:3300/d/networklogger-live and http://tejas.cse.iitd.ac.in:3300/d/networklogger-map.
Check first that the department firewall lets port 3300 through: from a campus machine,
`nc -vz tejas.cse.iitd.ac.in 3300` should say *succeeded*. If it doesn't, use the tunnel below.

**Through an SSH tunnel** (works from anywhere you can ssh from):

```bash
ssh -N -L 3300:127.0.0.1:3300 SERVER          # leave running
```

Then http://localhost:3300/d/networklogger-live (or `/d/networklogger-map`). User `admin`,
password from `cat /scratch/NetworkLoggerApp/runtime/secrets/grafana_admin_password` on the server.
Port 3300 doesn't clash with the Mac's own Grafana on 3000, so both can be open at once.

## Day to day (on the server)

| | |
|---|---|
| `server/nl.sh status` | Which services run + the listener's last lines |
| `server/nl.sh logs listener` | Follow the listener (a line per batch received); Ctrl+C to stop watching |
| `server/nl.sh restart listener` | After copying a new `firestore_listener.py` |
| `server/nl.sh stop` / `start` | Everything (cron will restart stopped services within 5 min — run `uninstall-cron` first to keep them stopped) |
| `server/nl.sh uninstall-cron` | Stop the automatic restarts |

To update after changing code or dashboards on the Mac: re-run the `rsync` from step 2, then
`server/nl.sh restart listener` (Grafana picks up dashboard JSON changes by itself within 30 s).

## If something fails

| Symptom | Look at |
|---|---|
| Setup stops at the proxy check | `echo $https_proxy` should be `http://proxy62.iitd.ac.in:3128`; edit `runtime/config.env` |
| `listener: exited at start` | `runtime/logs/listener.log` — `PermissionDenied` means the key lacks **Cloud Datastore Viewer**; `DeadlineExceeded`/`UNAVAILABLE` means gRPC can't get through the proxy |
| Grafana panels say the data source is missing | Grafana installs its InfluxDB plugin at first start through the proxy; check `runtime/grafana/logs/grafana.log` for `plugin` errors, then `server/nl.sh restart grafana` |
| Nothing new in the dashboard | `server/nl.sh status`; is a phone logging in **Production** mode? |

To remove everything: `server/nl.sh uninstall-cron && server/nl.sh stop && rm -rf /scratch/NetworkLoggerApp/runtime`
(Firestore keeps all data; nothing on the Mac is affected).
