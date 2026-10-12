"""
Campus-wide charts from the band-logging app version (Oct 2026 onwards) plus all earlier
logs: which band served where, how band frequency affects signal at the same spot, and
where each operator is stronger.

    15_band_map.png              - one dot per sample, coloured by band frequency range
    16_same_spot_bands.png       - Vi's bands compared inside the same 75 m square
    17_cross_operator_map.png    - Vi − Jio median RSRP per 100 m square
    18_rsrp_map.png              - RSRP at every logged point, Jio vs Vi
    19_rsrp_by_band_map.png      - RSRP at every point, one panel per band

Usage:
    ./venv/bin/python code/make_campus_charts.py \
        --src ../grafana_pipeline/firebase_csv_mirror --out-dir campus --since 2026-09-28
"""

import argparse
import os

import contextily as cx
import matplotlib.lines as mlines
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import matplotlib.colors as mcolors
import matplotlib.patches as mpatches

from make_all_logs_map import RSRP_COLORS, RSRP_EDGES, RSRP_LABELS, load_points
from make_research_charts import (CONTEXT, GRID, INK_MUTED, INK_PRIMARY, INK_SECONDARY, SURFACE,
                                  apply_style, finish, haversine_m)

# Colour encodes the band's frequency range, so it means the same thing for both operators
LOW, MID, HIGH = "#eb6834", "#1baf7a", "#2a78d6"     # reference palette slots 2, 3, 1
BAND_CLASS = {
    "low":  (["B5", "B8", "B20", "B28", "n5", "n8", "n28"], LOW, "low band  < 1 GHz"),
    "mid":  (["B1", "B3", "n1", "n3"], MID, "mid band  1.8–2.1 GHz"),
    "high": (["B40", "B41", "n40", "n41", "n77", "n78"], HIGH, "high band  2.3–3.5 GHz"),
}
BAND_FREQ = {"B8": "900 MHz", "B3": "1800 MHz", "B41": "2500 MHz", "B1": "2100 MHz",
             "n28": "700 MHz", "n78": "3500 MHz", "B40": "2300 MHz", "B5": "850 MHz", "n1": "2100 MHz"}

SAME_SPOT_M = 75
CROSS_OP_M = 100
MIN_SAMPLES = 10
# Diverging classes for Vi − Jio (dB): red = Jio stronger, grey = similar, blue = Vi stronger
DIFF_EDGES = [-60, -10, -3, 3, 10, 60]
DIFF_COLORS = ["#b2182b", "#ef8a62", "#c3c2b7", "#67a9cf", "#2166ac"]
DIFF_LABELS = ["Jio ≥ 10 dB stronger", "Jio 3–10 dB stronger", "within ±3 dB", "Vi 3–10 dB stronger",
               "Vi ≥ 10 dB stronger"]


def band_class(band):
    for key, (bands, _, _) in BAND_CLASS.items():
        if band in bands:
            return key
    return None


def extent(df, pad_m=120):
    x0, x1 = df.x.quantile([0.005, 0.995])
    y0, y1 = df.y.quantile([0.005, 0.995])
    return x0 - pad_m, x1 + pad_m, y0 - pad_m, y1 + pad_m


def style_map(ax, ext):
    ax.set_xlim(ext[0], ext[1])
    ax.set_ylim(ext[2], ext[3])
    cx.add_basemap(ax, crs="EPSG:3857", source=cx.providers.Esri.WorldGrayCanvas, attribution_size=6)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)


# ── 15: which band served where ─────────────────────────────────────────────

