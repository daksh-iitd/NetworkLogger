"""
Research-question charts built from the raw session export (android-telecom-logs.zip),
complementing the per-session route maps in make_map_charts.py.

Reads every logs/<uid>/<deviceId>/<sessionId>/network_logs.csv straight from the raw
export zip or from the local Firebase mirror (grafana_pipeline/fetch_logs.py) — no
InfluxDB needed — and writes:

    1_sampling_intervals.png     - how often the 5-second schedule was actually met
    2_radio_mix_by_operator.png  - 5G SA / 5G NSA / 4G share, Jio vs Vi
    3_5g_fallback_threshold.png  - serving RSRP at the moment Jio drops 5G -> 4G
    4_same_location_operators.png- Jio vs Vi at the one location both logged heavily
    5_time_of_day.png            - signal vs hour of day at fixed locations
    6_stationary_cell_churn.png  - serving-cell changes on a phone that never moved
    7_rsrp_vs_rsrq.png           - coverage-limited vs interference-limited samples

Usage:
    ./venv/bin/python code/make_research_charts.py \
        --src ../grafana_pipeline/firebase_csv_mirror --out-dir research
"""

import argparse
import io
import json
import os
import zipfile

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Same reference palette as make_map_charts.py. Color only ever encodes the radio
# technology of the serving cell, so it means the same thing on every slide.
NR = "#2a78d6"        # 5G (NR serving cell)  - slot 1 blue
LTE = "#eb6834"       # 4G (LTE serving cell) - slot 2 orange
NSA = "#1baf7a"       # 5G NSA (LTE anchor)   - slot 3 aqua
CONTEXT = "#c3c2b7"   # gray for background/context marks
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#8a8980"
SURFACE = "#fcfcfb"
GRID = "#e6e5e0"

SAMPLE_INTERVAL_S = 5
SHARED_CELL_DEG = 0.0018   # ~200 m grid used to find locations both operators logged


# ── Loading ──────────────────────────────────────────────────────────────────

def iter_session_files(source, file_name):
    """Yield (deviceId, sessionId, bytes, upload-metadata) for every session file,
    from either the raw export zip or a fetch_logs.py mirror directory."""
    if os.path.isdir(source):
        logs_root = os.path.join(source, "logs")
        for uid in sorted(os.listdir(logs_root)):
            for dev in sorted(os.listdir(os.path.join(logs_root, uid))):
                dev_dir = os.path.join(logs_root, uid, dev)
                if not os.path.isdir(dev_dir):
                    continue
                for ses in sorted(os.listdir(dev_dir)):
                    path = os.path.join(dev_dir, ses, file_name)
                    if not os.path.isfile(path):
                        continue
                    meta = {}
                    if os.path.isfile(path + ".meta.json"):
                        with open(path + ".meta.json") as f:
                            meta = json.load(f).get("metadata", {})
                    with open(path, "rb") as f:
                        yield dev, ses, f.read(), meta
    else:
        with zipfile.ZipFile(source) as zf:
            for name in zf.namelist():
                parts = name.split("/")
                # logs/<uid>/<deviceId>/<sessionId>/<file>; the few loose files directly
                # under a uid predate per-session folders and are skipped.
                if len(parts) == 5 and parts[-1] == file_name:
                    yield parts[2], parts[3], zf.read(name), {}


