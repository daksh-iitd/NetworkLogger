"""
Cross-operator comparisons that the current data supports, restricted to places both
operators logged (100 m squares with ≥ 10 samples each) or to moments a Jio and a Vi
phone were carried together.

    20_band_strategy.png         - which bands each operator served in the same squares
    21_coverage_probability.png  - share of time above −100 dBm, square by square
    22_walk_together.png         - the Oct 8 walk with both phones: signal and cell changes

Usage:
    ./venv/bin/python code/make_cross_operator_charts.py \
        --src ../grafana_pipeline/firebase_csv_mirror --out-dir campus --since 2026-09-28
"""

import argparse
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from make_all_logs_map import load_points
from make_campus_charts import BAND_CLASS, BAND_FREQ, MIN_SAMPLES, band_class
from make_research_charts import (CONTEXT, GRID, INK_MUTED, INK_PRIMARY, INK_SECONDARY, LTE, NR, SURFACE,
                                  apply_style, finish, haversine_m)

JIO, VI = NR, LTE                  # same operator colours as the table-experiment charts
SQUARE_M = 100
USABLE_DBM = -100
WALK_DAY = "2026-10-08"            # the one long walk with a Jio and a Vi phone carried together
PAIR_S, PAIR_M = 10, 50
CLASS_ORDER = ["low", "mid", "high"]


def shared_squares(df):
    d = df.dropna(subset=["rsrp"]).copy()
    d["cx"], d["cy"] = (d.x // SQUARE_M).astype(int), (d.y // SQUARE_M).astype(int)
    per = d.groupby(["cx", "cy", "op"]).size().unstack(fill_value=0)
    keep = per[(per.Jio >= MIN_SAMPLES) & (per.Vi >= MIN_SAMPLES)].index
    return d.set_index(["cx", "cy"]).loc[keep].reset_index(), len(keep)


# ── 20: band strategy ───────────────────────────────────────────────────────

def chart_band_strategy(s, n_sq, out_dir):
    s = s[s.band_class.notna()]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(14, 5.6), gridspec_kw=dict(width_ratios=[1.3, 1]))

    for row, op in enumerate(["Jio", "Vi"]):
        d = s[s.op == op]
        share = d.band.value_counts(normalize=True) * 100
        left = 0
        for cls in CLASS_ORDER:
            bands, color, _ = BAND_CLASS[cls]
            for band in [b for b in bands if b in share.index]:
                w = share[band]
                ax.barh(row, w, left=left, color=color, height=0.55, edgecolor=SURFACE, linewidth=2)
                if w >= 6:
                    ax.text(left + w / 2, row, f"{band}\n{w:.0f}%", ha="center", va="center", color="white",
                            fontsize=10, fontweight="bold")
                left += w
    ax.set_yticks([0, 1])
    ax.set_yticklabels([f"Jio\n{(s.op == 'Jio').sum():,} samples", f"Vi\n{(s.op == 'Vi').sum():,} samples"])
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of samples (%)")
    ax.grid(axis="y", visible=False)
    ax.set_title("Bands serving the phones", fontsize=12)
    handles = [plt.Rectangle((0, 0), 1, 1, color=BAND_CLASS[c][1], label=BAND_CLASS[c][2]) for c in CLASS_ORDER]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3, fontsize=9.5)

    med = s.groupby(["op", "band"]).rsrp.agg(["median", "size"]).query("size >= 50").reset_index()
    med["freq"] = med.band.map(lambda b: int(BAND_FREQ[b].split()[0]))
    med = med.sort_values(["op", "freq"])
    ylabels = []
    for i, r in enumerate(med.itertuples()):
        color = BAND_CLASS[band_class(r.band)][1]
        ax2.scatter(r.median, i, s=90, color=color, edgecolor=INK_PRIMARY if r.op == "Jio" else SURFACE,
                    linewidth=1.2, zorder=3)
        ax2.text(r.median + 0.8, i, f"{r.median:.0f}", va="center", fontsize=10)
        ylabels.append(f"{r.op} {r.band} ({BAND_FREQ[r.band]}) · n={r.size:,}")
    ax2.axvline(USABLE_DBM, color=INK_MUTED, linewidth=1, linestyle="--")
    ax2.set_yticks(range(len(med)))
    ax2.set_yticklabels(ylabels, fontsize=9.5)
    ax2.invert_yaxis()
    ax2.set_xlabel("Median RSRP in the shared squares (dBm)")
    ax2.grid(axis="y", visible=False)
    ax2.set_title("Signal on each band, same squares", fontsize=12)

    jio_high = (s[s.op == "Jio"].band_class == "high").mean() * 100
    vi_low_mid = s[s.op == "Vi"].band_class.isin(["low", "mid"]).mean() * 100
    finish(fig, out_dir, "20_band_strategy.png",
           f"Same places, different strategy: Jio rode 3.5 GHz 5G {jio_high:.0f}% of the time; "
           f"Vi stayed on 900/1800 MHz 4G {vi_low_mid:.0f}%",
           f"Only the {n_sq} squares ({SQUARE_M} m) where both operators logged ≥ {MIN_SAMPLES} samples · "
           "bands as reported by each phone",
           "Bands with fewer than 50 samples are left out of the right panel. Jio's side is a single phone, so "
           "its band mix describes that phone's time in these squares.")