def chart_band_map(df, out_dir):
    b = df[df.band_class.notna()]
    ext = extent(b)
    fig, axes = plt.subplots(1, 2, figsize=(15, 7.6))
    for ax, op in zip(axes, ["Jio", "Vi"]):
        d = b[b.op == op].sample(frac=1, random_state=0)
        colors = d.band_class.map({k: v[1] for k, v in BAND_CLASS.items()})
        ax.scatter(d.x, d.y, c=colors, s=7, linewidths=0, alpha=0.75, zorder=3)
        style_map(ax, ext)
        mix = d.band.value_counts(normalize=True).head(3)
        mix_txt = " · ".join(f"{band} {share*100:.0f}%" for band, share in mix.items())
        ax.set_title(f"{op} · {len(d):,} samples · {d.device.nunique()} phone(s)\n{mix_txt}", fontsize=11.5)
    handles = [mlines.Line2D([], [], marker="o", linestyle="", markersize=8, color=c,
                             label=f"{label}  ({', '.join(x for x in bands if x in set(b.band))})")
               for bands, c, label in BAND_CLASS.values()]
    axes[1].legend(handles=handles, loc="lower right", fontsize=9, frameon=True, facecolor=SURFACE,
                   edgecolor="none", framealpha=0.92, title="Serving band", title_fontsize=9.5)
    days = f"{b.ts.min():%d %b} – {b.ts.max():%d %b}"
    finish(fig, out_dir, "15_band_map.png",
           "Which frequency band served each spot on campus",
           f"One dot per 5-second sample from the band-logging app version · {days} · band as reported by "
           "each phone's modem (Android getBands())",
           "Jio here is a single phone, so its map shows that phone's paths only. Bands are the serving cell's; on "
           "Vi's 4G there is no 5G layer to show.")


# ── 16: same spot, different band ───────────────────────────────────────────

