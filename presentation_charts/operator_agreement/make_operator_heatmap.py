"""
Single map of all three operators: every grid cell is split into three stripes (Jio, Vi, Airtel,
left to right), each coloured by that operator's median RSRP. A blank stripe means that operator
has too little data in the cell.

Cells are built here from the raw samples the same way grid_builder.py builds them for the
dashboard (30 s mean windows per series, median per cell), so the map does not depend on the
grid builder running. With --5g only samples the app labelled "5G" (standalone) or "5G (NSA)" count.

    cd presentation_charts && ./venv/bin/python operator_agreement/make_operator_heatmap.py [--grid 110] [--5g]
"""

import argparse
import math
import os
import re
import tomllib
from statistics import median

import contextily as cx
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from influxdb_client import InfluxDBClient
from make_agreement_map import GRID_SIZES, HERE, MIN_WINDOWS, OPERATORS, to_mercator
from make_research_charts import CONTEXT, INK_PRIMARY, INK_SECONDARY, apply_style, finish
from matplotlib.cm import ScalarMappable
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Rectangle

CENTRE_LAT, CENTRE_LON = 28.5455, 77.1905   # IIT Delhi
HALF_WIDTH_M = 1350
ASPECT = 0.66
RSRP_MIN, RSRP_MAX = -115, -75              # centred on the medium class, -100 to -90
CMAP = LinearSegmentedColormap.from_list("rsrp", ["#d7301f", "#fc8d59", "#fee08b", "#91bfdb", "#2c7bb6"])
NORM = Normalize(RSRP_MIN, RSRP_MAX)
BLANK = "#ffffff"
FIVE_G = ("5G", "5G (NSA)")
SERIES_TAGS = ("deviceId", "sessionId", "network", "signal", "pci", "screenOn", "band", "bandSource", "nrLegBand")


def load_raw_cells(grid_size, networks=None):
    """Cells from raw samples, binned like grid_builder.py; optionally only some network labels."""
    with open(os.path.expanduser("~/.influxdbv2/configs"), "rb") as f:
        token = tomllib.load(f)["default"]["token"]
    network_filter = " or ".join(f'r.network == "{n}"' for n in networks) if networks else "true"
    query = f'''from(bucket: "network_logs_v2")
  |> range(start: -180d)
  |> filter(fn: (r) => r._measurement == "network_log" and ({network_filter}))
  |> filter(fn: (r) => r._field == "lat" or r._field == "lon" or r._field == "rsrp")
  |> aggregateWindow(every: 30s, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> filter(fn: (r) => exists r.lat and exists r.lon and exists r.rsrp)
  |> group()'''
    size = float(grid_size)
    cells, seen = {}, set()
    with InfluxDBClient(url="http://localhost:8086", token=token, org="networklogger", timeout=300_000) as client:
        for r in client.query_api().query_stream(query):
            op = "Airtel" if re.search("airtel", r.values.get("op") or "", re.IGNORECASE) else r.values.get("op")
            window = (op, r["_time"], *(r.values.get(t) for t in SERIES_TAGS))
            if window in seen:   # Airtel rows are stored twice, under "airtel" and "Airtel"
                continue
            seen.add(window)
            key = (op, (math.floor(r["lat"] / size) + 0.5) * size, (math.floor(r["lon"] / size) + 0.5) * size)
            cells.setdefault(key, []).append(r["rsrp"])
    df = pd.DataFrame([{"op": op, "cellLat": la, "cellLon": lo, "rsrp": median(v), "samples": len(v)}
                       for (op, la, lo), v in cells.items()])
    print(f"30 s windows per operator: {df.groupby('op').samples.sum().to_dict()}")
    return df[df.op.isin(OPERATORS) & (df.samples >= MIN_WINDOWS)]


def frame():
    x, y = to_mercator(CENTRE_LAT, CENTRE_LON)
    return x - HALF_WIDTH_M, x + HALF_WIDTH_M, y - HALF_WIDTH_M * ASPECT, y + HALF_WIDTH_M * ASPECT


def stripes(ax, x0, y0, width, height, values, zorder=3):
    for i, op in enumerate(OPERATORS):
        value = values.get(op, np.nan)
        color = BLANK if np.isnan(value) else CMAP(NORM(value))
        ax.add_patch(Rectangle((x0 + i * width / 3, y0), width / 3, height, facecolor=color,
                               edgecolor="none", zorder=zorder))
    ax.add_patch(Rectangle((x0, y0), width, height, facecolor="none", edgecolor=INK_PRIMARY,
                           linewidth=0.6, zorder=zorder + 0.1))


