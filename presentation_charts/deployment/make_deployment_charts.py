"""
Charts for the field-deployment presentation: the preliminary deployment (Firestore app,
13–25 Oct 2026) against the robustness app installed on the same phones from 26 Oct.

    ../grafana_pipeline/venv/bin/python deployment/export_data.py   # → deployment/data/
    ./venv/bin/python deployment/make_deployment_charts.py          # → deployment/charts/

    01_daily_coverage     share of each day's 5 s slots logged, per phone, both phases
    02_before_after       the same, averaged per phase, for the phones in both phases
    03_where_samples      GPS samples in and around IIT Delhi, per phase
    04_fixed_spot_hours   one phone at one spot for three weeks: RSRP by date and hour
    06_hostel_map         where the samples for 04 were taken (Aravali Hostel box)
    07_moto_memory        why the Motorola g35 keeps being killed: least free memory, killed within seconds
    08_hostel_weeks       Vi signal at Aravali Hostel week by week since August (history)
    05_history            samples per week since August, by app version
"""

import json
import os

import contextily as cx
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "charts")
TZ = "Asia/Kolkata"

INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#8a8980"
SURFACE = "#fcfcfb"
GRID = "#e6e5e0"
CONTEXT = "#c3c2b7"
PHASE1 = "#eb6834"   # orange: old app
PHASE2 = "#2a78d6"   # blue: robustness app
SEQ = LinearSegmentedColormap.from_list("seq", ["#eef3fa", "#86b6ef", "#2a78d6", "#104281"])

SLOTS_PER_DAY = 24 * 3600 // 5
NEW_APP = pd.Timestamp("2026-10-26", tz=TZ)
P1 = (pd.Timestamp("2026-10-13", tz=TZ), NEW_APP)
P2 = (NEW_APP, pd.Timestamp("2026-11-17", tz=TZ))
IITD_BOX = (28.538, 28.5515, 77.1795, 77.2015)
# Outline of Aravali Hostel, where the Samsung M32 stayed, traced from satellite imagery
HOSTEL_BOX = (28.54825, 28.54915, 77.18313, 77.18400)

NAMES = {
    "SM-M325F": "Samsung Galaxy M32", "moto g35 5G": "Motorola g35 5G", "A001": "Nothing A001",
    "moto e13": "Motorola e13", "SM-S721B": "Samsung Galaxy S24 FE", "SM-S921B": "Samsung Galaxy S24",
    "SM-S908E": "Samsung Galaxy S22 Ultra", "SM-A346E": "Samsung Galaxy A34", "RMX3842": "Realme RMX3842",
    "2201117PI": "Xiaomi 2201117PI", "CPH2423": "OnePlus CPH2423", "V2518": "vivo V2518",
}

plt.rcParams.update({
    "font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": INK_SECONDARY,
    "xtick.color": INK_SECONDARY, "ytick.color": INK_SECONDARY, "axes.spines.top": False,
    "axes.spines.right": False, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
})


