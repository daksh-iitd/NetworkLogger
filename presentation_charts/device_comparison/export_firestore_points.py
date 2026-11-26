"""
Exports every 5 s sample from Firestore (current app version) with GPS, signal and cell
fields, plus the session's phone model, to device_comparison/data/firestore_points.csv.
Read-only; one Firestore read per document.

    ../grafana_pipeline/venv/bin/python device_comparison/export_firestore_points.py
"""

import csv
import glob
import os

from google.cloud import firestore

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
FIELDS = ["ts", "lat", "lon", "rsrp", "rsrq", "sinr", "dlKbps", "ulKbps", "network", "mcc", "mnc",
          "operator", "pci", "nci", "band", "screenOn"]


def main():
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    key = sorted(glob.glob(os.path.join(REPO_ROOT, "*firebase-adminsdk*.json")))[0]
    db = firestore.Client.from_service_account_json(key, database="android-telecom-database")

    sessions = {d.id: d.to_dict() for d in db.collection_group("sessions").stream()}
    out = os.path.join(HERE, "data", "firestore_points.csv")
    n = 0
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["deviceId", "model", "sessionId"] + FIELDS, extrasaction="ignore")
        w.writeheader()
        for doc in db.collection_group("batches").stream():
            sid = doc.reference.parent.parent.id
            meta = sessions.get(sid, {})
            for row in doc.to_dict().get("rows", []):
                w.writerow({"deviceId": meta.get("deviceId", sid.rsplit("_", 2)[0]),
                            "model": meta.get("deviceModel", "unknown"), "sessionId": sid, **row})
                n += 1
    print(f"{n} samples from {len(sessions)} sessions → {out}")


if __name__ == "__main__":
    main()
