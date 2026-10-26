"""
Streams app sessions from Cloud Firestore into InfluxDB as they arrive, so Grafana
can show them live. Phones running the Firestore app version write one batch
document per minute (see CloudSync.kt); this keeps a listener open on every
`batches` and `background` collection and writes each new document straight away.

On start-up Firestore first delivers every existing document, so the full history
is (re)loaded too. Re-writing a point with the same tags and timestamp overwrites
it in InfluxDB, so restarting the listener never creates duplicates.

    ./venv/bin/python firestore_listener.py                    # key + token found automatically
    ./venv/bin/python firestore_listener.py --key <key>.json --influx-token <TOKEN>

The key is a service-account JSON (read access to Firestore is enough). If
--influx-token is omitted it is taken from $INFLUX_TOKEN, then from the influx CLI
config (~/.influxdbv2/configs, [default] profile).

    ./venv/bin/pip install google-cloud-firestore influxdb-client
"""

import argparse
import glob
import os
import threading
import time
import tomllib
from datetime import datetime

from google.cloud import firestore
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from pull_and_load_influx import INFLUX_ORG, INFLUX_URL, clean_fields, operator_of, to_float

DATABASE_ID = "android-telecom-database"
DEFAULT_BUCKET = "network_logs_v2"  # same bucket as the CSV history, so the map dashboard shows both
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BACKGROUND_FIELDS = ["battery", "totalStorageGB", "usedStorageGB", "freeStorageGB",
                     "totalRamGB", "usedRamGB", "availableRamGB"]


def tag(value, default="N/A"):
    return default if value is None or value == "" else str(value)


class SessionCache:
    """Session-document metadata (tester, device), fetched once per session."""

    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()

    def get(self, session_ref):
        with self._lock:
            if session_ref.path in self._cache:
                return self._cache[session_ref.path]
        snap = session_ref.get()
        if not snap.exists:
            # Batch arrived before its session doc; don't cache so the next batch retries.
            device_id = session_ref.id.rsplit("_", 2)[0]
            return {"deviceId": device_id, "sessionId": session_ref.id}
        meta = snap.to_dict() | {"sessionId": session_ref.id}
        with self._lock:
            self._cache[session_ref.path] = meta
        return meta


def batch_points(doc, meta):
    points = []
    for row in doc.to_dict().get("rows", []):
        ts = row.get("ts")
        if ts is None:
            continue
        fields = clean_fields(row)
        if not fields:
            continue
        p = (
            Point("network_log")
            .tag("deviceId", tag(meta.get("deviceId"), "unknown"))
            .tag("sessionId", meta["sessionId"])
            .tag("testerName", tag(meta.get("testerName"), "Unknown"))
            .tag("deviceModel", tag(meta.get("deviceModel"), "unknown"))
            .tag("network", tag(row.get("network"), "Unknown"))
            .tag("signal", tag(row.get("signal"), "Unknown"))
            .tag("operator", tag(row.get("operator"), "Unknown"))
            .tag("pci", tag(row.get("pci")))
            .tag("screenOn", tag(row.get("screenOn")))
            .tag("band", tag(row.get("band")))
            .tag("bandSource", tag(row.get("bandSource")))
            .tag("nrLegBand", tag(row.get("nrLegBand")))
            .tag("op", operator_of({k: tag(row.get(k), "") for k in ("mcc", "mnc", "operator")}))
            .time(int(ts), WritePrecision.MS)
        )
        for name, val in fields.items():
            p = p.field(name, val)
        points.append(p)
    return points