def finish(fig, name, title, subtitle, note=None):
    height_in = fig.get_size_inches()[1]
    top = 1 - 0.95 / height_in
    bottom = (0.45 / height_in) if note else 0
    fig.tight_layout(rect=[0, bottom, 1, top])
    fig.text(0.01, 1 - 0.18 / height_in, title, ha="left", va="top", fontsize=16, fontweight="bold")
    fig.text(0.01, 1 - 0.55 / height_in, subtitle, ha="left", va="top", fontsize=11, color=INK_SECONDARY)
    if note:
        fig.text(0.01, 0.1 / height_in, note, ha="left", va="bottom", fontsize=9, color=INK_MUTED)
    fig.savefig(os.path.join(OUT, name), dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {name}")


def load():
    df = pd.read_csv(os.path.join(DATA, "samples.csv"), dtype={"deviceId": str})
    df["t"] = pd.to_datetime(df.ts_ms, unit="ms", utc=True).dt.tz_convert(TZ)
    df["day"] = df.t.dt.floor("D")
    df["name"] = df.deviceModel.map(NAMES)
    return df[df.name.notna()]


def daily_coverage(df):
    days = pd.date_range(P1[0], P2[1] - pd.Timedelta(days=1), freq="D")
    cov = df[df.t >= P1[0]].groupby(["name", "day"]).size().unstack(0).reindex(days).fillna(0)
    return (cov / SLOTS_PER_DAY * 100).clip(upper=100)


def chart_daily_coverage(cov, df):
    counts = df[df.t >= P1[0]].groupby("name").size()
    first = df[df.t >= P1[0]].groupby("name").t.min()[counts >= 1000].sort_values()
    order = list(first.index)
    m = cov[order].T.values
    fig, ax = plt.subplots(figsize=(13, 6.2))
    im = ax.imshow(m, aspect="auto", cmap=SEQ, vmin=0, vmax=100, interpolation="none")
    ax.set_yticks(range(len(order)), order)
    ticks = [i for i, d in enumerate(cov.index) if d.weekday() == 0 or i == 0]
    ax.set_xticks(ticks, [cov.index[i].strftime("%d %b") for i in ticks])
    x_new = cov.index.get_loc(NEW_APP)
    ax.axvline(x_new - 0.5, color=INK_PRIMARY, lw=1.5)
    ax.text(x_new - 0.3, -0.75, "26 Oct: new app installed →", fontsize=10, color=INK_PRIMARY, va="bottom")
    ax.text(x_new - 0.7, -0.75, "← Preliminary deployment", fontsize=10, color=INK_SECONDARY, va="bottom", ha="right")
    for i, name in enumerate(order):
        for j, v in enumerate(cov[name].values):
            if v >= 0.5:
                ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=7,
                        color="white" if v > 55 else INK_PRIMARY)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01)
    cb.set_label("% of the day's 5 s samples logged", color=INK_SECONDARY)
    cb.outline.set_visible(False)
    finish(fig, "01_daily_coverage.png", "How much of each day did each phone log?",
           "100 = a sample every 5 seconds for the whole day (17,280 samples). Pale with no number = the phone did not log that day.",
           "Days in IST, 13 Oct – 16 Nov 2026. Phones with fewer than 1,000 samples (vivo V2518) left out.")


def chart_before_after(cov):
    phones = ["Samsung Galaxy M32", "Motorola g35 5G"]
    p1 = cov.loc[(cov.index >= P1[0] + pd.Timedelta(days=3)) & (cov.index < P1[1]), phones].mean()
    p2 = cov.loc[(cov.index > P2[0]) & (cov.index < pd.Timestamp("2026-11-16", tz=TZ)), phones].mean()
    fig, ax = plt.subplots(figsize=(10, 3.8))
    y = np.arange(len(phones))
    ax.barh(y - 0.2, p1.values, height=0.36, color=PHASE1, label="Preliminary app (16–25 Oct)")
    ax.barh(y + 0.2, p2.values, height=0.36, color=PHASE2, label="New app (27 Oct – 15 Nov)")
    for yy, a, b in zip(y, p1.values, p2.values):
        ax.text(a + 1, yy - 0.2, f"{a:.0f}%", va="center", fontsize=11, color=INK_PRIMARY)
        ax.text(b + 1, yy + 0.2, f"{b:.0f}%", va="center", fontsize=11, color=INK_PRIMARY, fontweight="bold")
    ax.set_yticks(y, phones)
    ax.set_xlim(0, 105)
    ax.set_xlabel("Average share of the day logged at 5 s (%)")
    ax.invert_yaxis()
    ax.grid(axis="x", color=GRID)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="lower right")
    finish(fig, "02_before_after.png", "Same phones, new app: more of the day is logged",
           "Both phones were meant to log around the clock in both phases.",
           "16 Oct = first full day both phones ran the Firestore app; 26 Oct (install day) and 16 Nov (stopped) left out.")
    return p1, p2