def key(ax):
    ax.add_patch(Rectangle((0.635, 0.755), 0.35, 0.215, transform=ax.transAxes, facecolor="white",
                           edgecolor=CONTEXT, zorder=6))
    legend = ax.inset_axes([0.65, 0.855, 0.135, 0.095], zorder=7)
    legend.set_xlim(0, 3)
    legend.set_ylim(0, 1)
    legend.axis("off")
    for i, op in enumerate(OPERATORS):
        legend.add_patch(Rectangle((i, 0), 1, 1, facecolor="#f1f0ec", edgecolor=INK_PRIMARY, linewidth=0.7))
        legend.text(i + 0.5, 0.5, op, ha="center", va="center", fontsize=9, color=INK_PRIMARY)
    ax.text(0.80, 0.903, "Each cell, left to right.\nBlank stripe = too little data", transform=ax.transAxes,
            fontsize=9, color=INK_SECONDARY, va="center", zorder=7)
    bar = ax.inset_axes([0.65, 0.80, 0.32, 0.022], zorder=7)
    colorbar = plt.colorbar(ScalarMappable(norm=NORM, cmap=CMAP), cax=bar, orientation="horizontal")
    colorbar.set_ticks([-110, -100, -90, -80])
    colorbar.set_ticklabels(["−110", "−100", "−90", "−80 dBm"])
    colorbar.ax.tick_params(labelsize=9, length=3, color=INK_SECONDARY)
    colorbar.outline.set_edgecolor(CONTEXT)


def draw(wide, measured, metres, five_g=False):
    apply_style()
    fig, ax = plt.subplots(figsize=(12, 8.6))
    size = float(GRID_SIZES[metres])
    x_min, x_max, y_min, y_max = frame()
    for _, c in wide.iterrows():
        x0, y0 = to_mercator(c.cellLat - size / 2, c.cellLon - size / 2)
        x1, y1 = to_mercator(c.cellLat + size / 2, c.cellLon + size / 2)
        stripes(ax, x0, y0, x1 - x0, y1 - y0, c[OPERATORS].astype(float).to_dict())
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    ax.set_aspect("equal")
    cx.add_basemap(ax, crs="EPSG:3857", source=cx.providers.Esri.WorldGrayCanvas, attribution_size=6)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    key(ax)

    shared = wide.dropna(subset=OPERATORS)
    best = shared[OPERATORS].astype(float).idxmax(axis=1).value_counts()
    if len(shared):
        title = f"{best.index[0]} is the strongest operator in {best.iloc[0]} of the {len(shared)} cells all three share"
    else:
        per_op = ", ".join(f"{op} {wide[op].notna().sum()}" for op in OPERATORS)
        title = f"No cell has 5G data from all three operators (cells with data: {per_op})"
    if five_g:
        name = f"operator_heatmap_5g_{metres}m.png"
        subtitle = (f"5G samples only, ~{metres} m cells around IIT Delhi, median RSRP per operator, "
                    f"at least {MIN_WINDOWS} 30 s windows")
        note = (f"{len(wide)} of {measured} cells with 5G data fall inside this view. Jio: 5G standalone (5G signal). "
                "Vi and Airtel: 5G NSA, where the phone reports the 4G anchor's RSRP.")
    else:
        name = f"operator_heatmap_{metres}m.png"
        subtitle = f"~{metres} m cells around IIT Delhi, median RSRP per operator, at least {MIN_WINDOWS} 30 s windows"
        note = (f"{len(wide)} of {measured} measured cells fall inside this view; shared counts cover this view only. "
                "Jio is mostly 5G SS-RSRP, a few dB below LTE RSRP by definition.")
    finish(fig, HERE, name, title, subtitle, note)
    print(best.to_string())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--grid", type=int, choices=sorted(GRID_SIZES), default=110, help="cell size in metres")
    parser.add_argument("--5g", dest="five_g", action="store_true", help="only samples labelled 5G or 5G (NSA)")
    args = parser.parse_args()
    metres = args.grid

    df = load_raw_cells(GRID_SIZES[metres], FIVE_G if args.five_g else None)
    wide = df.pivot(index=["cellLat", "cellLon"], columns="op", values="rsrp").reindex(columns=OPERATORS).reset_index()
    measured = len(wide)
    xs, ys = to_mercator(wide.cellLat.values, wide.cellLon.values)
    x_min, x_max, y_min, y_max = frame()
    wide = wide[(xs >= x_min) & (xs <= x_max) & (ys >= y_min) & (ys <= y_max)]
    print(f"{len(wide)} of {measured} cells in view; operators present per cell:")
    print(wide[OPERATORS].notna().sum(axis=1).value_counts().sort_index().to_string())
    draw(wide, measured, metres, args.five_g)


if __name__ == "__main__":
    main()