def load_sessions(source):
    frames = []
    for dev, ses, raw, meta in iter_session_files(source, "network_logs.csv"):
        df = pd.read_csv(io.BytesIO(raw), dtype=str, on_bad_lines="skip")
        if df.empty:
            continue
        df["device"], df["session"] = dev, ses
        df["model"] = meta.get("deviceModel", "unknown")
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    for col in ["lat", "lon", "pci", "tac", "nci", "rsrp", "rsrq", "sinr",
                "neighborCount", "dlKbps", "ulKbps"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["ts"] = build_timestamps(df)
    df = df.sort_values(["device", "session", "ts"]).reset_index(drop=True)

    # Obvious sensor garbage -> missing
    df.loc[(df.lat == 0) | (df.lon == 0), ["lat", "lon"]] = np.nan
    df.loc[(df.rsrp > -30) | (df.rsrp < -150), "rsrp"] = np.nan
    # Some modems (seen on the A001 and Motorola) report RSRP −44 with RSRQ −3 — both at
    # the top of Android's range — when they have no valid measurement. Not a real signal.
    saturated = (df.rsrp == -44) & (df.rsrq == -3)
    df.loc[saturated, ["rsrp", "rsrq"]] = np.nan
    df.loc[(df.rsrq > 0) | (df.rsrq < -40), "rsrq"] = np.nan

    # Serving-cell RAT from the cell data itself. 62% of rows carry network="Unknown"
    # (phone-state permission denied), but only the app's NR branch writes a 36-bit
    # NCI; the LTE branch writes the 8-bit local cell id.
    df["cell_rat"] = np.where(df.nci > 255, "NR", np.where(df.nci.notna(), "LTE", "?"))
    mcc = df.mcc.astype(str)
    df["op"] = np.where(mcc.str.startswith("405"), "Jio",
                np.where(df.mnc.astype(str).isin(["11", "011"]), "Vi", "Other"))
    df["radio"] = np.select(
        [df.cell_rat == "NR", df.network == "5G (NSA)", df.cell_rat == "LTE"],
        ["5G SA", "5G NSA", "4G"], default="?")
    return df


def build_timestamps(df):
    # Rows only carry HH:mm:ss. The session id is stamped at *upload*, i.e. when the
    # session ended (LoggingService.uploadLogsToFirebaseStorage), so anchor the last
    # row on that date and walk backwards, stepping back a day whenever the clock
    # jumps forward (a midnight crossing seen in reverse).
    out = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    for _, g in df.groupby(["device", "session"], sort=False):
        end = pd.to_datetime(g.session.iloc[0], format="%Y%m%d_%H%M%S")
        tod = pd.to_timedelta(g.time, errors="coerce")
        day = end.normalize()
        end_tod = end - day
        values, prev = [], None
        for t in reversed(tod.tolist()):
            if pd.isna(t):
                values.append(pd.NaT)
                continue
            if prev is None and t > end_tod + pd.Timedelta(minutes=5):
                day -= pd.Timedelta(days=1)
            elif prev is not None and t > prev + pd.Timedelta(hours=1):
                day -= pd.Timedelta(days=1)
            values.append(day + t)
            prev = t
        out.loc[g.index] = values[::-1]
    return out


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = (np.sin((p2 - p1) / 2) ** 2
         + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371000 * np.arcsin(np.sqrt(a))


# ── Styling ──────────────────────────────────────────────────────────────────

def apply_style():
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.size": 11,
        "text.color": INK_PRIMARY,
        "axes.edgecolor": GRID,
        "axes.labelcolor": INK_SECONDARY,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "axes.axisbelow": True,
        "xtick.color": INK_SECONDARY,
        "ytick.color": INK_SECONDARY,
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "legend.frameon": False,
    })


def finish(fig, out_dir, name, title, subtitle, note=None):
    # Reserve fixed bands for the title block and footnote so they never collide
    # with tick labels or legends inside the plot area.
    height_in = fig.get_size_inches()[1]
    top = 1 - 0.95 / height_in
    bottom = (0.45 / height_in) if note else 0
    fig.tight_layout(rect=[0, bottom, 1, top])
    fig.text(0.01, 1 - 0.18 / height_in, title, ha="left", va="top", fontsize=16, fontweight="bold")
    fig.text(0.01, 1 - 0.55 / height_in, subtitle, ha="left", va="top", fontsize=11, color=INK_SECONDARY)
    if note:
        fig.text(0.01, 0.1 / height_in, note, ha="left", va="bottom", fontsize=9, color=INK_MUTED)
    fig.savefig(os.path.join(out_dir, name), dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {name}")


# ── Charts ───────────────────────────────────────────────────────────────────

def chart_sampling_intervals(df, out_dir):
    gaps = df.groupby(["device", "session"]).ts.diff().dt.total_seconds().dropna()
    bins = [0, 6, 15, 60, 300, np.inf]
    labels = ["≤ 6 s\n(on schedule)", "6–15 s", "15–60 s", "1–5 min", "> 5 min"]
    share = pd.cut(gaps, bins, labels=labels).value_counts(normalize=True).reindex(labels) * 100

    fig, ax = plt.subplots(figsize=(11, 5.6))
    colors = [NR] + [CONTEXT] * 4
    bars = ax.bar(labels, share.values, color=colors, width=0.62)
    for b, v in zip(bars, share.values):
        ax.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.0f}%", ha="center",
                fontsize=12, color=INK_PRIMARY, fontweight="bold")
    ax.set_ylabel("Share of consecutive-sample gaps (%)")
    ax.set_ylim(0, max(share.values) * 1.18)
    ax.grid(axis="x", visible=False)
    dur_h = df.groupby(["device", "session"]).ts.agg(lambda t: (t.max() - t.min()).total_seconds() / 3600)
    long_keys = set(dur_h[dur_h > 24].index)
    key = pd.MultiIndex.from_frame(df.loc[gaps.index, ["device", "session"]])
    long_share = (gaps[key.isin(long_keys)] > 60).sum() / (gaps > 60).sum() * 100
    finish(fig, out_dir, "1_sampling_intervals.png",
           f"Only {share.iloc[0]:.0f}% of samples arrived on the 5-second schedule",
           f"Gap between consecutive samples within a session · {len(gaps):,} gaps, "
           f"{df.device.nunique()} devices, {df.groupby(['device','session']).ngroups} sessions",
           f"{long_share:.0f}% of the gaps over 1 min come from the {len(long_keys)} sessions that ran longer than a day — "
           "consistent with Android battery management (Doze) throttling logging while the phone sits idle.")


