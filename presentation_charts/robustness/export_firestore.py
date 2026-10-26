"""
Exports the Firestore app data (sessions, 5 s samples, background rows, batch upload
times) to CSV files in robustness/data/, for the robustness charts. Read-only.

    ../grafana_pipeline/venv/bin/python robustness/export_firestore.py

Uses the *firebase-adminsdk*.json key in the repo root. Costs one Firestore read per
document (a few thousand per run).
"""

import csv
import glob
import os

from google.cloud import firestore

DATABASE_ID = "android-telecom-database"
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, "data")


def ms(value):
    """Firestore server timestamps arrive as datetimes; store everything as epoch ms."""
    return int(value.timestamp() * 1000) if hasattr(value, "timestamp") else value


def write(name, rows, fields):
    path = os.path.join(OUT, name)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  {name}: {len(rows)} rows")


def main():
    os.makedirs(OUT, exist_ok=True)
    key = sorted(glob.glob(os.path.join(REPO_ROOT, "*firebase-adminsdk*.json")))[0]
    db = firestore.Client.from_service_account_json(key, database=DATABASE_ID)

    sessions = []
    for doc in db.collection_group("sessions").stream():
        d = doc.to_dict()
        sessions.append({
            "sessionId": doc.id, "uid": doc.reference.parent.parent.id,
            "deviceId": d.get("deviceId"), "deviceModel": d.get("deviceModel"),
            "manufacturer": d.get("manufacturer"), "androidVersion": d.get("androidVersion"),
            "testerName": d.get("testerName"), "appVersionName": d.get("appVersionName"),
            "status": d.get("status"), "startedAtMs": d.get("startedAtMs"), "endedAtMs": d.get("endedAtMs"),
            "batchCount": d.get("batchCount"),
        })
    write("sessions.csv", sessions, list(sessions[0]))

    samples, batches = [], []
    for doc in db.collection_group("batches").stream():
        d = doc.to_dict()
        sid = doc.reference.parent.parent.id
        rows = d.get("rows", [])
        batches.append({"sessionId": sid, "seq": d.get("seq"), "rowCount": len(rows),
                        "firstTs": d.get("firstTs"), "lastTs": d.get("lastTs"),
                        "uploadedAtMs": ms(d.get("uploadedAt"))})
        for r in rows:
            samples.append({"sessionId": sid, "ts": r.get("ts"), "screenOn": r.get("screenOn"),
                            "network": r.get("network"), "rsrp": r.get("rsrp"),
                            "dlKbps": r.get("dlKbps"), "ulKbps": r.get("ulKbps")})
    write("batches.csv", batches, list(batches[0]))
    write("samples.csv", samples, list(samples[0]))

    background = []
    for doc in db.collection_group("background").stream():
        d = doc.to_dict()
        background.append({"sessionId": doc.reference.parent.parent.id, "ts": d.get("ts"),
                           "battery": d.get("battery"), "screenOn": d.get("screenOn"),
                           "networkType": d.get("networkType"), "uploadedAtMs": ms(d.get("uploadedAt"))})
    write("background.csv", background, list(background[0]))


if __name__ == "__main__":
    main()
