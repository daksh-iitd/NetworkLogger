"""
Charts for the controlled Jio-vs-Vi experiment (Sep 2026, hostel table).

Setup (Experiment/scripts/masterScript.sh): two identical OnePlus 11R phones
(CPH2487, Android 14), one Jio SIM and one Vi SIM, side by side on a table indoors.
Each run, per phone, 30 s apart: start NetworkLogger → ndt7 download + upload
against M-Lab del02 → 300 s emulated video call (dummyConference.py) → stop.

Because location, hardware, time and offered traffic are held fixed, differences
between the phones within a run are attributable to the operator's network.

Writes to experiment/:
    12_one_paired_run.png          - what one run looks like on both phones
    13_paired_scoreboard.png       - ndt7 peaks and call uplink, run by run
    14_jio_cell_tradeoff.png       - Jio's serving cell decided which link worked

Usage:
    ./venv/bin/python code/make_experiment_charts.py \
        --src ../grafana_pipeline/firebase_csv_mirror --out-dir experiment
"""

import argparse
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from make_research_charts import (CONTEXT, GRID, INK_MUTED, INK_PRIMARY, INK_SECONDARY, LTE, NR,
                                  SURFACE, apply_style, finish, haversine_m, load_sessions)

JIO_DEVICE = "22c7af7602d27af4"
VI_DEVICE = "c176d0f3ae801a6d"
TABLE = (28.5487638, 77.1834913)   # median position of the co-located samples
JIO, VI = NR, LTE                  # Jio ran 5G in 14/17 runs, Vi was 4G throughout

NDT7_END_S = 60                    # ndt7 download + upload finish within the first minute
CALL_START_S, CALL_END_S = 70, 360 # 300 s call, with margin for app start/stop taps
CALL_UL_KBPS = 4000                # the call offers ~4.6 Mbps up; "held" = at least 4 Mbps
RUN_GAP_S = 60                     # consecutive samples > 60 s apart start a new run

# Jio's serving cells, from the NCI/PCI of each run (see chart 14)
CELL_GROUPS = {
    "weak 5G cells\n(PCI 174 / 35)": "weak5g",
    "strong 5G cell\n(PCI 319)": "strong5g",
    "4G cells\n(PCI 25 / 114)": "lte",
}


# ── Loading ──────────────────────────────────────────────────────────────────

def load_paired_runs(src):
    df = load_sessions(src)
    w = df[df.device.isin([JIO_DEVICE, VI_DEVICE])].copy()
    w["phone"] = np.where(w.device == JIO_DEVICE, "Jio", "Vi")
    # A run whose upload didn't finish before the script force-stopped the app is
    # re-uploaded inside the next session, so rows repeat across session files.
    w = w.sort_values("session").drop_duplicates(subset=["device", "ts"], keep="first")
    w = w[(haversine_m(w.lat, w.lon, *TABLE) < 50) & (w.ts >= "2026-09-15")]
    w = w.sort_values(["phone", "ts"])

    gap = w.groupby("phone").ts.diff().dt.total_seconds()
    w["run"] = (gap.isna() | (gap > RUN_GAP_S)).groupby(w.phone).cumsum()
    w["t"] = (w.ts - w.groupby(["phone", "run"]).ts.transform("min")).dt.total_seconds()
    runs = w.groupby(["phone", "run"]).agg(start=("ts", "min"), end=("ts", "max"))
    runs["minutes"] = (runs.end - runs.start).dt.total_seconds() / 60

    # Pair each complete Jio run with the Vi run the master script started ~30 s later
    jio, vi = runs.loc["Jio"].reset_index(), runs.loc["Vi"].reset_index()
    pairs = []
    for j in jio.itertuples():
        v = vi[(vi.start - j.start).dt.total_seconds().abs() < 120]
        if len(v) and 6 <= j.minutes <= 7 and 6 <= v.iloc[0].minutes <= 7:
            pairs.append({"pair": len(pairs) + 1, "Jio": j.run, "Vi": v.iloc[0].run, "start": j.start})
    pairs = pd.DataFrame(pairs)

    key = {("Jio", r.Jio): r.pair for r in pairs.itertuples()} | {("Vi", r.Vi): r.pair for r in pairs.itertuples()}
    w["pair"] = [key.get(k) for k in zip(w.phone, w.run)]
    w = w.dropna(subset=["pair"]).astype({"pair": int})
    w["phase"] = np.select([w.t < NDT7_END_S, (w.t >= CALL_START_S) & (w.t <= CALL_END_S)],
                           ["ndt7", "call"], "other")
    return w, pairs, len(runs.loc["Jio"]), len(runs.loc["Vi"])


