"""
Loads the old Firebase Storage CSV sessions into the server's InfluxDB.

Uses the loaders from grafana_pipeline/pull_and_load_influx.py unchanged (same
timestamp correction, de-duplication and cleaning as on the Mac); the only
difference is the InfluxDB address, which that script has fixed to localhost:8086.

    server/nl.sh load-history        (fills in --influx-url, --mirror and the token)
"""

import argparse
import os
import sys

from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.rest import ApiException

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "grafana_pipeline"))
from pull_and_load_influx import (INFLUX_ORG, iter_mirror, load_background_logs_csv,  # noqa: E402
                                  load_network_logs_csv)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--influx-url", required=True)
    parser.add_argument("--mirror", required=True, help="fetch_logs.py mirror directory")
    parser.add_argument("--bucket", default="network_logs_v2")
    args = parser.parse_args()

    if not os.path.isdir(os.path.join(args.mirror, "logs")):
        raise SystemExit(f"No mirror at {args.mirror} — copy grafana_pipeline/firebase_csv_mirror from the Mac")

    client = InfluxDBClient(url=args.influx_url, token=os.environ["INFLUX_TOKEN"], org=INFLUX_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)

    objects = iter_mirror(args.mirror)
    print(f"Found {len(objects)} files in {args.mirror}")
    total, skipped, seen = 0, [], set()
    for name, path, meta in objects:
        # A few of the earliest uploads have no metadata, so no session end to date their
        # HH:mm:ss rows from; they would land in 1970, which the bucket's retention rejects.
        if not meta.get("sessionId"):
            skipped.append(f"{name} (no session metadata, rows can't be dated)")
            continue
        try:
            if name.endswith("network_logs.csv"):
                total += load_network_logs_csv(path, meta, write_api, args.bucket, seen)
            elif name.endswith("background_logs.csv"):
                total += load_background_logs_csv(path, meta, write_api, args.bucket)
        except ApiException as e:
            # e.g. a partial write: points older than the retention period are dropped, the rest kept
            skipped.append(f"{name} (InfluxDB {e.status}: {(e.body or '')[:120]})")
    print(f"Done: {total} points written to '{args.bucket}'")
    if skipped:
        print(f"{len(skipped)} file(s) skipped or partly written:")
        for s in skipped:
            print("  " + s)
    client.close()


if __name__ == "__main__":
    main()
