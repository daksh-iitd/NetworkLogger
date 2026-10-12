"""
Every log collected so far, on one map: where data exists across Delhi, and median
signal strength (RSRP) per ~60 m hexagon around IIT Delhi, split by operator.

Usage:
    ./venv/bin/python code/make_all_logs_map.py \
        --src ../grafana_pipeline/firebase_csv_mirror --out maps/all_logs_map.png

Operators are never pooled into one colour: Jio and Vi logged in mostly different
places (11 of 128 occupied 100 m squares overlap), so a pooled map would show
who-was-where rather than coverage.
"""

import argparse

import contextily as cx
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np

from make_research_charts import INK_MUTED, INK_PRIMARY, INK_SECONDARY, SURFACE, apply_style, finish, load_sessions

# Android emulator default GPS fix (Google HQ) — a test run, not a real measurement
EMULATOR_FIX = (37.4220, -122.0841)
DELHI = dict(lat=(28.3, 28.9), lon=(76.9, 77.5))
ZOOM = dict(lat=(28.5395, 28.5515), lon=(77.1800, 77.1975))   # IIT Delhi and surroundings
TABLE = (28.5487638, 77.1834913)                               # controlled-experiment site

ZOOM_HEX_M = 60
OVERVIEW_HEX_M = 700
MIN_SAMPLES = 5

# Same thresholds as the app's own signal labels (LoggingService.getRsrpSignalLabel)
RSRP_EDGES = [-140, -110, -100, -90, -80, -40]
RSRP_LABELS = ["Very weak\n< −110", "Weak\n−110…−100", "Medium\n−100…−90", "Strong\n−90…−80", "Very strong\n≥ −80"]
RSRP_COLORS = ["#d7301f", "#fc8d59", "#fee08b", "#91bfdb", "#2c7bb6"]

R_EARTH = 6378137.0
GREYS_DARK = mcolors.LinearSegmentedColormap.from_list("greys_dark", ["#9a9993", "#1f1f1d"])
# (label, lat, lon, text offset x/y in points) for the overview's outlying data
OVERVIEW_LABELS = [
    ("drive, 7–8 Sep\n(own route maps)", 28.5303, 77.3116, -20, 30),
    ("one phone,\n~19 km north", 28.7156, 77.2183, 12, -6),
]


def to_mercator(lat, lon):
    x = np.radians(lon) * R_EARTH
    y = np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) * R_EARTH
    return x, y


def load_points(src):
    df = load_sessions(src)
    # Runs re-uploaded inside a later session appear twice; keep one copy
    df = df.sort_values("session").drop_duplicates(subset=["device", "ts"])
    df = df.dropna(subset=["lat", "lon"])
    df = df[~((df.lat.round(3) == round(EMULATOR_FIX[0], 3)) & (df.lon.round(3) == round(EMULATOR_FIX[1], 3)))]
    df = df[df.lat.between(*DELHI["lat"]) & df.lon.between(*DELHI["lon"]) & df.op.isin(["Jio", "Vi"])]
    df["x"], df["y"] = to_mercator(df.lat.values, df.lon.values)
    return df


def hex_gridsize(xmin, xmax, hex_m):
    return max(int((xmax - xmin) / hex_m), 1)


