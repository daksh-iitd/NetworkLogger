"""
Downloads every session log from Firebase Storage into a local mirror, with each
file's upload metadata (tester, device model, Android/app version, session id)
saved next to it as <file>.meta.json.

The bucket's security rules no longer allow unauthenticated reads (the REST
listing in pull_and_load_influx.py now gets 403), so this uses an authenticated
Google Cloud client. Either:

  A) Service-account key (simplest):
     Firebase console → Project settings → Service accounts → Generate new private key
         ./venv/bin/python fetch_logs.py --key ~/Downloads/<key>.json

  B) Your own Google login via gcloud:
         gcloud auth application-default login
         ./venv/bin/python fetch_logs.py

Only new or changed files are downloaded (compared by the object's generation).

    ./venv/bin/pip install google-cloud-storage
"""

import argparse
import json
import os

from google.cloud import storage

BUCKET_NAME = "android-telecom-monitoring.firebasestorage.app"
PROJECT_ID = "android-telecom-monitoring"
DEFAULT_OUT = os.path.join(os.path.dirname(__file__), "firebase_csv_mirror")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", help="Path to a service-account JSON key (omit to use gcloud login)")
    parser.add_argument("--out-dir", default=DEFAULT_OUT)
    parser.add_argument("--prefix", default="logs/")
    args = parser.parse_args()

    client = (storage.Client.from_service_account_json(args.key) if args.key
              else storage.Client(project=PROJECT_ID))
    bucket = client.bucket(BUCKET_NAME)

    new, unchanged = 0, 0
    for blob in client.list_blobs(bucket, prefix=args.prefix):
        if blob.name.endswith("/"):
            continue
        local_path = os.path.join(args.out_dir, blob.name)
        meta_path = local_path + ".meta.json"

        if os.path.exists(meta_path):
            with open(meta_path) as f:
                if json.load(f).get("generation") == blob.generation:
                    unchanged += 1
                    continue

        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        blob.download_to_filename(local_path)
        with open(meta_path, "w") as f:
            json.dump({
                "name": blob.name,
                "generation": blob.generation,
                "size": blob.size,
                "updated": blob.updated.isoformat() if blob.updated else None,
                "metadata": blob.metadata or {},
            }, f, indent=2)
        new += 1
        print(f"  downloaded {blob.name}")

    print(f"\nDone: {new} new/changed file(s), {unchanged} already up to date → {args.out_dir}")


if __name__ == "__main__":
    main()