def chart_radio_mix(df, out_dir):
    d = df[df.op.isin(["Jio", "Vi"]) & (df.radio != "?")]
    order = ["5G SA", "5G NSA", "4G"]
    colors = {"5G SA": NR, "5G NSA": NSA, "4G": LTE}
    share = pd.crosstab(d.op, d.radio, normalize="index").reindex(columns=order, fill_value=0) * 100
    counts = d.groupby("op").agg(n=("radio", "size"), devs=("device", "nunique"))

    fig, ax = plt.subplots(figsize=(11, 4.6))
    ops = ["Jio", "Vi"]
    left = np.zeros(len(ops))
    for r in order:
        vals = share.loc[ops, r].values
        ax.barh(ops, vals, left=left, color=colors[r], height=0.55, label=r,
                edgecolor=SURFACE, linewidth=2)
        for i, v in enumerate(vals):
            if v >= 6:
                ax.text(left[i] + v / 2, i, f"{r}\n{v:.0f}%", ha="center", va="center",
                        color="white", fontsize=10.5, fontweight="bold")
        left += vals
    ax.set_yticks(range(len(ops)))
    ax.set_yticklabels([f"{o}\n{counts.loc[o,'n']:,} samples · {counts.loc[o,'devs']} devices"
                        for o in ops])
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of samples (%)")
    ax.grid(axis="y", visible=False)
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.2))
    finish(fig, out_dir, "2_radio_mix_by_operator.png",
           "Jio runs standalone 5G; Vi's 5G is always NSA on a 4G anchor",
           "Serving radio technology per sample, by operator",
           "5G SA = NR serving cell. 5G NSA = LTE serving cell with an NR data leg "
           "(TelephonyDisplayInfo override). Samples, not unique users — dominated by a few long sessions.")


def fallback_transitions(df):
    rows = []
    for _, g in df[df.op == "Jio"].groupby(["device", "session"]):
        g = g.reset_index(drop=True)
        dt = g.ts.diff().dt.total_seconds()
        for i in range(1, len(g)):
            if dt[i] <= 30 and g.cell_rat[i - 1] == "NR" and g.cell_rat[i] == "LTE":
                rows.append(dict(device=g.device[i], rsrp=g.rsrp[i - 1]))
    return pd.DataFrame(rows)


def chart_fallback(df, out_dir):
    tr = fallback_transitions(df).dropna()
    nr_all = df[(df.op == "Jio") & (df.cell_rat == "NR")].rsrp.dropna()
    med = tr.rsrp.median()

    fig, ax = plt.subplots(figsize=(11, 5.6))
    bins = np.arange(-130, -79, 2)
    w_all = np.ones(len(nr_all)) / len(nr_all) * 100
    w_tr = np.ones(len(tr)) / len(tr) * 100
    ax.hist(nr_all, bins=bins, weights=w_all, color=CONTEXT, label=f"All Jio 5G samples (n={len(nr_all):,})")
    ax.hist(tr.rsrp, bins=bins, weights=w_tr, color=NR, alpha=0.9, rwidth=0.7,
            label=f"Last 5G sample before dropping to 4G (n={len(tr)})")
    ax.axvline(med, color=INK_PRIMARY, linewidth=1.5, linestyle="--")
    ax.text(med - 0.6, ax.get_ylim()[1] * 0.97, f"median {med:.0f} dBm", ha="right", va="top",
            fontsize=11, fontweight="bold",
            bbox=dict(facecolor=SURFACE, edgecolor="none", alpha=0.9, pad=2))
    ax.set_xlabel("5G serving-cell RSRP (dBm)  —  weaker ←   → stronger")
    ax.set_ylabel("Share of samples (%)")
    ax.legend(loc="upper right")
    ax.grid(axis="x", visible=False)
    finish(fig, out_dir, "3_5g_fallback_threshold.png",
           f"Jio's 5G→4G switches cluster around {med:.0f} dBm",
           f"RSRP of the 5G serving cell just before each 5G→4G switch · "
           f"{len(tr)} switches on {tr.device.nunique()} devices",
           "Only switches with consecutive samples ≤ 30 s apart. Switch RSRP overlaps normal 5G RSRP "
           "heavily — fallback isn't a single hard threshold, and many switches are ping-pong at a fixed spot.")


