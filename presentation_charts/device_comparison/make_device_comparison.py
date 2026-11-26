"""
Per-device signal statistics on and around the IIT Delhi campus, in 2-hour buckets.

Combines both data sources — the older Storage CSV uploads (via code/make_all_logs_map.load_points,
same timestamp reconstruction, de-duplication and cleaning as the other charts) and the
Firestore samples written by export_firestore_points.py — keeps samples whose GPS fix is
inside the IITD box, and computes n / mean / SD / median / min / max of RSRP (and RSRQ) per
phone, per 2-hour slot of the day (IST).

    ../grafana_pipeline/venv/bin/python device_comparison/export_firestore_points.py
    ./venv/bin/python device_comparison/make_device_comparison.py

Outputs (device_comparison/):
  tables/device_overall_stats.csv     one row per phone (all of its IITD samples)
  tables/device_slot_stats.csv        phone × 2-hour slot of the day (all days pooled)
  tables/device_window_stats.csv      phone × consecutive 2-hour window (date + slot)
  charts/01_rsrp_by_slot_heatmap.png  median RSRP per phone and slot
  charts/02_rsrp_by_device.png        RSRP distribution per phone
  charts/03_iitd_area.png             which samples count as "in/around IITD"
"""

import os
import sys

import contextily as cx
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "code"))
from make_all_logs_map import DELHI, EMULATOR_FIX, RSRP_COLORS, RSRP_EDGES, to_mercator  # noqa: E402
from make_research_charts import (CONTEXT, INK_PRIMARY, INK_SECONDARY, SURFACE,  # noqa: E402
                                  apply_style, finish, load_sessions)

MIRROR = os.path.join(os.path.dirname(os.path.dirname(HERE)), "grafana_pipeline", "firebase_csv_mirror")
FIRESTORE_CSV = os.path.join(HERE, "data", "firestore_points.csv")
OUT_CHARTS, OUT_TABLES = os.path.join(HERE, "charts"), os.path.join(HERE, "tables")

# IIT Delhi (Hauz Khas) campus with a ~150 m margin: hostels in the west, academic area in the east
IITD = dict(lat=(28.5380, 28.5515), lon=(77.1795, 77.2015))
SLOT_H = 2
MIN_SAMPLES = 60          # 5 minutes of 5 s samples; fewer are left out of the charts (kept in tables)
# Operator colours: Jio and Vi as in the existing charts; Airtel takes the third palette slot
OP_COLORS = {"Jio": "#2a78d6", "Vi": "#eb6834", "Airtel": "#1baf7a"}
OPERATORS = list(OP_COLORS)

NAMES = {"SM-M325F": "Samsung Galaxy M32", "SM-A346E": "Samsung Galaxy A34 5G",
         "SM-S908E": "Samsung Galaxy S22 Ultra", "moto g35 5G": "Moto g35 5G",
         "motorola edge 50 neo": "Motorola Edge 50 Neo", "moto e13": "Moto e13",
         "CPH2487": "OnePlus 11R", "OnePlus8Pro": "OnePlus 8 Pro", "A001": "Nothing A001",
         "X6525": "Infinix X6525", "Infinix X6525": "Infinix X6525",
         "SM-S721B": "Samsung Galaxy S24 FE", "SM-S921B": "Samsung Galaxy S24",
         "RMX3842": "Realme RMX3842", "V2518": "vivo V2518"}


# ── Data ─────────────────────────────────────────────────────────────────────

def operator(mcc, mnc, name=""):
    # Delhi codes: Jio 405-8xx, Vi 404-11, Airtel 404-10 (Airtel phones elsewhere report e.g. 404-93)
    mcc, mnc = str(mcc).split(".")[0], str(mnc).split(".")[0]
    if mcc.startswith("405"):
        return "Jio"
    if mnc in ("11", "011"):
        return "Vi"
    if mnc == "10" or "airtel" in str(name).lower():
        return "Airtel"
    return "Other"


def load_old():
    """Storage CSVs, prepared like make_all_logs_map.load_points but keeping Airtel too."""
    df = load_sessions(MIRROR)          # IST wall-clock timestamps, cleaned readings
    df = df.sort_values("session").drop_duplicates(subset=["device", "ts"]).dropna(subset=["lat", "lon"])
    df = df[~((df.lat.round(3) == round(EMULATOR_FIX[0], 3)) & (df.lon.round(3) == round(EMULATOR_FIX[1], 3)))]
    df = df[df.lat.between(*DELHI["lat"]) & df.lon.between(*DELHI["lon"])]
    df["op"] = [operator(a, b, c) for a, b, c in zip(df.mcc, df.mnc, df.operator)]
    df["source"] = "storage"
    return df