def background_point(doc, meta):
    row = doc.to_dict()
    if row.get("ts") is None:
        return None
    p = (
        Point("background_log")
        .tag("deviceId", tag(meta.get("deviceId"), "unknown"))
        .tag("sessionId", meta["sessionId"])
        .tag("testerName", tag(meta.get("testerName"), "Unknown"))
        .tag("deviceModel", tag(meta.get("deviceModel"), "unknown"))
        .tag("networkType", tag(row.get("networkType"), "Unknown"))
        .tag("operator", tag(row.get("operator"), "Unknown"))
        .tag("cellId", tag(row.get("cellId")))
        .tag("screenOn", tag(row.get("screenOn")))
        .time(int(row["ts"]), WritePrecision.MS)
    )
    has_field = False
    for name in BACKGROUND_FIELDS:
        val = to_float(row.get(name))
        if val is not None:
            p = p.field(name, val)
            has_field = True
    return p if has_field else None


def find_key():
    keys = sorted(glob.glob(os.path.join(REPO_ROOT, "*firebase-adminsdk*.json")))
    if not keys:
        raise SystemExit("No --key given and no *firebase-adminsdk*.json in the repo root")
    return keys[0]


def find_token():
    if os.environ.get("INFLUX_TOKEN"):
        return os.environ["INFLUX_TOKEN"]
    path = os.path.expanduser("~/.influxdbv2/configs")
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)["default"]["token"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        raise SystemExit("No --influx-token given, $INFLUX_TOKEN unset, and no token in " + path)


def now():
    return datetime.now().strftime("%H:%M:%S")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", help="Service-account JSON key (default: *firebase-adminsdk*.json in the repo root)")
    parser.add_argument("--influx-token")
    parser.add_argument("--influx-url", default=INFLUX_URL)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    args = parser.parse_args()

    db = firestore.Client.from_service_account_json(args.key or find_key(), database=DATABASE_ID)
    influx = InfluxDBClient(url=args.influx_url, token=args.influx_token or find_token(), org=INFLUX_ORG)
    write_api = influx.write_api(write_options=SYNCHRONOUS)
    sessions = SessionCache()
    initial = {"batches": True, "background": True}

    def handler(kind):
        def on_snapshot(_docs, changes, _read_time):
            points, latest = [], None
            for change in changes:
                if change.type.name == "REMOVED":
                    continue
                doc = change.document
                meta = sessions.get(doc.reference.parent.parent)
                if kind == "batches":
                    new = batch_points(doc, meta)
                    if new:
                        latest = (meta.get("deviceModel", "?"), meta.get("testerName", "?"), len(new))
                    points.extend(new)
                else:
                    p = background_point(doc, meta)
                    if p is not None:
                        points.append(p)
            if points:
                try:
                    write_api.write(bucket=args.bucket, org=INFLUX_ORG, record=points)
                except Exception as e:  # keep listening; the next restart re-sends everything
                    print(f"[{now()}] InfluxDB write failed: {e}", flush=True)
                    return
            if initial[kind]:
                initial[kind] = False
                print(f"[{now()}] {kind}: loaded {len(changes)} existing document(s), {len(points)} point(s)",
                      flush=True)
            elif kind == "batches" and latest:
                model, tester, n = latest
                print(f"[{now()}] new batch: {n} samples from {model} ({tester})", flush=True)
            elif points:
                print(f"[{now()}] new {kind} row(s): {len(points)}", flush=True)
        return on_snapshot

    def subscribe():
        return [db.collection_group(kind).on_snapshot(handler(kind)) for kind in ("batches", "background")]

    print(f"[{now()}] Listening to Firestore '{DATABASE_ID}' → InfluxDB bucket '{args.bucket}' (Ctrl+C to stop)",
          flush=True)
    watches = subscribe()
    try:
        while True:
            time.sleep(30)
            # A watch closes for good on non-retryable errors (e.g. network down too long);
            # re-subscribing replays everything, which InfluxDB de-duplicates.
            if not all(getattr(w, "is_active", True) for w in watches):
                print(f"[{now()}] Firestore listener dropped, reconnecting...", flush=True)
                for w in watches:
                    w.unsubscribe()
                watches = subscribe()
    except KeyboardInterrupt:
        pass
    finally:
        for w in watches:
            w.unsubscribe()
        influx.close()


if __name__ == "__main__":
    main()