def draw_overview(ax, df):
    x0, y0 = df.x.min() - 1500, df.y.min() - 1500
    x1, y1 = df.x.max() + 1500, df.y.max() + 1500
    hb = ax.hexbin(df.x, df.y, gridsize=hex_gridsize(x0, x1, OVERVIEW_HEX_M), extent=(x0, x1, y0, y1),
                   bins="log", mincnt=1, cmap=GREYS_DARK, vmin=1, linewidths=0.4, edgecolors=SURFACE,
                   zorder=3)
    for text, lat, lon, dx, dy in OVERVIEW_LABELS:
        x, y = to_mercator(lat, lon)
        ax.annotate(text, (x, y), xytext=(dx, dy), textcoords="offset points", fontsize=9,
                    color=INK_SECONDARY, zorder=5,
                    arrowprops=dict(arrowstyle="-", color=INK_MUTED, linewidth=0.8))
    zx0, zy0 = to_mercator(ZOOM["lat"][0], ZOOM["lon"][0])
    zx1, zy1 = to_mercator(ZOOM["lat"][1], ZOOM["lon"][1])
    ax.add_patch(mpatches.Rectangle((zx0, zy0), zx1 - zx0, zy1 - zy0, fill=False,
                                    edgecolor=INK_PRIMARY, linewidth=1.5, zorder=4))
    ax.annotate("IIT Delhi area\n(zoomed, right)", (zx0, zy1), xytext=(-10, 28), textcoords="offset points",
                fontsize=9.5, fontweight="bold", ha="right", zorder=5,
                arrowprops=dict(arrowstyle="-", color=INK_PRIMARY, linewidth=0.8))
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    cx.add_basemap(ax, crs="EPSG:3857", source=cx.providers.Esri.WorldGrayCanvas, attribution_size=6)
    ax.set_title(f"Where data exists · all {len(df):,} samples", fontsize=11.5)
    return hb


def draw_zoom(ax, df, title):
    zx0, zy0 = to_mercator(ZOOM["lat"][0], ZOOM["lon"][0])
    zx1, zy1 = to_mercator(ZOOM["lat"][1], ZOOM["lon"][1])
    cmap = mcolors.ListedColormap(RSRP_COLORS)
    norm = mcolors.BoundaryNorm(RSRP_EDGES, cmap.N)
    d = df.dropna(subset=["rsrp"])
    hb = ax.hexbin(d.x, d.y, C=d.rsrp, reduce_C_function=np.median, mincnt=MIN_SAMPLES,
                   gridsize=hex_gridsize(zx0, zx1, ZOOM_HEX_M), extent=(zx0, zx1, zy0, zy1),
                   cmap=cmap, norm=norm, linewidths=0.4, edgecolors=SURFACE, alpha=0.9, zorder=3)
    tx, ty = to_mercator(*TABLE)
    ax.scatter([tx], [ty], marker="*", s=220, color=INK_PRIMARY, edgecolor=SURFACE, linewidth=1.2, zorder=5)
    ax.annotate("experiment table", (tx, ty), xytext=(8, -14), textcoords="offset points", fontsize=9,
                fontweight="bold", zorder=5)
    ax.set_xlim(zx0, zx1)
    ax.set_ylim(zy0, zy1)
    cx.add_basemap(ax, crs="EPSG:3857", source=cx.providers.Esri.WorldGrayCanvas, attribution_size=6)
    n_hex = int((hb.get_array() is not None) and np.isfinite(hb.get_array()).sum())
    ax.set_title(f"{title} · {len(d):,} samples · {n_hex} hexagons", fontsize=11.5)
    return cmap, norm


def draw_zoom_points(ax, df, title):
    zx0, zy0 = to_mercator(ZOOM["lat"][0], ZOOM["lon"][0])
    zx1, zy1 = to_mercator(ZOOM["lat"][1], ZOOM["lon"][1])
    cmap = mcolors.ListedColormap(RSRP_COLORS)
    norm = mcolors.BoundaryNorm(RSRP_EDGES, cmap.N)
    d = df.dropna(subset=["rsrp"])
    d = d[d.x.between(zx0, zx1) & d.y.between(zy0, zy1)]
    # Thousands of samples share a spot (e.g. the experiment table); a fixed random
    # draw order keeps either end of the scale from systematically landing on top.
    d = d.sample(frac=1, random_state=0)
    ax.scatter(d.x, d.y, c=d.rsrp, cmap=cmap, norm=norm, s=10, linewidths=0, alpha=0.8, zorder=3)
    # Hollow ring, not a filled marker: thousands of samples sit at the table itself
    tx, ty = to_mercator(*TABLE)
    ax.scatter([tx], [ty], marker="o", s=420, facecolor="none", edgecolor=INK_PRIMARY, linewidth=1.5, zorder=5)
    ax.annotate("experiment table", (tx, ty), xytext=(14, -16), textcoords="offset points", fontsize=9,
                fontweight="bold", zorder=5)
    ax.set_xlim(zx0, zx1)
    ax.set_ylim(zy0, zy1)
    cx.add_basemap(ax, crs="EPSG:3857", source=cx.providers.Esri.WorldGrayCanvas, attribution_size=6)
    ax.set_title(f"{title} · {len(d):,} samples · {d.device.nunique()} phones", fontsize=11.5)


