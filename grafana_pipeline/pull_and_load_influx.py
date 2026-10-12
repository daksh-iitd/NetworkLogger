"""
Pulls CSV logs from the Firebase Storage bucket, parses them, and writes
points into a local InfluxDB 2.x instance for Grafana to visualize.

Usage:
    python pull_and_load_influx.py --influx-token <TOKEN>

Assumes InfluxDB 2.x is running locally on http://localhost:8086 with an
org "networklogger" and bucket "network_logs" already created (see setup
instructions).
"""

import argparse
import io
import json
import os
import re
import urllib.parse
from datetime import datetime, timedelta

import requests
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

BUCKET_NAME = "android-telecom-monitoring.firebasestorage.app"
STORAGE_BASE = f"https://firebasestorage.googleapis.com/v0/b/{BUCKET_NAME}/o"
LOCAL_MIRROR_DIR = os.path.join(os.path.dirname(__file__), "firebase_csv_mirror")

INFLUX_URL = "http://localhost:8086"
INFLUX_ORG = "networklogger"
INFLUX_BUCKET = "network_logs"


def list_all_objects(prefix="logs/"):
    """List every object under a prefix, paginating through nextPageToken."""
    objects = []
    page_token = None
    while True:
        params = {"prefix": prefix}
        if page_token:
            params["pageToken"] = page_token
        resp = requests.get(STORAGE_BASE, params=params)
        resp.raise_for_status()
        data = resp.json()
        objects.extend(data.get("items", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return objects


def download_object(object_name, local_path):
    """Download an object (raw CSV bytes) if not already present locally."""
    if os.path.exists(local_path):
        return
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    encoded = urllib.parse.quote(object_name, safe="")
    resp = requests.get(f"{STORAGE_BASE}/{encoded}", params={"alt": "media"})
    resp.raise_for_status()
    with open(local_path, "wb") as f:
        f.write(resp.content)


def get_metadata(object_name):
    encoded = urllib.parse.quote(object_name, safe="")
    resp = requests.get(f"{STORAGE_BASE}/{encoded}")
    resp.raise_for_status()
    return resp.json().get("metadata", {})


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_session_end(session_id):
    # sessionId format: yyyyMMdd_HHmmss, stamped at upload — i.e. when the session ended
    try:
        return datetime.strptime(session_id, "%Y%m%d_%H%M%S")
    except (ValueError, TypeError):
        return None


def reconstruct_datetimes(rows, session_end):
    """rows[i]['time'] is HH:MM:SS only. Anchor the last row on the upload date and
    walk backwards, stepping back a day whenever the clock jumps forward (a midnight
    crossing seen in reverse). Anchoring on the start instead shifts rows by a day."""
    out = []
    day = datetime.combine(session_end.date(), datetime.min.time())
    prev_t = None
    for row in reversed(rows):
        t = datetime.strptime(row["time"], "%H:%M:%S")
        tod = timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)
        if prev_t is None and day + tod > session_end + timedelta(minutes=5):
            day -= timedelta(days=1)
        elif prev_t is not None and tod > prev_t + timedelta(hours=1):
            day -= timedelta(days=1)
        out.append(day + tod)
        prev_t = tod
    return out[::-1]


# Android emulator default GPS fix (Google HQ) — test runs, not real positions
EMULATOR_FIX = (37.422, -122.084)
TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")


def operator_of(row):
    # Operator *names* vary by phone ("Jio True5G", "JIO 4G", "Vi India"...); the MCC/MNC don't
    mcc, mnc = row.get("mcc", ""), row.get("mnc", "")
    if mcc.startswith("405"):
        return "Jio"
    if mnc in ("11", "011"):
        return "Vi"
    name = (row.get("operator") or "").lower()
    if "jio" in name:
        return "Jio"
    if name.startswith("vi") or "vodafone" in name:
        return "Vi"
    return row.get("operator") or "Unknown"


def clean_fields(row):
    """Numeric fields worth writing, with known-bad readings removed (same rules as the charts)."""
    vals = {f: to_float(row.get(f)) for f in ["lat", "lon", "rsrp", "rsrq", "sinr", "neighborCount", "dlKbps",
                                              "ulKbps", "arfcn", "bandwidthMHz"]}
    rsrp, rsrq = vals["rsrp"], vals["rsrq"]
    # Int.MAX_VALUE / out-of-range, and the −44 dBm + −3 dB "no valid measurement" pair some modems report
    if rsrp is not None and (rsrp > -30 or rsrp < -150 or (rsrp == -44 and rsrq == -3)):
        vals["rsrp"] = vals["rsrq"] = None
    if vals["rsrq"] is not None and (vals["rsrq"] > 0 or vals["rsrq"] < -40):
        vals["rsrq"] = None
    lat, lon = vals["lat"], vals["lon"]
    if lat is not None and lon is not None and (
            lat == 0 or lon == 0 or (round(lat, 3), round(lon, 3)) == EMULATOR_FIX):
        vals["lat"] = vals["lon"] = None
    return {k: v for k, v in vals.items() if v is not None}


def load_network_logs_csv(path, metadata, write_api, bucket=INFLUX_BUCKET, seen=None):
    device_id = metadata.get("deviceId", "unknown")
    session_id = metadata.get("sessionId", "unknown")
    tester_name = metadata.get("testerName", "Unknown")
    device_model = metadata.get("deviceModel", "unknown")

    session_end = parse_session_end(session_id) or datetime(1970, 1, 1)

    with open(path, newline="") as f:
        # NUL bytes appear where a write was cut off (app force-stopped mid-write)
        lines = f.read().replace("\x00", "").strip().split("\n")
    if len(lines) < 2:
        return 0
    header = lines[0].split(",")
    rows = [dict(zip(header, line.split(","))) for line in lines[1:]]
    rows = [r for r in rows if TIME_RE.match(r.get("time", ""))]
    if not rows:
        return 0
    timestamps = reconstruct_datetimes(rows, session_end)

    points = []
    for row, ts in zip(rows, timestamps):
        # A run whose upload didn't finish is re-uploaded inside the next session's file;
        # with a different sessionId tag it would become a duplicate series, so keep the first.
        if seen is not None:
            key = (device_id, ts)
            if key in seen:
                continue
            seen.add(key)
        p = (
            Point("network_log")
            .tag("deviceId", device_id)
            .tag("sessionId", session_id)
            .tag("testerName", tester_name)
            .tag("deviceModel", device_model)
            .tag("network", row.get("network", "Unknown"))
            .tag("signal", row.get("signal", "Unknown"))
            .tag("operator", row.get("operator", "Unknown"))
            .tag("pci", row.get("pci", "N/A"))
            .tag("screenOn", row.get("screenOn", "N/A"))
            .tag("band", row.get("band", "N/A"))
            .tag("bandSource", row.get("bandSource", "N/A"))
            .tag("nrLegBand", row.get("nrLegBand", "N/A"))
            .tag("op", operator_of(row))
            .time(ts, WritePrecision.S)
        )
        fields = clean_fields(row)
        if not fields:
            continue
        for field, val in fields.items():
            p = p.field(field, val)
        points.append(p)

    write_api.write(bucket=bucket, org=INFLUX_ORG, record=points)
    return len(points)


def load_background_logs_csv(path, metadata, write_api, bucket=INFLUX_BUCKET):
    device_id = metadata.get("deviceId", "unknown")
    session_id = metadata.get("sessionId", "unknown")
    tester_name = metadata.get("testerName", "Unknown")
    device_model = metadata.get("deviceModel", "unknown")

    with open(path, newline="") as f:
        lines = f.read().strip().split("\n")
    if len(lines) < 2:
        return 0
    header = lines[0].split(",")
    rows = [dict(zip(header, line.split(","))) for line in lines[1:]]

    points = []
    for row in rows:
        try:
            ts = datetime.strptime(row["Time"], "%Y-%m-%d %H:%M:%S")
        except (ValueError, KeyError):
            continue
        p = (
            Point("background_log")
            .tag("deviceId", device_id)
            .tag("sessionId", session_id)
            .tag("testerName", tester_name)
            .tag("deviceModel", device_model)
            .tag("networkType", row.get("NetworkType", "Unknown"))
            .tag("operator", row.get("Operator", "Unknown"))
            .tag("cellId", row.get("CellID", "N/A"))
            .tag("screenOn", row.get("ScreenOn", "N/A"))
            .time(ts, WritePrecision.S)
        )
        for csv_field, influx_field in [
            ("Battery", "battery"), ("TotalStorage", "totalStorageGB"),
            ("UsedStorage", "usedStorageGB"), ("FreeStorage", "freeStorageGB"),
            ("TotalRAM", "totalRamGB"), ("UsedRAM", "usedRamGB"),
            ("AvailableRAM", "availableRamGB"),
        ]:
            val = to_float(row.get(csv_field))
            if val is not None:
                p = p.field(influx_field, val)
        points.append(p)

    write_api.write(bucket=bucket, org=INFLUX_ORG, record=points)
    return len(points)


def iter_mirror(mirror_dir):
    """(object name, local path, upload metadata) for every file in a fetch_logs.py mirror,
    oldest session first so the first upload of a re-uploaded run wins de-duplication."""
    found = []
    for root, _, files in os.walk(os.path.join(mirror_dir, "logs")):
        for fn in files:
            if fn.endswith(".csv"):
                path = os.path.join(root, fn)
                meta = {}
                if os.path.exists(path + ".meta.json"):
                    with open(path + ".meta.json") as f:
                        meta = json.load(f).get("metadata", {})
                found.append((os.path.relpath(path, mirror_dir), path, meta))
    return sorted(found, key=lambda x: x[0].split(os.sep)[-2])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--influx-token", required=True)
    parser.add_argument("--mirror", help="Load from a fetch_logs.py mirror directory instead of the public REST "
                                         "API (which now returns 403)")
    parser.add_argument("--bucket", default=INFLUX_BUCKET)
    args = parser.parse_args()

    if args.mirror:
        objects = iter_mirror(args.mirror)
        print(f"Found {len(objects)} files in mirror {args.mirror}.")
    else:
        print("Listing objects in Firebase Storage...")
        objects = []
        for obj in list_all_objects():
            local_path = os.path.join(LOCAL_MIRROR_DIR, obj["name"])
            download_object(obj["name"], local_path)
            objects.append((obj["name"], local_path, get_metadata(obj["name"])))
        print(f"Found {len(objects)} files.")

    client = InfluxDBClient(url=INFLUX_URL, token=args.influx_token, org=INFLUX_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)

    total_points, seen = 0, set()
    for name, local_path, metadata in objects:
        if name.endswith("network_logs.csv"):
            n = load_network_logs_csv(local_path, metadata, write_api, args.bucket, seen)
            print(f"  {name}: {n} points -> network_log")
            total_points += n
        elif name.endswith("background_logs.csv"):
            n = load_background_logs_csv(local_path, metadata, write_api, args.bucket)
            print(f"  {name}: {n} points -> background_log")
            total_points += n

    print(f"\nDone. Wrote {total_points} total points to InfluxDB bucket '{args.bucket}'.")
    client.close()


if __name__ == "__main__":
    main()
