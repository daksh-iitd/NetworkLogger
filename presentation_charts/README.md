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