def main_points(df, out):
    fig, axes = plt.subplots(1, 2, figsize=(15, 7.6))
    draw_zoom_points(axes[0], df[df.op == "Jio"], "Jio (4G + 5G SA)")
    draw_zoom_points(axes[1], df[df.op == "Vi"], "Vi (4G)")
    for ax in axes:
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        for s in ax.spines.values():
            s.set_visible(False)
    handles = [mpatches.Patch(color=c, label=l.replace("\n", "  ")) for c, l in zip(RSRP_COLORS, RSRP_LABELS)][::-1]
    axes[0].legend(handles=handles, title="Serving-cell RSRP (dBm)", loc="lower left",
                   fontsize=9, title_fontsize=9.5, frameon=True, facecolor=SURFACE, edgecolor="none",
                   framealpha=0.92)
    finish(fig, *out.rsplit("/", 1),
           "Every log so far around IIT Delhi: one dot per sample, by operator",
           "Each dot is one 5-second sample, coloured by the serving cell's RSRP · same colour classes as the app's "
           "signal labels",
           "Overlapping dots at stationary spots hide most samples there — the experiment table alone holds thousands. "
           "Phones, days and placement differ between spots. Jio's 5G SS-RSRP runs a few dB below LTE RSRP by definition.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--style", choices=["hex", "points"], default="hex",
                        help="hex: overview + median per hexagon · points: one dot per sample")
    args = parser.parse_args()
    apply_style()

    df = load_points(args.src)
    print(f"{len(df):,} samples from {df.device.nunique()} phones")
    if args.style == "points":
        main_points(df, args.out)
        return

    fig, axes = plt.subplots(1, 3, figsize=(18, 7.4), gridspec_kw=dict(width_ratios=[1, 1.15, 1.15]))
    draw_overview(axes[0], df)
    cmap, norm = draw_zoom(axes[1], df[df.op == "Jio"], "Jio (4G + 5G SA)")
    draw_zoom(axes[2], df[df.op == "Vi"], "Vi (4G)")
    for ax in axes:
        ax.set_xticks([])
        ax.set_yticks([])
        ax.grid(False)
        for s in ax.spines.values():
            s.set_visible(False)

    handles = [mpatches.Patch(color=c, label=l.replace("\n", "  ")) for c, l in zip(RSRP_COLORS, RSRP_LABELS)][::-1]
    axes[1].legend(handles=handles, title="Median RSRP per hexagon (dBm)", loc="lower left",
                   fontsize=9, title_fontsize=9.5, frameon=True, facecolor=SURFACE, edgecolor="none",
                   framealpha=0.92)

    finish(fig, *args.out.rsplit("/", 1),
           "Every log so far: signal strength around IIT Delhi, by operator",
           f"Left: where samples were collected (darker = more samples, ~{OVERVIEW_HEX_M} m hexagons) · "
           f"middle/right: median serving-cell RSRP per ~{ZOOM_HEX_M} m hexagon with ≥ {MIN_SAMPLES} samples",
           "Phones, days and indoor/outdoor placement differ between hexagons, so read colours as 'what was measured "
           "here', not a controlled coverage survey. Jio's 5G SS-RSRP runs a few dB below LTE RSRP by definition. "
           "Excludes one emulator test run (fake GPS) and duplicated re-uploads.")


if __name__ == "__main__":
    main()