def load_firestore():
    fs = pd.read_csv(FIRESTORE_CSV, low_memory=False)
    fs["ts"] = pd.to_datetime(fs.ts, unit="ms", utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    for c in ["lat", "lon", "rsrp", "rsrq", "nci", "dlKbps"]:
        fs[c] = pd.to_numeric(fs[c], errors="coerce")
    # Same cleaning rules as make_research_charts.load_sessions
    fs.loc[(fs.lat == 0) | (fs.lon == 0), ["lat", "lon"]] = np.nan
    fs.loc[(fs.rsrp > -30) | (fs.rsrp < -150), "rsrp"] = np.nan
    fs.loc[(fs.rsrp == -44) & (fs.rsrq == -3), ["rsrp", "rsrq"]] = np.nan
    fs.loc[(fs.rsrq > 0) | (fs.rsrq < -40), "rsrq"] = np.nan
    fs = fs[~((fs.lat.round(3) == round(EMULATOR_FIX[0], 3)) & (fs.lon.round(3) == round(EMULATOR_FIX[1], 3)))]
    fs["op"] = [operator(a, b, c) for a, b, c in zip(fs.mcc, fs.mnc, fs.operator)]
    fs["cell_rat"] = np.where(fs.nci > 255, "NR", np.where(fs.nci.notna(), "LTE", "?"))
    fs = fs.rename(columns={"deviceId": "device"})
    fs["source"] = "firestore"
    return fs


def load_all():
    old = load_old()
    fs = load_firestore()
    cols = ["device", "model", "ts", "lat", "lon", "rsrp", "rsrq", "op", "cell_rat", "source"]
    df = pd.concat([old[cols], fs[cols]], ignore_index=True)
    df = df[df.op.isin(OPERATORS)].dropna(subset=["ts", "lat", "lon"])
    # A phone's data can't be in both sources at the same second; drop exact repeats anyway
    df = df.assign(_s=df.ts.dt.floor("s")).drop_duplicates(subset=["device", "_s"]).drop(columns="_s")
    df["iitd"] = df.lat.between(*IITD["lat"]) & df.lon.between(*IITD["lon"])
    # One label per phone and operator (the two OnePlus 11R units ran Jio and Vi)
    df["model"] = df.groupby("device").model.transform(lambda s: s[s.ne("unknown")].mode().iat[0]
                                                        if s.ne("unknown").any() else "unknown")
    df["name"] = df.model.map(lambda m: NAMES.get(m, f"Xiaomi {m}" if m[:2] in ("22", "23", "25") else m))
    df["phone"] = df.name + " · " + df.op
    df["slot"] = (df.ts.dt.hour // SLOT_H) * SLOT_H
    return df


# ── Tables ───────────────────────────────────────────────────────────────────

def stats(g, metric):
    v = g[metric].dropna()
    return pd.Series({
        "n": len(v), "hours": round(len(v) * 5 / 3600, 1),
        "mean": round(v.mean(), 1) if len(v) else np.nan, "sd": round(v.std(), 1) if len(v) > 1 else np.nan,
        "median": v.median() if len(v) else np.nan, "min": v.min() if len(v) else np.nan,
        "max": v.max() if len(v) else np.nan,
    })


def tables(d):
    os.makedirs(OUT_TABLES, exist_ok=True)
    out = {}
    for metric in ["rsrp", "rsrq"]:
        overall = d.groupby(["phone", "op"]).apply(stats, metric, include_groups=False).reset_index()
        overall["first_day"] = overall.phone.map(d.groupby("phone").ts.min().dt.strftime("%d %b"))
        overall["last_day"] = overall.phone.map(d.groupby("phone").ts.max().dt.strftime("%d %b"))
        overall["days"] = overall.phone.map(d.groupby("phone").ts.apply(lambda t: t.dt.date.nunique()))
        overall["pct_5g_sa"] = overall.phone.map((d.cell_rat == "NR").groupby(d.phone).mean().mul(100).round(0))
        by_slot = d.groupby(["phone", "op", "slot"]).apply(stats, metric, include_groups=False).reset_index()
        by_slot.insert(2, "slot_ist", by_slot.slot.map(lambda h: f"{h:02d}:00–{h + SLOT_H:02d}:00"))
        win = d.assign(date=d.ts.dt.date).groupby(["phone", "op", "date", "slot"]) \
            .apply(stats, metric, include_groups=False).reset_index()
        for name, t in [("overall", overall), ("slot", by_slot), ("window", win)]:
            t.insert(0, "metric", metric)
            out.setdefault(name, []).append(t)
    for name, parts in out.items():
        path = os.path.join(OUT_TABLES, f"device_{name}_stats.csv")
        pd.concat(parts).to_csv(path, index=False)
        print(f"  wrote tables/{os.path.basename(path)}")
    return pd.concat(out["overall"]), pd.concat(out["slot"])


# ── Charts ───────────────────────────────────────────────────────────────────

def phone_order(overall):
    o = overall[(overall.metric == "rsrp") & (overall.n >= MIN_SAMPLES)]
    o = o.assign(k=o.op.map(OPERATORS.index))
    return o.sort_values(["k", "median"], ascending=[True, False]).phone.tolist()


def chart_heatmap(slot, order, d):
    s = slot[(slot.metric == "rsrp")].set_index(["phone", "slot"])
    slots = list(range(0, 24, SLOT_H))
    fig, ax = plt.subplots(figsize=(13, 0.52 * len(order) + 2.2))
    cmap, norm = mcolors.ListedColormap(RSRP_COLORS), mcolors.BoundaryNorm(RSRP_EDGES, len(RSRP_COLORS))
    for i, ph in enumerate(order):
        for j, h in enumerate(slots):
            row = s.loc[(ph, h)] if (ph, h) in s.index else None
            if row is None or row.n < MIN_SAMPLES:
                ax.add_patch(plt.Rectangle((j, i), 1, 1, color="#f0efec", ec=SURFACE, lw=2))
                continue
            color = cmap(norm(row["median"]))
            ax.add_patch(plt.Rectangle((j, i), 1, 1, color=color, ec=SURFACE, lw=2))
            dark = row["median"] < -110 or row["median"] >= -80
            ax.text(j + 0.5, i + 0.42, f"{row['median']:.0f}", ha="center", va="center", fontsize=10,
                    fontweight="bold", color="white" if dark else INK_PRIMARY)
            ax.text(j + 0.5, i + 0.75, f"±{row['sd']:.0f}", ha="center", va="center", fontsize=7.5,
                    color="white" if dark else INK_SECONDARY)
    ax.set_xlim(0, len(slots))
    ax.set_ylim(len(order), 0)
    ax.set_xticks([j + 0.5 for j in range(len(slots))], [f"{h:02d}–{h + SLOT_H:02d}" for h in slots], fontsize=10)
    ax.set_yticks([i + 0.5 for i in range(len(order))], order, fontsize=10)
    for lbl in ax.get_yticklabels():
        lbl.set_color(OP_COLORS[lbl.get_text().rsplit(" · ", 1)[1]])
    ax.tick_params(length=0)
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xlabel("Time of day (IST), all days pooled")
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in RSRP_COLORS] + \
              [plt.Rectangle((0, 0), 1, 1, color="#f0efec")]
    labels = ["< −110", "−110…−100", "−100…−90", "−90…−80", "≥ −80", f"< {MIN_SAMPLES} samples"]
    ax.legend(handles, labels, loc="upper left", bbox_to_anchor=(0, -0.09 - 0.25 / len(order)), ncol=6,
              fontsize=9.5, title="Median RSRP (dBm)", title_fontsize=9.5, alignment="left")
    finish(fig, OUT_CHARTS, "01_rsrp_by_slot_heatmap.png", "Signal strength per phone across the day, in and around IITD",
           f"Median RSRP (dBm) per 2-hour slot, with ± standard deviation. Phone names: blue = Jio, "
           f"orange = Vi, green = Airtel. {d.ts.min():%d %b} – {d.ts.max():%d %b %Y}.",
           note="Each cell pools all days. Jio is mostly 5G (SS-RSRP, a few dB lower than LTE RSRP by "
                "definition), so compare phones within one operator. Full numbers: tables/device_slot_stats.csv.")


def chart_distribution(d, order, overall):
    o = overall[overall.metric == "rsrp"].set_index("phone")
    fig, ax = plt.subplots(figsize=(12, 0.5 * len(order) + 2))
    for i, ph in enumerate(order):
        v = d.loc[d.phone == ph, "rsrp"].dropna()
        p5, q1, med, q3, p95 = np.percentile(v, [5, 25, 50, 75, 95])
        c = OP_COLORS[ph.rsplit(" · ", 1)[1]]
        ax.plot([p5, p95], [i, i], color=c, lw=1.5, solid_capstyle="round")
        ax.add_patch(plt.Rectangle((q1, i - 0.28), q3 - q1, 0.56, color=c, alpha=0.35, lw=0))
        ax.plot([med, med], [i - 0.28, i + 0.28], color=c, lw=3)
        ax.scatter([v.min(), v.max()], [i, i], s=14, color=c, zorder=3, marker="|")
        ax.text(-41, i, f"median {med:.0f} · mean {v.mean():.0f} ± {v.std():.0f}   n={len(v):,} "
                        f"({o.loc[ph, 'hours']:.0f} h, {int(o.loc[ph, 'days'])} d)".replace("(0 h", "(<1 h"),
                va="center", fontsize=9, color=INK_SECONDARY)
    ax.set_yticks(range(len(order)), order, fontsize=10)
    for lbl in ax.get_yticklabels():
        lbl.set_color(OP_COLORS[lbl.get_text().rsplit(" · ", 1)[1]])
    ax.set_ylim(len(order) - 0.5, -0.5)
    ax.set_xlim(-140, 5)
    ax.set_xticks(range(-140, -39, 10))
    ax.set_xlabel("RSRP (dBm)  ·  line = 5th–95th percentile, box = middle 50%, thick tick = median, "
                  "small ticks = min / max")
    ax.grid(axis="y", visible=False)
    finish(fig, OUT_CHARTS, "02_rsrp_by_device.png", "RSRP of each phone in and around IITD",
           "All of each phone's IITD samples. Blue = Jio, orange = Vi, green = Airtel; sorted by median within each operator.",
           note="Phones were in different parts of campus at different times, so differences mix the phone, the "
                "spot and the operator — not a same-place comparison.")


def chart_area(d):
    fig, ax = plt.subplots(figsize=(10, 7))
    near = d[d.lat.between(28.530, 28.560) & d.lon.between(77.170, 77.215)]
    x, y = to_mercator(near.lat.values, near.lon.values)
    ax.scatter(x[~near.iitd.values], y[~near.iitd.values], s=2, color=CONTEXT, label="outside the IITD box")
    ax.scatter(x[near.iitd.values], y[near.iitd.values], s=2, color=INK_SECONDARY, label="counted as in/around IITD")
    bx, by = to_mercator(np.array([IITD["lat"][0], IITD["lat"][1]]), np.array([IITD["lon"][0], IITD["lon"][1]]))
    ax.add_patch(plt.Rectangle((bx[0], by[0]), bx[1] - bx[0], by[1] - by[0], fill=False, ec=INK_PRIMARY, lw=1.5))
    cx.add_basemap(ax, source=cx.providers.Esri.WorldGrayCanvas, attribution_size=6)
    ax.set_axis_off()
    ax.legend(loc="lower left", markerscale=6, fontsize=10, frameon=True, facecolor=SURFACE)
    share = d.iitd.mean() * 100
    finish(fig, OUT_CHARTS, "03_iitd_area.png", "Which samples count as \"in/around IITD\"",
           f"Box = IIT Delhi campus plus ~150 m ({IITD['lat'][0]}–{IITD['lat'][1]} N, "
           f"{IITD['lon'][0]}–{IITD['lon'][1]} E). {share:.0f}% of all GPS-tagged samples fall inside.")


def main():
    os.makedirs(OUT_CHARTS, exist_ok=True)
    apply_style()
    df = load_all()
    print(f"{len(df):,} GPS-tagged samples, {df.iitd.sum():,} in/around IITD")
    d = df[df.iitd].copy()
    overall, slot = tables(d)
    order = phone_order(overall)
    chart_heatmap(slot, order, d)
    chart_distribution(d, order, overall)
    chart_area(df)
    o = overall[overall.metric == "rsrp"].sort_values(["op", "median"], ascending=[True, False])
    print(o[["phone", "n", "hours", "days", "mean", "sd", "median", "min", "max", "pct_5g_sa"]].to_string(index=False))


if __name__ == "__main__":
    main()
