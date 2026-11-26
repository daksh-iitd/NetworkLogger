# NetworkLogger — context for Claude

M.Tech project (MTP), IIT Delhi. Android app that logs mobile-network quality (serving cell,
RSRP/RSRQ, band, GPS, throughput) every 5 s, plus a pipeline that turns the data into Grafana
dashboards and analysis charts. Current state and open items: @PROJECT_STATUS.md

## Repo map

| Path | What |
|---|---|
| `app/` | Kotlin Android app. Key files: `LoggingService.kt` (5 s loop, wake lock, resume), `CloudSync.kt` (Firestore batches), `NetworkWorker.kt` (15-min device health + watchdog), `SessionDiagnostics.kt` (exit reasons), `LogStorage.kt` (dev-mode CSVs), `BandInfo.kt`, `MainActivity.kt` |
| `firestore.rules` | Firestore security rules (published by hand in the Firebase console) |
| `grafana_pipeline/` | **Mac** pipeline: `firestore_listener.py` (live), `grid_builder.py` (Live map squares, `grid_cache` bucket), `fetch_logs.py` + `pull_and_load_influx.py` (old Storage CSVs), `dashboards/make_map_dashboard.py` → Map + Live dashboard JSON |
| `server/` | Same pipeline on the lab server (`setup.sh`, `nl.sh`, `load_history.py`) |
| `presentation_charts/` | Analysis charts; `robustness/` = when/why logging stopped |
| `apk/` | Built APKs (git-ignored). Share `NetworkLogger-public-*.apk` with testers |

## Data flow

Phone (production mode) → every 60 s a batch → **Firestore** → `firestore_listener.py` → InfluxDB
→ Grafana. Older app versions uploaded CSVs to **Firebase Storage** on Stop (still loadable).

- Firebase project `android-telecom-monitoring`. Firestore database is **named
  `android-telecom-database`** — not `(default)`; every client must pass it explicitly.
- Firestore layout: `users/{uid}/sessions/{deviceId}_{yyyyMMdd_HHmmss start}` (metadata, `status`
  active/ended/died, `restarts`, `events[]`) with subcollections `batches/{seq 000000…}` (`rows` =
  5 s samples, epoch-ms `ts`) and `background/{auto}`.
- InfluxDB org `networklogger`, bucket `network_logs_v2` (180-day retention), measurements
  `network_log` and `background_log`. Grafana data source uid `P7C70A67DE99A08E6`.
- Developer mode keeps CSVs on the phone (`Download/NetworkLogger/session_<start>/`), never uploaded.

## Environments

| Where | Details |
|---|---|
| Mac | InfluxDB `:8086` + Grafana `:3000` via Homebrew (`brew services`). InfluxDB data in `grafana_pipeline/influx_data/` (git-ignored). Listener runs by hand in a terminal |
| Lab server | `daksh@tejas.cse.iitd.ac.in` (hostname dellserver750), `/scratch/NetworkLoggerApp/{grafana_pipeline,server,runtime}`. No sudo, no Docker; outbound only via proxy `http://proxy62.iitd.ac.in:3128`. InfluxDB `127.0.0.1:8087`, Grafana `:3300` (port 3000 is someone else's), cron watchdog every 5 min |
| Dashboards (IITD network/VPN only) | http://tejas.cse.iitd.ac.in:3300/d/networklogger-live and `/d/networklogger-map`, view-only without login |

Python venvs: `grafana_pipeline/venv` (firestore, influxdb-client, storage; **no pandas**),
`presentation_charts/venv` (pandas, matplotlib, contextily). The Firebase admin key
`*firebase-adminsdk*.json` sits in the repo root (git-ignored); scripts find it by glob.

## Commands

```bash
# Build (Gradle needs Android Studio's JDK)
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
./gradlew :app:assembleInternalDebug :app:assemblePublicRelease :app:testInternalDebugUnitTest
# flavors: internal = dev-mode toggle; public = always production (for testers). Same applicationId.

# Mac live pipeline
cd grafana_pipeline && ./venv/bin/python firestore_listener.py

# Server (after ssh)
cd /scratch/NetworkLoggerApp && server/nl.sh status        # start|stop|restart|logs listener|load-history

# Robustness charts
cd presentation_charts && ../grafana_pipeline/venv/bin/python robustness/export_firestore.py \
  && ./venv/bin/python robustness/make_robustness_charts.py
```

## Conventions and preferences

- **Don't change the Mac's live pipeline files** (`grafana_pipeline/*.py`, Homebrew config) when
  working on something else; put new server/analysis code in its own folder and import from them.
- Commit/push only when asked. Work branch: `band-logging-dev-mode` (not merged to `main` yet).
  Never commit keys, `apk/`, venvs, `influx_data/`, `firebase_csv_mirror/` or `robustness/data/`.
- Charts follow the style in `presentation_charts/code/make_research_charts.py` (palette, title
  block via `finish()`); look at every PNG after generating.
- Ask before running commands against the server, Firebase writes, or `adb` on the user's phone;
  read-only Firestore queries are fine (free tier: 50k reads/day).
- The user prefers short, direct answers with the commands to run.

## Gotchas

- `./gradlew lint` reports ~70 pre-existing NewApi/permission errors; not a build blocker.
- CONTRIBUTING rule: catch `Throwable` (not `Exception`) around foreground-service calls.
- Throughput is passive and uses `TrafficStats.getTotal*` (all interfaces): Wi-Fi traffic currently
  inflates it (open item).
- Why a session died: session `events` (new app) or `adb shell dumpsys activity exit-info
  com.example.networklogger` (Android keeps ~16 entries). Google Play services updates
  (`stop com.google.android.gms due to installPackageLI`) kill the app.
- Old CSV rows only have `HH:mm:ss`; dates come from the Storage session id (= upload/end time).