def per_run_metrics(w):
    def metrics(g):
        ndt, call = g[g.phase == "ndt7"], g[g.phase == "call"]
        return pd.Series({
            "dl_peak": ndt.dlKbps.max() / 1000,
            "ul_peak": ndt.ulKbps.max() / 1000,
            "call_ul_held": (call.ulKbps >= CALL_UL_KBPS).mean() * 100,
            "rsrp": g.rsrp.median(),
            "pci": g.pci.mode().iloc[0],
            "rat": g.cell_rat.mode().iloc[0],
        })
    m = w.groupby(["pair", "phone"]).apply(metrics).unstack()
    jio_cell = np.where(m[("rat", "Jio")] == "LTE", "lte",
                np.where(m[("pci", "Jio")] == 319, "strong5g", "weak5g"))
    m[("cell", "Jio")] = jio_cell
    return m


# ── Charts ───────────────────────────────────────────────────────────────────

def chart_one_run(w, out_dir, pair_no):
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    for ax, col, label in [(axes[0], "dlKbps", "Download (Mbps)"), (axes[1], "ulKbps", "Upload (Mbps)")]:
        ax.axvspan(0, NDT7_END_S, color=CONTEXT, alpha=0.25, linewidth=0)
        ax.axvspan(CALL_START_S, CALL_END_S, color=CONTEXT, alpha=0.10, linewidth=0)
        for phone, c in [("Jio", JIO), ("Vi", VI)]:
            g = w[(w.pair == pair_no) & (w.phone == phone)]
            ax.plot(g.t, (g[col] / 1000).clip(lower=0.01), color=c, linewidth=2, label=phone)
        ax.set_yscale("log")
        ax.set_ylim(0.01, 300)
        ax.set_yticks([0.1, 1, 10, 100])
        ax.set_yticklabels(["0.1", "1", "10", "100"])
        ax.set_ylabel(label)
    axes[0].text(NDT7_END_S / 2, 180, "ndt7 speed test", ha="center", fontsize=10.5, fontweight="bold")
    axes[0].text((CALL_START_S + CALL_END_S) / 2, 180, "300 s emulated video call", ha="center",
                 fontsize=10.5, fontweight="bold")
    axes[1].axhline(CALL_UL_KBPS / 1000, color=INK_SECONDARY, linewidth=1, linestyle="--")
    axes[1].text(CALL_END_S - 2, CALL_UL_KBPS / 1000 * 1.25, "call needs ~4.6 Mbps up", ha="right",
                 fontsize=9.5, color=INK_SECONDARY)
    axes[0].legend(loc="lower right", ncol=2)
    axes[1].set_xlabel("Seconds since the run started")
    axes[1].set_xlim(0, 380)
    start = w[w.pair == pair_no].ts.min()
    finish(fig, out_dir, "12_one_paired_run.png",
           "One experiment run: same table, same phone model, same test — different operator",
           f"Run {pair_no} · {start:%d %b %H:%M} · both phones run the identical script 30 s apart "
           "(aligned here at t = 0)",
           "Throughput is the app's 5-second traffic counter, so ndt7 peaks are 5-s averages of a ~10 s test. "
           "The call paces its own download, so both phones match there; the uplink is where they differ.")


def dumbbell(ax, m, metric, xlabel, log=False):
    order = m.index[::-1]
    y = np.arange(len(order))
    jv, vv = m.loc[order, (metric, "Jio")].values, m.loc[order, (metric, "Vi")].values
    for yi, a, b in zip(y, jv, vv):
        ax.plot([a, b], [yi, yi], color=GRID, linewidth=2.5, zorder=1)
    ax.scatter(vv, y, color=VI, s=55, zorder=2, label="Vi", edgecolor=SURFACE, linewidth=1.5)
    ax.scatter(jv, y, color=JIO, s=55, zorder=3, label="Jio", edgecolor=SURFACE, linewidth=1.5)
    ax.set_yticks(y)
    ax.set_yticklabels([f"run {p}" for p in order], fontsize=9)
    ax.set_xlabel(xlabel)
    if log:
        ax.set_xscale("log")
    ax.grid(axis="y", visible=False)
    med_j, med_v = np.median(jv), np.median(vv)
    ax.set_title(f"median  Jio {med_j:.3g}  ·  Vi {med_v:.3g}", fontsize=11, fontweight="normal",
                 color=INK_SECONDARY)