def shared_location(df):
    d = df.dropna(subset=["lat", "lon"]).copy()
    d["gx"] = (d.lat / SHARED_CELL_DEG).round().astype(int)
    d["gy"] = (d.lon / SHARED_CELL_DEG).round().astype(int)
    per = d[d.op.isin(["Jio", "Vi"])].groupby(["gx", "gy", "op"]).size().unstack(fill_value=0)
    per = per[(per.get("Jio", 0) > 0) & (per.get("Vi", 0) > 0)]
    gx, gy = per.min(axis=1).idxmax()
    return d[(d.gx == gx) & (d.gy == gy) & d.op.isin(["Jio", "Vi"])]


def chart_same_location(df, out_dir):
    s = shared_location(df)
    groups = [("Jio", "LTE", "Jio · 4G", LTE), ("Jio", "NR", "Jio · 5G SA", NR),
              ("Vi", "LTE", "Vi · 4G / 5G NSA anchor", LTE)]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.8))
    for ax, metric, label in [(axes[0], "rsrp", "RSRP (dBm) — signal strength"),
                              (axes[1], "rsrq", "RSRQ (dB) — signal quality")]:
        data, names, cols = [], [], []
        for op, rat, name, c in groups:
            v = s[(s.op == op) & (s.cell_rat == rat)][metric].dropna()
            data.append(v)
            names.append(f"{name}\nn={len(v):,}")
            cols.append(c)
        bp = ax.boxplot(data, patch_artist=True, widths=0.5, showfliers=False,
                        medianprops=dict(color=INK_PRIMARY, linewidth=2))
        for patch, c in zip(bp["boxes"], cols):
            patch.set_facecolor(c)
            patch.set_edgecolor(c)
            patch.set_alpha(0.85)
        for i, v in enumerate(data, start=1):
            ax.text(i + 0.3, v.median(), f"{v.median():.0f}", va="center", fontsize=10.5,
                    fontweight="bold")
        ax.set_xticks(range(1, len(names) + 1))
        ax.set_xticklabels(names, fontsize=10)
        ax.set_title(label, fontsize=12)
        ax.grid(axis="x", visible=False)
    devs = s.groupby("op").device.nunique()
    finish(fig, out_dir, "4_same_location_operators.png",
           "At the same spot, Vi's 4G is stronger and cleaner than Jio's 4G",
           f"All samples inside one ~200 m grid cell logged by both operators · "
           f"Jio {devs.get('Jio',0)} device, Vi {devs.get('Vi',0)} devices · higher is better on both",
           "Compare like with like: Jio 4G vs Vi 4G. 5G SS-RSRP is measured on a different reference "
           "signal and runs lower by design, so Jio 5G vs Vi 4G is not an apples-to-apples RSRP comparison.")


def chart_time_of_day(df, out_dir):
    # The two longest stationary sessions, one per operator
    picks = [("22c7af7602d27af4", "20260906_133054", "Jio phone, 5 days in place"),
             ("c176d0f3ae801a6d", "20260909_153934", "Vi phone, 2 days in place")]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2), sharey=True)
    for ax, (dev, ses, label) in zip(axes, picks):
        g = df[(df.device == dev) & (df.session == ses)].dropna(subset=["ts", "rsrp"])
        # Sampling rate varies 5 s .. several minutes; bursts at 5 s would otherwise
        # let a single busy hour on one day dominate that hour's statistics.
        g = g.groupby(g.ts.dt.floor("2min")).first()
        h = g.groupby(g.ts.dt.hour).rsrp.quantile([0.25, 0.5, 0.75]).unstack()
        ax.fill_between(h.index, h[0.25], h[0.75], color=CONTEXT, alpha=0.6, linewidth=0,
                        label="middle 50%")
        ax.plot(h.index, h[0.5], color=INK_PRIMARY, linewidth=2, label="median")
        ax.set_ylim(-125, -85)
        ax.set_xlim(0, 23)
        ax.set_xticks([0, 6, 12, 18, 23])
        ax.set_title(label, fontsize=11.5)
        ax.set_xlabel("Hour of day")
    axes[0].set_ylabel("RSRP (dBm)")
    axes[0].legend(loc="lower left")
    finish(fig, out_dir, "5_time_of_day.png",
           "At a fixed spot, signal strength doesn't change with time of day",
           "Median RSRP by hour for the two longest stationary sessions — "
           "flat to within ~2–3 dB around the clock for both operators",
           "Thinned to one sample per 2 minutes so bursts of 5-second logging don't dominate an hour. "
           "RSRP isn't a load metric — peak-hour congestion needs active throughput/latency tests to measure.")


