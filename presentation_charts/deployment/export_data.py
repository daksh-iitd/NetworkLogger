"""
Exports what the deployment charts need, read-only:

- every 5 s sample since 8 Oct 2026 from the local InfluxDB (bucket network_logs_v2),
  one row per phone and timestamp (Airtel rows stored twice under two op tags count once)
- the Firestore session documents (status, restarts, events): one read per session

    ../grafana_pipeline/venv/bin/python deployment/export_data.py
"""

import csv
import datetime as dt
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO_ROOT, "grafana_pipeline"))

from google.cloud import firestore  # noqa: E402
from influxdb_client import InfluxDBClient  # noqa: E402

from firestore_listener import DATABASE_ID, find_token  # noqa: E402
from pull_and_load_influx import INFLUX_ORG, INFLUX_URL  # noqa: E402

OUT = os.path.join(HERE, "data")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
START = "2026-10-08T00:00:00+05:30"
FIELDS = ["lat", "lon", "rsrp", "rsrq"]
TAGS = ["deviceId", "deviceModel", "testerName", "op", "network", "screenOn", "sessionId"]

QUERY = f'''from(bucket: "network_logs_v2")
  |> range(start: {START})
  |> filter(fn: (r) => r._measurement == "network_log")
  |> filter(fn: (r) => {" or ".join(f'r._field == "{f}"' for f in FIELDS)})
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> group()
  |> keep(columns: ["_time", {", ".join(f'"{c}"' for c in TAGS + FIELDS)}])'''


def export_samples():
    client = InfluxDBClient(url=INFLUX_URL, token=find_token(), org=INFLUX_ORG, timeout=600_000)
    seen, n = set(), 0
    path = os.path.join(OUT, "samples.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_ms"] + TAGS + FIELDS)
        for r in client.query_api().query_stream(QUERY, org=INFLUX_ORG):
            ts = int(r["_time"].timestamp() * 1000)
            key = (r.values.get("deviceId"), ts)
            if key in seen:
                continue
            seen.add(key)
            w.writerow([ts] + [r.values.get(c) for c in TAGS] + [r.values.get(c) for c in FIELDS])
            n += 1
    print(f"  samples.csv: {n} rows")


HISTORY_QUERY = '''from(bucket: "network_logs_v2")
  |> range(start: 2026-08-01T00:00:00+05:30)
  |> filter(fn: (r) => r._measurement == "network_log" and r._field == "rsrp")
  |> group(columns: ["deviceId", "sessionId"])
  |> unique(column: "_time")
  |> aggregateWindow(every: 1d, fn: count, createEmpty: false, location: {zone: "Asia/Kolkata", offset: 0s})'''


def export_history():
    """Samples per day, split by app version: Firestore session ids start with the deviceId,
    the older Storage CSV sessions are a bare yyyyMMdd_HHmmss stamp."""
    client = InfluxDBClient(url=INFLUX_URL, token=find_token(), org=INFLUX_ORG, timeout=600_000)
    counts = {}
    for table in client.query_api().query(HISTORY_QUERY, org=INFLUX_ORG):
        for r in table.records:
            source = "firestore" if "_" in r.values["sessionId"].split("_", 1)[1] else "storage_csv"
            # aggregateWindow stamps each window with its end, so the day is the one before
            day = (r["_time"].astimezone(IST) - dt.timedelta(days=1)).date()
            k = (day, source, r.values["deviceId"])
            counts[k] = counts.get(k, 0) + r["_value"]
    with open(os.path.join(OUT, "daily_history.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["day", "source", "deviceId", "samples"])
        for (day, source, dev), n in sorted(counts.items()):
            w.writerow([day.isoformat(), source, dev, n])
    print(f"  daily_history.csv: {len(counts)} rows")


HOSTEL_BOX = (28.54825, 28.54915, 77.18313, 77.18400)   # Aravali Hostel, same box as the charts

HOSTEL_QUERY = f'''from(bucket: "network_logs_v2")
  |> range(start: 2026-08-01T00:00:00+05:30)
  |> filter(fn: (r) => r._measurement == "network_log")
  |> filter(fn: (r) => r._field == "lat" or r._field == "lon" or r._field == "rsrp")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> filter(fn: (r) => exists r.lat and exists r.lon and exists r.rsrp
      and r.lat >= {HOSTEL_BOX[0]} and r.lat <= {HOSTEL_BOX[1]} and r.lon >= {HOSTEL_BOX[2]} and r.lon <= {HOSTEL_BOX[3]})
  |> group()
  |> keep(columns: ["_time", "deviceId", "deviceModel", "op", "rsrp"])'''


def export_hostel_history():
    """Every sample inside Aravali Hostel since August, from both app versions."""
    client = InfluxDBClient(url=INFLUX_URL, token=find_token(), org=INFLUX_ORG, timeout=600_000)
    seen, n = set(), 0
    with open(os.path.join(OUT, "hostel_history.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_ms", "deviceId", "deviceModel", "op", "rsrp"])
        for r in client.query_api().query_stream(HOSTEL_QUERY, org=INFLUX_ORG):
            ts = int(r["_time"].timestamp() * 1000)
            if (r.values.get("deviceId"), ts) in seen:
                continue
            seen.add((r.values.get("deviceId"), ts))
            w.writerow([ts, r.values.get("deviceId"), r.values.get("deviceModel"), r.values.get("op"), r["rsrp"]])
            n += 1
    print(f"  hostel_history.csv: {n} rows")


RAM_QUERY = '''from(bucket: "network_logs_v2")
  |> range(start: 2026-10-01T00:00:00+05:30)
  |> filter(fn: (r) => r._measurement == "background_log")
  |> filter(fn: (r) => r._field == "availableRamGB" or r._field == "totalRamGB")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> group()
  |> keep(columns: ["_time", "deviceId", "deviceModel", "availableRamGB", "totalRamGB"])'''


def export_ram():
    """Free and total memory from the 15-minute device-health rows."""
    client = InfluxDBClient(url=INFLUX_URL, token=find_token(), org=INFLUX_ORG, timeout=600_000)
    n = 0
    with open(os.path.join(OUT, "ram.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_ms", "deviceId", "deviceModel", "availableRamGB", "totalRamGB"])
        for r in client.query_api().query_stream(RAM_QUERY, org=INFLUX_ORG):
            w.writerow([int(r["_time"].timestamp() * 1000), r.values.get("deviceId"), r.values.get("deviceModel"),
                        r.values.get("availableRamGB"), r.values.get("totalRamGB")])
            n += 1
    print(f"  ram.csv: {n} rows")


def export_sessions():
    key = sorted(glob.glob(os.path.join(REPO_ROOT, "*firebase-adminsdk*.json")))[0]
    db = firestore.Client.from_service_account_json(key, database=DATABASE_ID)
    sessions = []
    for doc in db.collection_group("sessions").stream():
        d = doc.to_dict()
        d.pop("startedAt", None), d.pop("endedAt", None)
        sessions.append(d | {"sessionId": doc.id})
    with open(os.path.join(OUT, "sessions.json"), "w") as f:
        json.dump(sessions, f, default=str)
    print(f"  sessions.json: {len(sessions)} sessions")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    export_samples()
    export_history()
    export_hostel_history()
    export_ram()
    if "--no-firestore" not in sys.argv:
        export_sessions()