def chart_where(df):
    lat0, lat1, lon0, lon1 = IITD_BOX
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.2))
    for ax, (label, (a, b), color) in zip(axes, [("Preliminary deployment, 13–25 Oct", P1, PHASE1),
                                                 ("New app, 26 Oct – 16 Nov", P2, PHASE2)]):
        x = df[(df.t >= a) & (df.t < b)].dropna(subset=["lat", "lon"])
        inside = x[x.lat.between(lat0, lat1) & x.lon.between(lon0, lon1)]
        pts = inside.sample(min(len(inside), 40000), random_state=1)
        mx, my = to_mercator(pts.lon.values, pts.lat.values)
        ax.scatter(mx, my, s=2, color=color, alpha=0.35, linewidths=0)
        bx, by = to_mercator(np.array([lon0, lon1]), np.array([lat0, lat1]))
        ax.set_xlim(*bx)
        ax.set_ylim(*by)
        cx.add_basemap(ax, source=cx.providers.Esri.WorldGrayCanvas, attribution_size=6, zoom=15)
        ax.set_axis_off()
        phones = inside.name.nunique()
        ax.set_title(f"{label}\n{len(inside):,} samples from {phones} phones · "
                     f"{len(x) - len(inside):,} more outside this area (not shown)",
                     loc="left", fontsize=11, color=INK_SECONDARY)
    finish(fig, "03_where_samples.png", "Where the samples were taken",
           "Each dot is a 5 s sample with a GPS fix inside the IIT Delhi area (campus plus ~150 m).",
           "Points thinned to 40,000 per map. Off-campus samples are left out to keep testers' homes private.")


def to_mercator(lon, lat):
    r = 6378137.0
    return np.radians(lon) * r, np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) * r


def chart_fixed_spot(df):
    x = df[(df.deviceModel == "SM-M325F") & (df.t >= pd.Timestamp("2026-10-27", tz=TZ))
           & (df.t < pd.Timestamp("2026-11-16", tz=TZ))].dropna(subset=["lat", "lon", "rsrp"])
    lat0, lat1, lon0, lon1 = HOSTEL_BOX
    x = x[x.lat.between(lat0, lat1) & x.lon.between(lon0, lon1)]
    x = x.assign(hour=x.t.dt.hour, date=x.t.dt.strftime("%d %b"))
    grid = x.pivot_table(index="date", columns="hour", values="rsrp", aggfunc="median")
    grid = grid.reindex(sorted(grid.index, key=lambda d: pd.Timestamp(d + " 2026")))
    prof = x.groupby("hour").rsrp.agg(["median", lambda s: s.quantile(0.25), lambda s: s.quantile(0.75)])
    prof.columns = ["med", "q1", "q3"]

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(14, 6.8), gridspec_kw={"width_ratios": [3, 1.3]})
    cmap = LinearSegmentedColormap.from_list("rsrp", ["#d7301f", "#fc8d59", "#fee08b", "#91bfdb", "#2c7bb6"])
    im = ax.imshow(grid.values, aspect="auto", cmap=cmap, vmin=-110, vmax=-80, interpolation="none")
    ax.set_yticks(range(len(grid.index)), grid.index, fontsize=9)
    ax.set_xticks(range(0, 24, 3), [f"{h:02d}:00" for h in range(0, 24, 3)])
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.01)
    cb.set_label("Median RSRP (dBm)", color=INK_SECONDARY)
    cb.outline.set_visible(False)
    ax.set_title("Median RSRP per hour", loc="left", fontsize=11, color=INK_SECONDARY)

    ax2.fill_betweenx(prof.index, prof.q1, prof.q3, color=PHASE2, alpha=0.2, linewidth=0, label="Middle 50%")
    ax2.plot(prof.med, prof.index, color=PHASE2, lw=2, label="Median")
    ax2.set_ylim(23.5, -0.5)
    ax2.set_yticks(range(0, 24, 3), [f"{h:02d}:00" for h in range(0, 24, 3)])
    ax2.set_xlabel("RSRP (dBm)")
    ax2.grid(axis="x", color=GRID)
    ax2.legend(frameon=False, loc="lower left", fontsize=9)
    ax2.set_title("All days, by hour of day", loc="left", fontsize=11, color=INK_SECONDARY)
    finish(fig, "04_fixed_spot_hours.png", "One phone in Aravali Hostel, three weeks: signal by time of day",
           f"Samsung Galaxy M32 on Vi, only samples inside Aravali Hostel ({len(x):,} samples).",
           "27 Oct – 15 Nov 2026, IST. Colours use the same red-to-blue RSRP scale as the coverage maps.")
    return prof, len(x)