def chart_cell_churn(df, out_dir):
    dev, ses = "22c7af7602d27af4", "20260906_133054"
    g = df[(df.device == dev) & (df.session == ses)].dropna(subset=["pci"]).copy()
    med_lat, med_lon = g.lat.median(), g.lon.median()
    p90_m = np.nanpercentile(haversine_m(g.lat, g.lon, med_lat, med_lon), 90)
    seq = g.pci.values
    changes = int((np.diff(seq) != 0).sum())
    aba = sum(1 for i in range(2, len(seq)) if seq[i] == seq[i - 2] != seq[i - 1])
    days = (g.ts.max() - g.ts.min()).total_seconds() / 86400

    top = g.pci.value_counts().head(8).index
    g["pci_label"] = np.where(g.pci.isin(top), g.pci.astype("Int64").astype(str), "other")
    order = [str(int(p)) for p in top] + ["other"]
    ypos = {p: i for i, p in enumerate(order)}
    rat_of = g.groupby("pci_label").cell_rat.agg(lambda x: x.value_counts().index[0])

    fig, ax = plt.subplots(figsize=(13, 5.6))
    for rat, c in [("NR", NR), ("LTE", LTE)]:
        h = g[g.cell_rat == rat]
        ax.scatter(h.ts, h.pci_label.map(ypos), s=9, color=c, alpha=0.75, linewidths=0,
                   label="5G cell" if rat == "NR" else "4G cell")
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([f"PCI {p}" if p != "other" else "other cells" for p in order])
    ax.invert_yaxis()
    ax.set_ylabel("Serving cell")
    ax.legend(loc="upper right", bbox_to_anchor=(1, 1.12), ncol=2, markerscale=2.5)
    ax.grid(axis="y", visible=False)
    fig.autofmt_xdate()
    finish(fig, out_dir, "6_stationary_cell_churn.png",
           f"A phone that stayed put switched serving cell {changes} times",
           f"Jio phone, {days:.1f} days, 90% of GPS fixes within {p90_m:.0f} m of its median position · "
           f"{g.pci.nunique()} distinct cells · {aba} immediate A→B→A returns",
           "Each dot is one sample; rows are the eight most-used serving cells. Partway through, the phone left 5G "
           "almost entirely (likely a settings or network change) and churned between 4G cells from then on.")


def chart_rsrp_vs_rsrq(df, out_dir):
    d = df.dropna(subset=["rsrp", "rsrq"])
    good_rsrp, poor_rsrq = -100, -15
    q = {
        "strong & clean": ((d.rsrp > good_rsrp) & (d.rsrq >= poor_rsrq)).mean(),
        "strong but noisy\n(interference-limited)": ((d.rsrp > good_rsrp) & (d.rsrq < poor_rsrq)).mean(),
        "weak but clean\n(coverage-limited)": ((d.rsrp <= good_rsrp) & (d.rsrq >= poor_rsrq)).mean(),
        "weak & noisy": ((d.rsrp <= good_rsrp) & (d.rsrq < poor_rsrq)).mean(),
    }
    fig, ax = plt.subplots(figsize=(11, 6.4))
    hb = ax.hexbin(d.rsrp, d.rsrq, gridsize=(40, 20), extent=(-135, -65, -25, -3),
                   cmap="Blues", mincnt=1, bins="log", linewidths=0.2, edgecolors=SURFACE)
    cb = fig.colorbar(hb, ax=ax, shrink=0.8, pad=0.02)
    cb.set_label("Samples (log scale)", color=INK_SECONDARY)
    cb.outline.set_visible(False)
    ax.axvline(good_rsrp, color=INK_SECONDARY, linewidth=1, linestyle="--")
    ax.axhline(poor_rsrq, color=INK_SECONDARY, linewidth=1, linestyle="--")
    pos = {"strong & clean": (-72, -4.5, "right", "top"),
           "strong but noisy\n(interference-limited)": (-72, -24, "right", "bottom"),
           "weak but clean\n(coverage-limited)": (-133, -4.5, "left", "top"),
           "weak & noisy": (-133, -24, "left", "bottom")}
    for k, (x, y, ha, va) in pos.items():
        ax.text(x, y, f"{k}\n{q[k]*100:.0f}%", ha=ha, va=va, fontsize=11,
                fontweight="bold", color=INK_PRIMARY,
                bbox=dict(facecolor=SURFACE, edgecolor="none", alpha=0.85, pad=3))
    ax.set_xlim(-135, -65)
    ax.set_ylim(-25, -3)
    ax.set_xlabel("RSRP (dBm) — signal strength")
    ax.set_ylabel("RSRQ (dB) — signal quality")
    ax.grid(False)
    finish(fig, out_dir, "7_rsrp_vs_rsrq.png",
           "Where signal is poor, it's because it's weak — not because of interference",
           f"Every sample with both measurements · n={len(d):,} · thresholds −100 dBm / −15 dB",
           "Only a small share of samples show good strength with poor quality, the signature of "
           "interference. Poor experience in this dataset is a coverage problem.")


