# Presentation charts: map visualizations

Route/coverage maps generated from the local InfluxDB (see `../grafana_pipeline/`
for how log data gets from Firebase Storage into InfluxDB in the first place).

## Requirements

```bash
python3 -m venv venv
./venv/bin/pip install contextily matplotlib pandas requests
```

InfluxDB must be running locally (`brew services start influxdb@2`) with the
`network_logs` bucket already populated.

## Generating maps for a session

```bash
./venv/bin/python code/make_map_charts.py \
  --device-id <DEVICE_ID> --session-id <SESSION_ID> \
  --out-dir maps/<some_folder_name>
```

Produces 4 PNGs: route colored by elapsed time, route colored by RSRP,
route colored by network type (4G/5G), route colored by downlink throughput.

## How to find a session worth plotting

Most sessions are near-stationary (GPS jitter of a few meters). Don't just
rank by lat/lon bounding-box span — a single bad GPS fix can make a
stationary session look like it moved kilometers. Check the actual point
*distribution*, not just the min/max range:

```python
# For each (deviceId, sessionId) candidate:
med_lat, med_lon = df["lat"].median(), df["lon"].median()  # median, not mean -- robust to outliers
dist_m = haversine_distance(df.lat, df.lon, med_lat, med_lon)
# Genuine movement: most points are far from the median (no single dominant
# "home" cluster). A false positive (GPS glitch): median_dist is tiny (~1m)
# but max_dist is huge, with only 1-2 points that far out.
```

Sessions used so far:

| Folder | deviceId | sessionId | Points | Notes |
|---|---|---|---|---|
| `session1_7b1194d6bf7630cb_20260907_225448` | `7b1194d6bf7630cb` | `20260907_225448` | 1021 | Large ~10km journey, mixed 4G/5G, multiple repeated passes over ~4hrs |
| `session2_c176d0f3ae801a6d_20260902_092536` | `c176d0f3ae801a6d` | `20260902_092536` | 151 | Clean ~12min drive, pure 4G, clear signal dip mid-route |

## Research-question charts (whole dataset)

`code/make_research_charts.py` reads every session straight from the raw export
zip (no InfluxDB needed) and writes 7 charts to `research/`:

```bash
./venv/bin/pip install matplotlib pandas
./venv/bin/python code/make_research_charts.py --zip ../android-telecom-logs.zip --out-dir research
```

Things to know about the data before trusting a new chart:
- **62% of rows have `network=Unknown`** (phone-state permission denied on those
  devices). The script recovers the serving RAT from the cell data instead: only
  the app's NR branch writes a 36-bit NCI (> 255).
- **Sampling rate is uneven** (5 s up to several minutes). Anything aggregated by
  hour must thin samples first, or a single 5-second burst dominates that hour —
  this produced a fake "5G peaks late morning" pattern before thinning.
- **Throughput is passive** (TrafficStats counts all app traffic), so it measures
  usage, not capacity; it correlates *negatively* with RSRP. Don't chart it as a
  network-performance metric.
- `../network_logs-7.csv` is a duplicate of session `c176d0f3ae801a6d/20260903_151443`.

## Controlled Jio-vs-Vi experiment charts

`code/make_experiment_charts.py` analyses the scripted runs from
`../../Experiment/scripts/` (two OnePlus 11R phones side by side; per run: ndt7
download + upload, then a 300 s emulated video call). Reads the Firebase mirror:

```bash
./venv/bin/python code/make_experiment_charts.py --src ../grafana_pipeline/firebase_csv_mirror --out-dir experiment
```

- Rows are de-duplicated first: when the script force-stops the app before an upload
  finishes, that run is re-uploaded inside the next session's files.
- Runs are split on > 60 s gaps and paired by start time (the master script starts
  the phones 30 s apart). Only runs of 6–7 min within 50 m of the hostel table are
  used; the Sep 16 and Sep 17 runs were at two other locations and are excluded.
- Throughput is the app's 5-second traffic counter, so ndt7 peaks are approximate;
  the `ndt7_speedtest_*.txt` files on the measurement drive are the ground truth.
- `experiment/paired_runs.csv` holds the per-run numbers behind the charts.

## Campus band and cross-operator charts

`code/make_campus_charts.py` uses every GPS-tagged log; the band charts need the
band-logging app version (Oct 2026 onwards, columns `band`/`bandSource`):

```bash
./venv/bin/python code/make_campus_charts.py --src ../grafana_pipeline/firebase_csv_mirror --out-dir campus --since 2026-09-28
```

`--since` restricts every chart to recent data; older long stationary sessions otherwise
dominate per-sample statistics (e.g. Jio looked 71% weak overall vs 23% in the last two weeks).

- Bands are coloured by frequency range (low < 1 GHz, mid 1.8–2.1 GHz, high 2.3–3.5 GHz)
  so a colour means the same for both operators.
- Same-spot comparisons only use squares with ≥ 10 samples from each side.
- Cross-operator RSRP mixes Jio's 5G SS-RSRP with Vi's LTE RSRP and different phone
  models — treat gaps of a few dB as noise.

## Notes on basemap tile providers

`contextily` needs a tile provider to draw the street map underneath the
data. Two common ones will silently fail or get blocked:
- **OpenStreetMap.Mapnik**: blocked automated/scripted requests outright
  (their usage policy requires a proper client + reasonable request volume).
- **CartoDB.Positron**: now requires a paid API key; without one the tiles
  render as a large watermark instead of the actual map.

We use **`cx.providers.Esri.WorldGrayCanvas`**, which remains free for this
kind of use and gives a clean, muted basemap. If tiles ever come back broken
or watermarked again, that's the first thing to check — try a different
`cx.providers.Esri.*` option (e.g. `WorldStreetMap`, `WorldTopoMap`).

Esri's gray canvas also tops out around zoom level 16 -- for a very tight
session (a few hundred meters), contextily will warn that its inferred zoom
(17-18) isn't supported and will clamp down. The map still renders fine, just
slightly less zoomed-in than ideal for very short/tight sessions.