def chart_scoreboard(m, out_dir):
    fig, axes = plt.subplots(1, 3, figsize=(14, 7.2), sharey=True)
    dumbbell(axes[0], m, "dl_peak", "ndt7 download peak (Mbps, log)", log=True)
    dumbbell(axes[1], m, "ul_peak", "ndt7 upload peak (Mbps, log)", log=True)
    dumbbell(axes[2], m, "call_ul_held", "Call uplink held ≥ 4 Mbps (% of call)")
    axes[2].set_xlim(-5, 105)
    for ax, t in zip(axes, ["Speed test · download", "Speed test · upload", "Video call · upload"]):
        ax.text(0, 1.07, t, transform=ax.transAxes, fontsize=12.5, fontweight="bold")
    axes[2].legend(loc="lower right", bbox_to_anchor=(1, 1.1), ncol=2)
    held_vi = (m[("call_ul_held", "Vi")] >= 90).sum()
    held_jio = (m[("call_ul_held", "Jio")] >= 90).sum()
    faster_dl = (m[("dl_peak", "Vi")] > m[("dl_peak", "Jio")]).sum()
    finish(fig, out_dir, "13_paired_scoreboard.png",
           f"Vi held the video call's uplink in {held_vi} of {len(m)} runs; Jio in {held_jio}",
           f"{len(m)} paired runs, 21–23 Sep, same table · Vi also had the faster speed-test download "
           f"in {faster_dl} of {len(m)} runs · each row is one run, both phones",
           "ndt7 peaks come from the app's 5-second traffic counter (approximate; ndt7's own result files are the "
           "ground truth). Jio's spread is not noise — it tracks which cell served it (next chart).")


def chart_cell_tradeoff(m, out_dir):
    jm = pd.DataFrame({
        "rsrp": m[("rsrp", "Jio")], "dl": m[("dl_peak", "Jio")],
        "held": m[("call_ul_held", "Jio")], "cell": m[("cell", "Jio")],
    })
    markers = {"weak5g": ("o", NR), "strong5g": ("s", NR), "lte": ("^", LTE)}
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.8), sharex=True)
    for label, key in CELL_GROUPS.items():
        g = jm[jm.cell == key]
        mk, c = markers[key]
        filled = key != "strong5g"
        for ax, col in [(axes[0], "dl"), (axes[1], "held")]:
            ax.scatter(g.rsrp, g[col], marker=mk, s=90, linewidth=2, zorder=3,
                       facecolor=c if filled else SURFACE, edgecolor=c,
                       label=f"{label.replace(chr(10), ' ')} · {len(g)} runs")
    axes[0].set_yscale("log")
    axes[0].set_yticks([1, 3, 10, 30, 100])
    axes[0].set_yticklabels(["1", "3", "10", "30", "100"])
    axes[0].set_ylabel("ndt7 download peak (Mbps, log)")
    axes[0].set_title("Speed-test download", fontsize=12)
    axes[1].set_ylabel("Call uplink held ≥ 4 Mbps (% of call)")
    axes[1].set_ylim(-5, 105)
    axes[1].set_title("Video-call uplink", fontsize=12)
    for ax in axes:
        ax.set_xlabel("Jio serving-cell RSRP during the run (dBm)")
        ax.invert_xaxis()
    axes[1].legend(loc="center left", fontsize=9.5)
    finish(fig, out_dir, "14_jio_cell_tradeoff.png",
           "On the same table, Jio's serving cell decided whether download or upload worked",
           "Jio phone only, one point per run · the weak-signal 5G cells gave fast downloads but couldn't sustain "
           "uplink; the strong-signal cell did the reverse",
           "Consistent with a mid-band (wide, weaker indoors) vs low-band (narrow, penetrates walls) split — uplink "
           "fails first because a phone transmits at ~0.2 W vs a tower's tens of watts. The app doesn't log NR-ARFCN, "
           "so the bands can't be confirmed from this data.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    apply_style()

    w, pairs, n_jio, n_vi = load_paired_runs(args.src)
    print(f"Runs at the table: Jio {n_jio}, Vi {n_vi} · complete paired runs: {len(pairs)}")
    m = per_run_metrics(w)
    chart_one_run(w, args.out_dir, pair_no=3)
    chart_scoreboard(m, args.out_dir)
    chart_cell_tradeoff(m, args.out_dir)
    m.round(2).to_csv(os.path.join(args.out_dir, "paired_runs.csv"))
    print("  wrote paired_runs.csv")


if __name__ == "__main__":
    main()