def chart_hostel_map(df):
    x = df[(df.deviceModel == "SM-M325F") & (df.t >= pd.Timestamp("2026-10-27", tz=TZ))
           & (df.t < pd.Timestamp("2026-11-16", tz=TZ))].dropna(subset=["lat", "lon"])
    lat0, lat1, lon0, lon1 = HOSTEL_BOX
    clat, clon = (lat0 + lat1) / 2, (lon0 + lon1) / 2
    near = x[x.lat.between(clat - 0.0016, clat + 0.0016) & x.lon.between(clon - 0.002, clon + 0.002)]
    inside = near.lat.between(lat0, lat1) & near.lon.between(lon0, lon1)
    fig, ax = plt.subplots(figsize=(10, 8.6))
    for sel, color, size, label in [(~inside, "#ffffff", 3, "Outside (not used)"), (inside, "#ffcc00", 3, "Inside Aravali Hostel (used)")]:
        pts = near[sel].sample(min(sel.sum(), 15000), random_state=1)
        mx, my = to_mercator(pts.lon.values, pts.lat.values)
        ax.scatter(mx, my, s=size, color=color, alpha=0.45, linewidths=0, label=label)
    bx, by = to_mercator(np.array([lon0, lon1, lon1, lon0, lon0]), np.array([lat0, lat0, lat1, lat1, lat0]))
    ax.plot(bx, by, color="#00d0e0", lw=2.5)
    ex, ey = to_mercator(np.array([clon - 0.0016, clon + 0.0016]), np.array([clat - 0.0013, clat + 0.0013]))
    ax.set_xlim(*ex)
    ax.set_ylim(*ey)
    cx.add_basemap(ax, source=cx.providers.Esri.WorldImagery, zoom=18, attribution_size=6)
    ax.text(bx[1] + 8, by[2] - 4, "Aravali Hostel", color="white", fontsize=13, fontweight="bold", va="top")
    ax.set_axis_off()
    leg = ax.legend(loc="lower left", markerscale=5, frameon=True, fontsize=10)
    leg.get_frame().set_alpha(0.85)
    finish(fig, "06_hostel_map.png", "Where the temporal data comes from",
           f"Samsung Galaxy M32, 27 Oct – 15 Nov: {inside.sum():,} of its {len(x):,} GPS fixes fall inside the Aravali Hostel box.",
           "Box ≈ 100 m × 85 m, traced around the hostel building on satellite imagery (Esri World Imagery).")


