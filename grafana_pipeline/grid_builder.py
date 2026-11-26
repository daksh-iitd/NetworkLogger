"""
Rebuilds the coverage grid for the Live dashboard every 30 minutes.

Reads all raw samples once (30 s mean windows per InfluxDB series, computed
storage-side; a series is one phone/session with one band, PCI and signal class),
then bins them into cells for every grid size and operator in one pass and writes
median RSRP + window count to the short-retention bucket "grid_cache" (measurement
grid_rsrp, tags op/gridSize/cellLat/cellLon) — the exact schema the Live dashboard's
map panels look up.

This replaces an InfluxDB task (grid_task.flux, now removed): Flux re-ran the raw
scan for every grid size and for the median/count join (~8 scans, minutes of CPU),
and after the Mac slept the task scheduler fired all missed runs at once, starving
live writes. A plain loop scans once (a few seconds) and has no catch-up backlog.

Run it like the listener, in its own terminal or under nohup (on the lab server,
server/nl.sh runs it as the "grid" service):

    cd grafana_pipeline && ./venv/bin/python grid_builder.py
"""

import argparse
import math
import re
import time
from datetime import datetime, timezone
from statistics import median

from influxdb_client import BucketRetentionRules, InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from firestore_listener import find_token
from pull_and_load_influx import INFLUX_ORG, INFLUX_URL

SOURCE_BUCKET = "network_logs_v2"
CACHE_BUCKET = "grid_cache"
GRID_SIZES = [0.00025, 0.0005, 0.001, 0.002]   # degrees; must match the dashboard variable
EVERY_S = 30 * 60
CACHE_RETENTION_S = 72 * 3600
SERIES_TAGS = ("deviceId", "sessionId", "network", "signal", "pci", "screenOn", "band", "bandSource", "nrLegBand")
AIRTEL = re.compile("airtel", re.IGNORECASE)

BASE_QUERY = f'''from(bucket: "{SOURCE_BUCKET}")
  |> range(start: -180d)
  |> filter(fn: (r) => r._measurement == "network_log")
  |> filter(fn: (r) => r._field == "lat" or r._field == "lon" or r._field == "rsrp")
  |> aggregateWindow(every: 30s, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> filter(fn: (r) => exists r.lat and exists r.lon and exists r.rsrp)
  |> group()
  |> drop(columns: ["_start", "_stop", "_measurement"])'''


def now():
    return datetime.now().strftime("%H:%M:%S")


def cell_key(value, size):
    # centre of the cell, as a fixed-format string so re-runs hit the same series
    return f"{(math.floor(value / size) + 0.5) * size:.6f}"


def ensure_cache_bucket(client):
    buckets = client.buckets_api()
    if not buckets.find_bucket_by_name(CACHE_BUCKET):
        rules = BucketRetentionRules(type="expire", every_seconds=CACHE_RETENTION_S)
        buckets.create_bucket(bucket_name=CACHE_BUCKET, retention_rules=rules, org=INFLUX_ORG)
        print(f"[{now()}] created bucket '{CACHE_BUCKET}'", flush=True)


def rebuild(client):
    ensure_cache_bucket(client)
    cells = {}  # (op, size, cellLat, cellLon) -> list of rsrp
    seen = set()
    rows = 0
    for record in client.query_api().query_stream(BASE_QUERY, org=INFLUX_ORG):
        op = record.values.get("op") or "Unknown"
        if AIRTEL.search(op):
            op = "Airtel"
        # Rows stored as "airtel" were re-sent as "Airtel" after the rename, so the same
        # window exists under both op tags and must only count once
        window = (op, record["_time"], *(record.values.get(t) for t in SERIES_TAGS))
        if window in seen:
            continue
        seen.add(window)
        lat, lon, rsrp = record["lat"], record["lon"], record["rsrp"]
        rows += 1
        for size in GRID_SIZES:
            key = (op, f"{size:g}", cell_key(lat, size), cell_key(lon, size))
            cells.setdefault(key, []).append(rsrp)

    points = [
        Point("grid_rsrp")
        .tag("op", op).tag("gridSize", size).tag("cellLat", clat).tag("cellLon", clon)
        .field("rsrp", float(median(values))).field("samples", float(len(values)))
        .time(datetime.now(timezone.utc), WritePrecision.S)
        for (op, size, clat, clon), values in cells.items()
    ]
    write_api = client.write_api(write_options=SYNCHRONOUS)
    for i in range(0, len(points), 5000):
        write_api.write(bucket=CACHE_BUCKET, org=INFLUX_ORG, record=points[i:i + 5000])
    return rows, len(points)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--influx-url", default=INFLUX_URL)
    args = parser.parse_args()

    client = InfluxDBClient(url=args.influx_url, token=find_token(), org=INFLUX_ORG, timeout=120_000)
    print(f"[{now()}] grid builder: rebuilding '{CACHE_BUCKET}' every {EVERY_S // 60} min (Ctrl+C to stop)",
          flush=True)
    while True:
        started = time.monotonic()
        try:
            rows, n = rebuild(client)
            print(f"[{now()}] rebuilt {n} cells from {rows} windowed rows "
                  f"in {time.monotonic() - started:.0f}s", flush=True)
        except Exception as e:  # influxd busy or asleep: just try again next cycle
            print(f"[{now()}] rebuild failed: {e}", flush=True)
        time.sleep(EVERY_S)


if __name__ == "__main__":
    main()