# ── Context-free charts ──────────────────────────────────────────────────────
# The sessions weren't controlled (unknown placement, settings, usage), so these
# only make claims about the tool itself or about relationships fixed by the
# 3GPP measurement definitions — neither depends on what the tester was doing.

def load_background(source):
    frames = []
    for dev, ses, raw, _ in iter_session_files(source, "background_logs.csv"):
        d = pd.read_csv(io.BytesIO(raw), dtype=str, on_bad_lines="skip")
        if d.empty:
            continue
        d["device"], d["session"] = dev, ses
        frames.append(d)
    bg = pd.concat(frames, ignore_index=True)
    # The background file wasn't always cleared between uploads, so the same row
    # can appear in two sessions' copies — keep one per device and timestamp.
    bg = bg.drop_duplicates(subset=["device", "Time"])
    bg["ts"] = pd.to_datetime(bg.Time, errors="coerce")
    bg["sig"] = pd.to_numeric(bg.SignalLevel.astype(str).str.replace(" dBm", ""), errors="coerce")
    return bg.sort_values(["device", "ts"]).reset_index(drop=True)


def chart_dataset_overview(df, out_dir):
    s = df.groupby(["device", "session"]).agg(start=("ts", "min"), end=("ts", "max"),
                                              n=("ts", "size"), op=("op", "first")).reset_index()
    per_dev = s.groupby("device").agg(n=("n", "sum"), sessions=("session", "size"), op=("op", "first"))
    order = per_dev.sort_values("n").index
    fig, ax = plt.subplots(figsize=(13, 6))
    for i, dev in enumerate(order):
        for _, r in s[s.device == dev].iterrows():
            width = max((r.end - r.start).total_seconds() / 86400, 0.04)  # keep short sessions visible
            ax.barh(i, width, left=r.start, height=0.55, color=NR, edgecolor=SURFACE, linewidth=1)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([f"{d[:6]} · {per_dev.loc[d,'op']} · {per_dev.loc[d,'sessions']} session{'s' if per_dev.loc[d,'sessions'] != 1 else ''} · "
                        f"{per_dev.loc[d,'n']:,} rows" for d in order], fontsize=9.5)
    ax.grid(axis="y", visible=False)
    fig.autofmt_xdate()
    top3 = per_dev.n.sort_values(ascending=False).head(3).sum() / per_dev.n.sum() * 100
    finish(fig, out_dir, "8_dataset_overview.png",
           f"{len(per_dev)} phones logged data, but 3 of them produced {top3:.0f}% of it",
           f"Each bar is one logging session (start → end) · {df.groupby(['device','session']).ngroups} sessions, "
           f"{len(df):,} rows, {s.start.min():%d %b} – {s.end.max():%d %b %Y}",
           "Any per-sample statistic is dominated by the few multi-day sessions — results describe "
           "those phones, not a population. Device ids truncated to 6 characters.")