def chart_moto_memory():
    ram = pd.read_csv(os.path.join(DATA, "ram.csv"))
    ram["name"] = ram.deviceModel.map(NAMES)
    ram = ram[ram.name.notna()]
    stats = ram.groupby("name").agg(free=("availableRamGB", "median"), total=("totalRamGB", "median"), n=("ts_ms", "size"))
    stats = stats[stats.n >= 30].sort_values("free")

    with open(os.path.join(DATA, "sessions.json")) as f:
        sessions = json.load(f)
    alive = []
    for sess in sessions:
        if sess["deviceModel"] != "moto g35 5G":
            continue
        resumed = None
        for e in sorted(sess.get("events", []), key=lambda e: e["atMs"]):
            if e["type"] == "resumed":
                resumed = e["atMs"]
            elif e["type"] == "process_exit" and resumed:
                alive.append((e["atMs"] - resumed) / 1000)
                resumed = None
    alive = pd.Series(alive)
    bins = [0, 10, 60, 600, 3600, np.inf]
    labels = ["< 10 s", "10–60 s", "1–10 min", "10–60 min", "> 1 h"]
    share = pd.cut(alive, bins, labels=labels, right=False).value_counts(normalize=True).reindex(labels) * 100

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(14, 5.6), gridspec_kw={"width_ratios": [1.25, 1]})
    y = np.arange(len(stats))
    colors = [PHASE1 if n == "Motorola g35 5G" else CONTEXT for n in stats.index]
    ax.barh(y, stats.total, color=GRID, height=0.62, label="Total memory")
    ax.barh(y, stats.free, color=colors, height=0.62, label="Free (median)")
    for yy, (fr, tot) in enumerate(zip(stats.free, stats.total)):
        ax.text(tot + 0.15, yy, f"{fr:.1f} of {tot:.1f} GB free", va="center", fontsize=9.5, color=INK_SECONDARY)
    ax.set_yticks(y, stats.index, fontsize=10)
    ax.set_xlim(0, 14.5)
    ax.set_xlabel("Memory (GB)")
    ax.grid(axis="x", color=GRID)
    ax.set_axisbelow(True)
    ax.set_title("Free memory, from the 15-minute device-health rows", loc="left", fontsize=11, color=INK_SECONDARY)

    bars = ax2.bar(labels, share.values, color=[PHASE1, PHASE1, CONTEXT, CONTEXT, CONTEXT], width=0.62)
    for b, v in zip(bars, share.values):
        ax2.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.0f}%", ha="center", fontsize=11, fontweight="bold")
    ax2.set_ylabel("Share of kills (%)")
    ax2.set_ylim(0, max(share.values) + 10)
    ax2.grid(axis="y", color=GRID)
    ax2.set_axisbelow(True)
    ax2.set_title(f"How long the app lived after each restart ({len(alive):,} kills)", loc="left",
                  fontsize=11, color=INK_SECONDARY)
    finish(fig, "07_moto_memory.png", "The Motorola g35 runs short of memory, and Android keeps killing the app",
           f"It has the least free memory of all phones; {share.iloc[:2].sum():.0f}% of kills came within a minute of a restart.",
           "Kills from the new app's session events, 26 Oct – 17 Nov (Android reason: low memory, \"Watermark Pressure\"). "
           "Phones with fewer than 30 health rows left out.")