# ── 21: coverage probability ────────────────────────────────────────────────

def chart_coverage(s, n_sq, out_dir):
    cov = s.groupby(["cx", "cy", "op"]).rsrp.apply(lambda x: (x > USABLE_DBM).mean() * 100).unstack()
    cov = cov.sort_values("Jio")
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(14, 6.4), gridspec_kw=dict(width_ratios=[1.4, 1]))

    y = np.arange(len(cov))
    for yi, (j, v) in enumerate(zip(cov.Jio, cov.Vi)):
        ax.plot([j, v], [yi, yi], color=GRID, linewidth=2.5, zorder=1)
    ax.scatter(cov.Vi, y, color=VI, s=55, zorder=2, label="Vi", edgecolor=SURFACE, linewidth=1.2)
    ax.scatter(cov.Jio, y, color=JIO, s=55, zorder=3, label="Jio", edgecolor=SURFACE, linewidth=1.2)
    ax.set_yticks([])
    ax.set_xlim(-3, 103)
    ax.set_xlabel(f"Samples above {USABLE_DBM} dBm in the square (%)")
    ax.set_ylabel(f"Each row = one shared {SQUARE_M} m square (sorted by Jio)")
    ax.legend(loc="lower right")
    ax.grid(axis="y", visible=False)
    ax.set_title("Square by square", fontsize=12)

    bins = [-0.1, 25, 75, 100]
    labels = ["mostly weak\n(< 25% usable)", "mixed\n(25–75%)", "mostly usable\n(> 75%)"]
    counts = pd.DataFrame({op: pd.cut(cov[op], bins, labels=labels).value_counts().reindex(labels)
                           for op in ["Jio", "Vi"]})
    x = np.arange(len(labels))
    ax2.bar(x - 0.18, counts.Jio, width=0.36, color=JIO, label="Jio")
    ax2.bar(x + 0.18, counts.Vi, width=0.36, color=VI, label="Vi")
    for xi, (a, b) in enumerate(zip(counts.Jio, counts.Vi)):
        ax2.text(xi - 0.18, a + 0.2, str(a), ha="center", fontsize=11, fontweight="bold")
        ax2.text(xi + 0.18, b + 0.2, str(b), ha="center", fontsize=11, fontweight="bold")
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, fontsize=10)
    ax2.set_ylabel("Number of squares")
    ax2.grid(axis="x", visible=False)
    ax2.set_title("How the squares fall", fontsize=12)

    finish(fig, out_dir, "21_coverage_probability.png",
           f"Jio is all-or-nothing; Vi is rarely unusable — across squares, Vi was usable "
           f"{cov.Vi.mean():.0f}% of the time vs Jio {cov.Jio.mean():.0f}%",
           f"Share of samples above {USABLE_DBM} dBm in each of the {n_sq} squares both operators logged "
           f"(≥ {MIN_SAMPLES} samples each) · every square weighted equally",
           "Vi's misses mostly come from its 2.5 GHz B41 layer (chart 20). Jio's values are mostly 5G SS-RSRP, which "
           "reads a few dB below LTE RSRP, so the same threshold is slightly harsher on Jio.")


# ── 22: the walk with both phones ───────────────────────────────────────────