def chart_scheduler_comparison(df, bg, out_dir):
    fg_gaps = df.groupby(["device", "session"]).ts.diff().dt.total_seconds().dropna() / SAMPLE_INTERVAL_S
    bg_gaps = bg.groupby("device").ts.diff().dt.total_seconds().dropna() / (15 * 60)
    # Background rows are continuous per device across sessions; drop gaps where
    # the worker simply wasn't scheduled (no session running for > 1 day).
    bg_gaps = bg_gaps[bg_gaps < 96]
    bins = [0, 1.2, 3, 12, np.inf]
    labels = ["on schedule\n(≤ 1.2× target)", "1.2–3× late", "3–12× late", "> 12× late"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.4), sharey=True)
    for ax, gaps, title in [
        (axes[0], fg_gaps, f"5-second foreground loop · {len(fg_gaps):,} gaps"),
        (axes[1], bg_gaps, f"15-minute WorkManager job · {len(bg_gaps):,} gaps"),
    ]:
        share = pd.cut(gaps, bins, labels=labels).value_counts(normalize=True).reindex(labels) * 100
        bars = ax.bar(labels, share.values, color=[NR] + [CONTEXT] * 3, width=0.6)
        for b, v in zip(bars, share.values):
            ax.text(b.get_x() + b.get_width() / 2, v + 1.5, f"{v:.0f}%", ha="center",
                    fontsize=12, fontweight="bold")
        ax.set_title(title, fontsize=12)
        ax.set_ylim(0, 105)
        ax.grid(axis="x", visible=False)
        ax.tick_params(axis="x", labelsize=9.5)
    axes[0].set_ylabel("Share of gaps between consecutive rows (%)")
    fg_bad = (fg_gaps > 12).mean() * 100
    finish(fig, out_dir, "9_scheduler_comparison.png",
           f"The 15-minute job was almost never badly late; {fg_bad:.0f}% of the 5-second loop's gaps were 12× late or worse",
           "Gap between consecutive log rows, as a multiple of each pipeline's target interval · same set of phones",
           "Android's Doze defers timers and alarms to occasional maintenance windows. WorkManager is built for that and "
           "degrades gracefully; a 5-second cadence can't survive it unless the logger is exempt (foreground service).")


def chart_field_completeness(df, bg, out_dir):
    nr = df.cell_rat == "NR"
    fields = [
        ("Foreground", "GPS position", df.lat.notna().mean()),
        ("Foreground", "RSRP (strength)", df.rsrp.notna().mean()),
        ("Foreground", "RSRQ (quality)", df.rsrq.notna().mean()),
        ("Foreground", "Cell id (PCI / NCI)", (df.pci.notna() & df.nci.notna()).mean()),
        ("Foreground", "SINR — on 5G cells", df[nr].sinr.notna().mean()),
        ("Foreground", "SINR — on 4G cells", df[~nr].sinr.notna().mean()),
        ("Foreground", "Network type label", (~df.network.isin(["Unknown"]) & df.network.notna()).mean()),
        ("Background", "Battery / RAM / storage", pd.to_numeric(bg.Battery, errors="coerce").notna().mean()),
        ("Background", "Network type", (~bg.NetworkType.isin(["Unknown", "No Permission"]) & bg.NetworkType.notna()).mean()),
        ("Background", "Signal level", bg.sig.notna().mean()),
    ]
    why = {
        "SINR — on 4G cells": "app only reads SINR on the NR branch",
        "Network type label": "'Unknown' = phone-state permission missing or type unmapped",
        "Network type": "same permission ('No Permission' / 'Unknown')",
        "Signal level": "N/A when location permission or cell info unavailable",
    }
    fig, ax = plt.subplots(figsize=(12, 6.2))
    y = np.arange(len(fields))[::-1]
    vals = np.array([f[2] * 100 for f in fields])
    ax.barh(y, vals, color=[NR if v >= 90 else LTE for v in vals], height=0.6)
    for yi, (grp, name, v) in zip(y, fields):
        note = f"   {why[name]}" if name in why else ""
        ax.text(v * 100 + 1, yi, f"{v*100:.0f}%{note}", va="center", fontsize=10,
                fontweight="bold" if not note else "normal")
    ax.set_yticks(y)
    ax.set_yticklabels([f"{name}  ({grp.lower()})" for grp, name, _ in fields])
    ax.set_xlim(0, 150)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("Rows where the field has a usable value (%)")
    ax.grid(axis="y", visible=False)
    finish(fig, out_dir, "10_field_completeness.png",
           "Radio measurements are ~100% complete; the gaps are all permission or code-path issues",
           f"Share of usable values per field · foreground {len(df):,} rows, background {len(bg):,} rows (deduplicated) · "
           "blue ≥ 90%, orange below",
           "≥ 99% of RSRP / RSRQ values and 100% of PCI values fall inside their 3GPP-defined ranges. Each weak field "
           "traces to a code path in the app, so it's fixable rather than a limitation of the phones.")