def chart_same_spot_bands(df, out_dir):
    v = df[(df.op == "Vi") & df.band.isin(["B3", "B8", "B41"])].dropna(subset=["rsrp"]).copy()
    v["cx"], v["cy"] = (v.x // SAME_SPOT_M).astype(int), (v.y // SAME_SPOT_M).astype(int)
    per = v.groupby(["cx", "cy", "band"]).rsrp.agg(["size", "median"]).unstack("band")

    pairs = [("B3", "B41"), ("B8", "B41"), ("B8", "B3")]
    fig, axes = plt.subplots(1, 3, figsize=(14, 5.4), sharex=True, sharey=True)
    summary = {}
    for ax, (a, b) in zip(axes, pairs):
        ok = per[(per[("size", a)] >= MIN_SAMPLES) & (per[("size", b)] >= MIN_SAMPLES)]
        xa, yb = ok[("median", a)], ok[("median", b)]
        diff = (xa - yb).median()
        summary[(a, b)] = (diff, len(ok))
        ax.plot([-130, -60], [-130, -60], color=INK_MUTED, linewidth=1, linestyle="--", zorder=1)
        ax.scatter(xa, yb, s=55, color=INK_PRIMARY, alpha=0.8, edgecolor=SURFACE, linewidth=1, zorder=3)
        ax.set_xlabel(f"{a} ({BAND_FREQ[a]}) median RSRP (dBm)")
        ax.set_ylabel(f"{b} ({BAND_FREQ[b]}) median RSRP (dBm)")
        winner, margin = (a, diff) if diff >= 0 else (b, -diff)
        ax.set_title(f"{a} vs {b} · {len(ok)} squares\n{winner} stronger by {margin:.1f} dB (median)", fontsize=11.5)
        ax.set_xlim(-130, -65)
        ax.set_ylim(-130, -65)
        ax.text(-128, -68, f"above line: {b} stronger", fontsize=9, color=INK_SECONDARY, va="top")
        ax.text(-67, -128, f"below line: {a} stronger", fontsize=9, color=INK_SECONDARY, ha="right")
    d41 = summary[("B3", "B41")][0]
    finish(fig, out_dir, "16_same_spot_bands.png",
           f"At the same spot, Vi's 2.5 GHz band (B41) reads ~{d41:.0f} dB weaker than its 1.8 GHz band",
           f"Each dot is one {SAME_SPOT_M} m square where Vi phones logged both bands (≥ {MIN_SAMPLES} samples each) · "
           "comparing within a square removes location from the comparison",
           "Higher frequencies lose more power over distance and through walls, consistent with B41's deficit. "
           "B8 (900 MHz) is roughly level with B3 rather than stronger — physics alone would favour B8, so tower "
           "placement and transmit power matter as much as frequency here.")
    return summary


# ── 17: cross-operator, same squares ────────────────────────────────────────

def concurrent_pairs(df):
    j = df[(df.op == "Jio") & (df.ts >= "2026-10-06")].sort_values("ts")
    v = df[(df.op == "Vi") & (df.ts >= "2026-10-06")].sort_values("ts")
    m = pd.merge_asof(j, v[["ts", "lat", "lon", "rsrp"]], on="ts", tolerance=pd.Timedelta("10s"),
                      direction="nearest", suffixes=("_j", "_v")).dropna(subset=["lat_v"])
    m = m[haversine_m(m.lat_j, m.lon_j, m.lat_v, m.lon_v) < 50]
    return len(m), (m.rsrp_v - m.rsrp_j).median()


def chart_cross_operator(df, out_dir):
    d = df.dropna(subset=["rsrp"]).copy()
    d["cx"], d["cy"] = (d.x // CROSS_OP_M).astype(int), (d.y // CROSS_OP_M).astype(int)
    per = d.groupby(["cx", "cy", "op"]).rsrp.agg(["size", "median"]).unstack("op")
    ok = per[(per[("size", "Jio")] >= MIN_SAMPLES) & (per[("size", "Vi")] >= MIN_SAMPLES)].copy()
    ok["diff"] = ok[("median", "Vi")] - ok[("median", "Jio")]
    ok["x"] = (ok.index.get_level_values(0) + 0.5) * CROSS_OP_M
    ok["y"] = (ok.index.get_level_values(1) + 0.5) * CROSS_OP_M
    ok["cls"] = pd.cut(ok["diff"], DIFF_EDGES, labels=False)

    fig, (ax, axh) = plt.subplots(1, 2, figsize=(15, 7.4), gridspec_kw=dict(width_ratios=[1.6, 1]))
    ax.scatter(ok.x, ok.y, s=110, c=[DIFF_COLORS[int(c)] for c in ok.cls], edgecolor=INK_PRIMARY,
               linewidth=0.6, zorder=3, marker="s")
    style_map(ax, extent(d[d.cx.isin(ok.index.get_level_values(0))], pad_m=250))
    ax.set_title(f"Vi − Jio median RSRP in each {CROSS_OP_M} m square both operators logged", fontsize=11.5)

    counts = ok.cls.value_counts().reindex(range(5), fill_value=0)
    axh.barh(range(5), counts.values, color=DIFF_COLORS, height=0.6)
    for i, n in enumerate(counts.values):
        axh.text(n + 0.2, i, str(n), va="center", fontsize=11, fontweight="bold")
    axh.set_yticks(range(5))
    axh.set_yticklabels(DIFF_LABELS)
    axh.set_xlabel("Number of squares")
    axh.grid(axis="y", visible=False)
    axh.set_title("How the squares split", fontsize=11.5)

    n_pairs, pair_diff = concurrent_pairs(df)
    # Count from the same classes the bars use, so headline and bars always agree
    vi_ahead = int((ok.cls >= 3).sum())
    jio_ahead = int((ok.cls <= 1).sum())
    finish(fig, out_dir, "17_cross_operator_map.png",
           f"Vi read > 3 dB stronger than Jio in {vi_ahead} of {len(ok)} shared squares; Jio in {jio_ahead}",
           f"Squares with ≥ {MIN_SAMPLES} samples from each operator ({df.ts.min():%d %b} – {df.ts.max():%d %b}) · "
           f"median difference "
           f"{ok['diff'].median():+.0f} dB · when a Jio and a Vi phone were carried together ({n_pairs} samples "
           f"≤ 10 s and ≤ 50 m apart), Vi read {pair_diff:+.0f} dB",
           "Jio's values are mostly 5G SS-RSRP, which reads a few dB below LTE RSRP by definition, so part of Vi's lead "
           "is measurement, not coverage. Different phone models also differ by a few dB. Read the map for where "
           "the gap is large, not small ones.")


# ── 18/19: RSRP on the map ──────────────────────────────────────────────────

RSRP_CMAP = mcolors.ListedColormap(RSRP_COLORS)
RSRP_NORM = mcolors.BoundaryNorm(RSRP_EDGES, RSRP_CMAP.N)


def rsrp_dots(ax, d, ext, size=7):
    # Fixed random draw order: stacked samples at stationary spots shouldn't
    # systematically show only the weakest or only the strongest reading.
    d = d.dropna(subset=["rsrp"]).sample(frac=1, random_state=0)
    ax.scatter(d.x, d.y, c=d.rsrp, cmap=RSRP_CMAP, norm=RSRP_NORM, s=size, linewidths=0, alpha=0.8, zorder=3)
    style_map(ax, ext)
    return d


def rsrp_legend(ax, loc="lower right"):
    handles = [mpatches.Patch(color=c, label=l.replace("\n", "  ")) for c, l in zip(RSRP_COLORS, RSRP_LABELS)][::-1]
    ax.legend(handles=handles, title="Serving-cell RSRP (dBm)", loc=loc, fontsize=9, title_fontsize=9.5,
              frameon=True, facecolor=SURFACE, edgecolor="none", framealpha=0.92)


def weak_share(d):
    return (d.rsrp < -100).mean() * 100


def chart_rsrp_map(df, out_dir):
    # Same campus window as the band maps; the Sep drive and far-off points have their own maps
    ext = extent(df[df.band.notna()])
    campus = df[df.x.between(ext[0], ext[1]) & df.y.between(ext[2], ext[3])]
    fig, axes = plt.subplots(1, 2, figsize=(15, 7.8))
    for ax, op in zip(axes, ["Jio", "Vi"]):
        d = rsrp_dots(ax, campus[campus.op == op], ext)
        # Stationary sessions dominate per-sample statistics; say how much
        top_spot = d.groupby([(d.x // SAME_SPOT_M), (d.y // SAME_SPOT_M)]).size().max() / len(d) * 100
        ax.set_title(f"{op} · {len(d):,} samples · {d.device.nunique()} phone{'s' if d.device.nunique() != 1 else ''} · "
                     f"median {d.rsrp.median():.0f} dBm · {weak_share(d):.0f}% weak (< −100)\n{top_spot:.0f}% of samples come from one "
                     f"{SAME_SPOT_M} m spot where a phone sat still", fontsize=11)
    rsrp_legend(axes[1])
    finish(fig, out_dir, "18_rsrp_map.png",
           "Signal strength (RSRP) at every logged point around campus, Jio vs Vi",
           f"One dot per 5-second sample, campus logs {df.ts.min():%d %b} – {df.ts.max():%d %b} · colour classes "
           "match the app's signal labels",
           "Dots stack where phones sat still, so a spot's colour is one of many samples there. Jio's values are mostly "
           "5G SS-RSRP, a few dB below LTE RSRP by definition. Phones, days and placement differ between areas.")


def chart_rsrp_by_band(df, out_dir):
    panels = [("Vi", "B8"), ("Vi", "B3"), ("Vi", "B41"), ("Jio", "n28"), ("Jio", "n78")]
    b = df[df.band.notna()]
    ext = extent(b)
    fig, axes = plt.subplots(2, 3, figsize=(16, 10.5))
    for ax, (op, band) in zip(axes.flat, panels):
        d = rsrp_dots(ax, b[(b.op == op) & (b.band == band)], ext, size=6)
        ax.set_title(f"{op} {band} ({BAND_FREQ[band]}) · {len(d):,} samples\nmedian {d.rsrp.median():.0f} dBm · "
                     f"{weak_share(d):.0f}% weak", fontsize=11)
    legend_ax = axes.flat[-1]
    legend_ax.axis("off")
    rsrp_legend(legend_ax, loc="center")
    finish(fig, out_dir, "19_rsrp_by_band_map.png",
           "RSRP by band: Vi's 2.5 GHz layer is the weak one wherever it serves",
           "Same samples as the RSRP map, split by the serving band reported by each phone (band-logging app version, "
           f"{b.ts.min():%d %b} – {b.ts.max():%d %b})",
           "Each band appears only where the network put the phone on it, so a band's map shows where it served, not "
           "everywhere it reaches. Jio panels come from a single phone.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--since", help="only use samples on/after this date (YYYY-MM-DD), e.g. the last two weeks")
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    apply_style()

    df = load_points(args.src)
    if args.since:
        df = df[df.ts >= args.since]
    df["band"] = df.band.astype(str).replace({"nan": None, "N/A": None}) if "band" in df else None
    df["band_class"] = df.band.map(band_class)
    print(f"{len(df):,} GPS samples · {df.band.notna().sum():,} with a band")
    chart_band_map(df, args.out_dir)
    summary = chart_same_spot_bands(df, args.out_dir)
    print("  same-spot band differences:", {f"{a}-{b}": (round(d, 1), n) for (a, b), (d, n) in summary.items()})
    chart_cross_operator(df, args.out_dir)
    chart_rsrp_map(df, args.out_dir)
    chart_rsrp_by_band(df, args.out_dir)


if __name__ == "__main__":
    main()