def walk_pairs(df):
    j = df[(df.op == "Jio") & (df.ts.dt.date.astype(str) == WALK_DAY)].sort_values("ts")
    v = df[(df.op == "Vi") & (df.ts.dt.date.astype(str) == WALK_DAY)].sort_values("ts")
    m = pd.merge_asof(j, v[["ts", "lat", "lon", "rsrp", "band", "pci", "model"]], on="ts",
                      tolerance=pd.Timedelta(f"{PAIR_S}s"), direction="nearest", suffixes=("_j", "_v"))
    m = m.dropna(subset=["lat_v", "rsrp_v"])
    return m[haversine_m(m.lat_j, m.lon_j, m.lat_v, m.lon_v) < PAIR_M].sort_values("ts").reset_index(drop=True)


def chart_walk(df, out_dir):
    m = walk_pairs(df)
    seg = (m.ts.diff().dt.total_seconds() > 60).cumsum()
    km, changes = 0.0, {"Jio": 0, "Vi": 0}
    for _, h in m.groupby(seg):
        step = haversine_m(h.lat_j.values[1:], h.lon_j.values[1:], h.lat_j.values[:-1], h.lon_j.values[:-1])
        km += step[step < 150].sum() / 1000
        changes["Jio"] += int((h.pci_j.diff().fillna(0) != 0).sum())
        changes["Vi"] += int((h.pci_v.diff().fillna(0) != 0).sum())

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(14, 5.6), gridspec_kw=dict(width_ratios=[2.2, 1]))
    m["minute"] = (m.ts - m.ts.min()).dt.total_seconds() / 60
    for col, op, c in [("rsrp_j", "Jio", JIO), ("rsrp_v", "Vi", VI)]:
        ax.scatter(m.minute, m[col], s=12, color=c, alpha=0.75, linewidths=0, label=op)
    ax.axhline(USABLE_DBM, color=INK_MUTED, linewidth=1, linestyle="--")
    ax.set_xlabel("Minutes since the walk started (gaps = phones not logging together)")
    ax.set_ylabel("Serving-cell RSRP (dBm)")
    ax.legend(loc="lower right", markerscale=2.5)
    ax.set_title(f"RSRP at the same moments · {len(m)} paired samples", fontsize=12)

    per_km = {op: changes[op] / km for op in changes}
    ax2.bar(["Jio", "Vi"], [per_km["Jio"], per_km["Vi"]], color=[JIO, VI], width=0.55)
    for i, op in enumerate(["Jio", "Vi"]):
        ax2.text(i, per_km[op] + 0.4, f"{per_km[op]:.0f}/km\n({changes[op]} changes)", ha="center",
                 fontsize=11, fontweight="bold")
    ax2.set_ylabel("Serving-cell changes per km")
    ax2.set_ylim(0, max(per_km.values()) * 1.3)
    ax2.grid(axis="x", visible=False)
    ax2.set_title(f"Cell changes over ~{km:.1f} km", fontsize=12)

    weak_j, weak_v = (m.rsrp_j < USABLE_DBM).mean() * 100, (m.rsrp_v < USABLE_DBM).mean() * 100
    ratio = per_km["Jio"] / per_km["Vi"]
    finish(fig, out_dir, "22_walk_together.png",
           f"Walking together, Jio changed cell {ratio:.1f}× as often as Vi; both were weak about half the time",
           f"{WALK_DAY} · Jio ({m.model_j.iloc[0]}) and Vi ({m.model_v.iloc[0]}) carried together · samples ≤ {PAIR_S} s "
           f"and ≤ {PAIR_M} m apart · weak (< {USABLE_DBM} dBm): Jio {weak_j:.0f}%, Vi {weak_v:.0f}%",
           "Cell changes are counted between consecutive paired samples, identically for both phones, so the ratio is "
           "fair even though some changes between samples are missed. One walk and two different phone models — "
           "treat as a first observation to repeat.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--since")
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    apply_style()

    df = load_points(args.src)
    if args.since:
        df = df[df.ts >= args.since]
    df["band"] = df.band.astype(str).replace({"nan": None, "N/A": None})
    df["band_class"] = df.band.map(band_class)
    s, n_sq = shared_squares(df)
    print(f"{n_sq} shared squares · {len(s):,} samples")
    chart_band_strategy(s, n_sq, args.out_dir)
    chart_coverage(s, n_sq, args.out_dir)
    chart_walk(df, args.out_dir)


if __name__ == "__main__":
    main()