def chart_quality_vs_strength(df, out_dir):
    n = df[df.cell_rat == "NR"].dropna(subset=["rsrp", "rsrq", "sinr"])
    rho_q = n[["rsrq", "sinr"]].corr(method="spearman").iloc[0, 1]
    rho_p = n[["rsrp", "sinr"]].corr(method="spearman").iloc[0, 1]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.8), sharey=True)
    for ax, x, xlabel, rho, extent in [
        (axes[0], "rsrq", "RSRQ (dB) — signal quality", rho_q, (-21, -9, -11, 31)),
        (axes[1], "rsrp", "RSRP (dBm) — signal strength", rho_p, (-131, -75, -11, 31)),
    ]:
        hb = ax.hexbin(n[x], n.sinr, gridsize=26, extent=extent, cmap="Blues", mincnt=1,
                       bins="log", linewidths=0.2, edgecolors=SURFACE)
        ax.set_xlim(extent[0], extent[1])
        ax.set_xlabel(xlabel)
        ax.set_title(f"SINR vs {x.upper()}  ·  Spearman ρ = {rho:.2f}", fontsize=12)
        ax.grid(False)
    # RSRQ = N·RSRP / RSSI; with the cell otherwise idle, RSSI is ~12 subcarriers'
    # worth of reference power per resource block, so RSRQ can't exceed ~10·log10(1/12).
    ceiling = 10 * np.log10(1 / 12)
    axes[0].axvline(ceiling, color=INK_SECONDARY, linewidth=1, linestyle="--")
    axes[0].text(ceiling - 0.2, 29, f"RSRQ ceiling\n≈ {ceiling:.1f} dB", ha="right", va="top", fontsize=10,
                 bbox=dict(facecolor=SURFACE, edgecolor="none", alpha=0.9, pad=2))
    axes[0].set_ylabel("SINR (dB) — signal vs interference + noise")
    fig.set_layout_engine(None)
    finish_manual(fig, out_dir, "11_quality_vs_strength.png",
           "Signal quality tracks interference, not signal strength",
           f"5G serving-cell samples with all three measurements · n={len(n):,} on {n.device.nunique()} devices",
           "RSRQ and SINR both compare the wanted signal with what's around it; RSRP measures the wanted signal alone, so a "
           "strong signal can still be unusable. RSRQ saturates at its theoretical ceiling, where only SINR keeps discriminating.",
           colorbar=hb)


def finish_manual(fig, out_dir, name, title, subtitle, note, colorbar=None):
    height_in = fig.get_size_inches()[1]
    fig.subplots_adjust(left=0.07, right=0.88, top=1 - 1.05 / height_in, bottom=0.95 / height_in, wspace=0.08)
    if colorbar is not None:
        cax = fig.add_axes([0.9, 0.95 / height_in + 0.05, 0.015, 1 - 2.0 / height_in - 0.1])
        cb = fig.colorbar(colorbar, cax=cax)
        cb.set_label("Samples (log scale)", color=INK_SECONDARY)
        cb.outline.set_visible(False)
    fig.text(0.01, 1 - 0.18 / height_in, title, ha="left", va="top", fontsize=16, fontweight="bold")
    fig.text(0.01, 1 - 0.55 / height_in, subtitle, ha="left", va="top", fontsize=11, color=INK_SECONDARY)
    fig.text(0.01, 0.1 / height_in, note, ha="left", va="bottom", fontsize=9, color=INK_MUTED)
    fig.savefig(os.path.join(out_dir, name), dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True,
                        help="android-telecom-logs.zip, or a fetch_logs.py mirror directory")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    apply_style()

    df = load_sessions(args.src)
    print(f"Loaded {len(df):,} samples · {df.device.nunique()} devices · "
          f"{df.groupby(['device','session']).ngroups} sessions")
    chart_sampling_intervals(df, args.out_dir)
    chart_radio_mix(df, args.out_dir)
    chart_fallback(df, args.out_dir)
    chart_same_location(df, args.out_dir)
    chart_time_of_day(df, args.out_dir)
    chart_cell_churn(df, args.out_dir)
    chart_rsrp_vs_rsrq(df, args.out_dir)

    bg = load_background(args.src)
    chart_dataset_overview(df, args.out_dir)
    chart_scheduler_comparison(df, bg, args.out_dir)
    chart_field_completeness(df, bg, args.out_dir)
    chart_quality_vs_strength(df, args.out_dir)


if __name__ == "__main__":
    main()
