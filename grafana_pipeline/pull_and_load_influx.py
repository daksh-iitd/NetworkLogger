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


def parse_session_date(session_id):
    # sessionId format: yyyyMMdd_HHmmss
    try:
        return datetime.strptime(session_id.split("_")[0], "%Y%m%d")
    except (ValueError, IndexError, AttributeError):
        return None


def reconstruct_datetimes(rows, session_date):
    """rows[i]['time'] is HH:MM:SS only; combine with session start date and
    handle midnight rollover, same logic used for the earlier gap analysis."""
    out = []
    day_offset = timedelta(0)
    prev_t = None
    for row in rows:
        t = datetime.strptime(row["time"], "%H:%M:%S").time()
        if prev_t is not None and t < prev_t and (
            datetime.combine(session_date, prev_t) - datetime.combine(session_date, t)
        ).total_seconds() > 3600:
            day_offset += timedelta(days=1)
        full = datetime.combine(session_date, t) + day_offset
        out.append(full)
        prev_t = t
    return out


def load_network_logs_csv(path, metadata, write_api):
    device_id = metadata.get("deviceId", "unknown")
    session_id = metadata.get("sessionId", "unknown")
    tester_name = metadata.get("testerName", "Unknown")
    device_model = metadata.get("deviceModel", "unknown")

    session_date = parse_session_date(session_id) or datetime(1970, 1, 1)

    with open(path, newline="") as f:
        lines = f.read().strip().split("\n")
    if len(lines) < 2:
        return 0
    header = lines[0].split(",")
    rows = [dict(zip(header, line.split(","))) for line in lines[1:]]
    timestamps = reconstruct_datetimes(rows, session_date)

    points = []
    for row, ts in zip(rows, timestamps):
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
            .time(ts, WritePrecision.S)
        )
        for field in ["lat", "lon", "rsrp", "rsrq", "sinr", "neighborCount", "dlKbps", "ulKbps"]:
            val = to_float(row.get(field))
            if val is not None:
                p = p.field(field, val)
        points.append(p)

    write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=points)
    return len(points)


def load_background_logs_csv(path, metadata, write_api):
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

    write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=points)
    return len(points)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--influx-token", required=True)
    args = parser.parse_args()

    print("Listing objects in Firebase Storage...")
    objects = list_all_objects()
    print(f"Found {len(objects)} files.")

    client = InfluxDBClient(url=INFLUX_URL, token=args.influx_token, org=INFLUX_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)

    total_points = 0
    for obj in objects:
        name = obj["name"]
        local_path = os.path.join(LOCAL_MIRROR_DIR, name)
        download_object(name, local_path)
        metadata = get_metadata(name)

        if name.endswith("network_logs.csv"):
            n = load_network_logs_csv(local_path, metadata, write_api)
            print(f"  {name}: {n} points -> network_log")
            total_points += n
        elif name.endswith("background_logs.csv"):
            n = load_background_logs_csv(local_path, metadata, write_api)
            print(f"  {name}: {n} points -> background_log")
            total_points += n

    print(f"\nDone. Wrote {total_points} total points to InfluxDB bucket '{INFLUX_BUCKET}'.")
    client.close()


if __name__ == "__main__":
    main()