def chart_hostel_weeks():
    h = pd.read_csv(os.path.join(DATA, "hostel_history.csv"))
    h = h[h.op == "Vi"]
    h["t"] = pd.to_datetime(h.ts_ms, unit="ms", utc=True).dt.tz_convert(TZ).dt.tz_localize(None)
    h["week"] = h.t.dt.to_period("W-SUN").dt.start_time
    w = h.groupby("week").agg(med=("rsrp", "median"), q1=("rsrp", lambda s: s.quantile(0.25)),
                              q3=("rsrp", lambda s: s.quantile(0.75)), n=("rsrp", "size"),
                              days=("t", lambda s: s.dt.date.nunique()))
    w = w[(w.n >= 100) & (w.days >= 3)]
    x = w.index + pd.Timedelta(days=3)
    fig, ax = plt.subplots(figsize=(12, 5.2))
    ax.vlines(x, w.q1, w.q3, color=PHASE2, alpha=0.3, lw=16, label="Middle half of the week's samples")
    ax.plot(x, w.med, color=PHASE2, marker="o", ms=8, lw=0, label="Median")
    for xx, (m, q3, n) in zip(x, zip(w.med, w.q3, w.n)):
        ax.text(xx, q3 + 0.8, f"{m:.0f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
        ax.text(xx, -113.2, f"{n:,}", ha="center", fontsize=9, color=INK_MUTED)
    ax.text(w.index.min() - pd.Timedelta(days=4), -113.2, "samples", ha="right", fontsize=9, color=INK_MUTED)
    ax.axvline(pd.Timestamp("2026-10-13"), color=INK_MUTED, lw=1, ls="--")
    ax.text(pd.Timestamp("2026-10-12"), -80, "CSV app  ", ha="right", fontsize=10, color=INK_SECONDARY)
    ax.text(pd.Timestamp("2026-10-14"), -80, "  Firestore app", ha="left", fontsize=10, color=INK_SECONDARY)
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO, interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.set_ylabel("RSRP (dBm)")
    ax.set_ylim(-115, -78)
    ax.grid(axis="y", color=GRID)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="upper left", fontsize=10)
    finish(fig, "08_hostel_weeks.png", "Vi signal at Aravali Hostel, week by week since August",
           "Number = median RSRP that week. All Vi phones, only samples inside the hostel box.",
           "Weeks with fewer than 100 samples or 3 days of data left out (gaps). Vi phones: Samsung M32, OnePlus CPH2487, Nothing A001.")
    return w


def chart_history():
    h = pd.read_csv(os.path.join(DATA, "daily_history.csv"), parse_dates=["day"])
    w = h.groupby([pd.Grouper(key="day", freq="W-MON", label="left", closed="left"), "source"]).samples.sum().unstack().fillna(0)
    fig, ax = plt.subplots(figsize=(12, 4.6))
    ax.bar(w.index, w.get("storage_csv", 0) / 1000, width=5.5, color=CONTEXT, label="CSV app (uploaded on Stop)", align="edge")
    ax.bar(w.index, w.get("firestore", 0) / 1000, width=5.5, bottom=w.get("storage_csv", 0) / 1000,
           color=PHASE2, label="Firestore app (live, every minute)", align="edge")
    ax.axvline(pd.Timestamp("2026-10-26"), color=INK_PRIMARY, lw=1)
    ax.text(pd.Timestamp("2026-10-26") - pd.Timedelta(days=0.5), ax.get_ylim()[1] * 0.95, "new app installed",
            fontsize=10, va="top", ha="right")
    ax.set_ylabel("Samples per week (thousands)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.grid(axis="y", color=GRID)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="upper left")
    total = h.samples.sum()
    finish(fig, "05_history.png", "Everything is kept: the dashboards can go back to August",
           f"{total / 1e6:.2f} million 5 s samples in InfluxDB, {h.deviceId.nunique()} phones, since {h.day.min():%d %b %Y}.",
           "Weeks start on Monday; the last week is partial (to 17 Nov). Airtel rows stored twice are counted once.")
    return h


def phase_events():
    with open(os.path.join(DATA, "sessions.json")) as f:
        sessions = json.load(f)
    rows = []
    for s in sessions:
        for e in s.get("events", []):
            rows.append({"model": s["deviceModel"], "type": e["type"], "reason": e.get("reason"),
                         "description": e.get("description"), "gapMs": e.get("gapMs")})
    return pd.DataFrame(rows)


def main():
    os.makedirs(OUT, exist_ok=True)
    df = load()
    cov = daily_coverage(df)
    chart_daily_coverage(cov, df)
    p1, p2 = chart_before_after(cov)
    print("phase averages\n", pd.DataFrame({"p1": p1, "p2": p2}).round(1))
    chart_where(df)
    prof, n = chart_fixed_spot(df)
    print("hour profile\n", prof.round(1).T)
    chart_hostel_map(df)
    chart_moto_memory()
    print(chart_hostel_weeks())
    chart_history()
    ev = phase_events()
    print(ev.groupby(["model", "type"]).size().unstack(fill_value=0))


if __name__ == "__main__":
    main()
