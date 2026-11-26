"""
Map of the grid cells where Jio, Vi and Airtel were all measured, showing whether the three
operators fall in the same signal class there (strong >= -90, medium, poor < -100 dBm).

Reads the cells grid_builder.py keeps in the local InfluxDB bucket grid_cache, so the classes and
grid match the Live dashboard. Writes the PNG and the cell table next to this script.

    cd presentation_charts && ./venv/bin/python operator_agreement/make_agreement_map.py [--grid 110]
"""

import argparse
import os
import sys
import tomllib

import contextily as cx
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from influxdb_client import InfluxDBClient
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "code"))
from make_research_charts import CONTEXT, INK_PRIMARY, INK_SECONDARY, apply_style, finish  # noqa: E402

OPERATORS = ["Jio", "Vi", "Airtel"]
GRID_SIZES = {27: "0.00025", 55: "0.0005", 110: "0.001", 220: "0.002"}   # metres -> degrees, as on the dashboard
MIN_WINDOWS = 3          # per operator, the Live dashboard default
CAMPUS_MIN_LON = 77.15   # shared cells west of this are ~10 km away near the airport, too far to frame together
COLORS = {"All strong": "#2c7bb6", "All medium": "#fee08b", "All poor": "#d7301f", "Operators differ": CONTEXT}


def load_cells(grid_size):
    with open(os.path.expanduser("~/.influxdbv2/configs"), "rb") as f:
        token = tomllib.load(f)["default"]["token"]
    query = f'''from(bucket: "grid_cache")
  |> range(start: -3d)
  |> filter(fn: (r) => r._measurement == "grid_rsrp" and r.gridSize == "{grid_size}")
  |> filter(fn: (r) => r._field == "rsrp" or r._field == "samples")
  |> last()
  |> pivot(rowKey: ["cellLat", "cellLon", "op"], columnKey: ["_field"], valueColumn: "_value")'''
    with InfluxDBClient(url="http://localhost:8086", token=token, org="networklogger", timeout=60_000) as client:
        rows = [r.values for t in client.query_api().query(query) for r in t.records]
    df = pd.DataFrame(rows)[["cellLat", "cellLon", "op", "rsrp", "samples"]]
    df = df[df.op.isin(OPERATORS) & (df.samples >= MIN_WINDOWS)]
    df[["cellLat", "cellLon"]] = df[["cellLat", "cellLon"]].astype(float)
    return df


def signal_class(rsrp):
    return "strong" if rsrp >= -90 else "medium" if rsrp >= -100 else "poor"


def agreement_table(df):
    wide = df.pivot(index=["cellLat", "cellLon"], columns="op", values="rsrp").dropna()[OPERATORS].reset_index()
    classes = wide[OPERATORS].map(signal_class)
    wide["agreement"] = [f"All {c[0]}" if len(set(c)) == 1 else "Operators differ" for c in classes.values]
    return wide


def to_mercator(lat, lon):
    radius = 6378137.0
    return radius * np.radians(lon), radius * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def draw(cells, measured, metres, out_dir):
    apply_style()
    fig, ax = plt.subplots(figsize=(12, 8.6))
    half = float(GRID_SIZES[metres]) / 2
    campus = cells[cells.cellLon >= CAMPUS_MIN_LON]
    away = cells[cells.cellLon < CAMPUS_MIN_LON]
    for _, c in campus.sort_values("agreement", key=lambda s: s != "Operators differ", kind="stable").iterrows():
        x0, y0 = to_mercator(c.cellLat - half, c.cellLon - half)
        x1, y1 = to_mercator(c.cellLat + half, c.cellLon + half)
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=COLORS[c.agreement],
                               edgecolor=INK_PRIMARY, linewidth=0.7, alpha=0.9, zorder=3))
    xs, ys = to_mercator(campus.cellLat.values, campus.cellLon.values)
    centre_x, centre_y = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    half_w = np.ptp(xs) / 2 + 260
    half_h = half_w * 0.62
    ax.set_xlim(centre_x - half_w, centre_x + half_w)
    ax.set_ylim(centre_y - half_h, centre_y + half_h)
    ax.set_aspect("equal")
    cx.add_basemap(ax, crs="EPSG:3857", source=cx.providers.Esri.WorldGrayCanvas, attribution_size=6)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)

    counts = campus.agreement.value_counts()
    away_counts = away.agreement.value_counts()

    def legend_label(name):
        off_map = away_counts.get(name, 0)
        return f"{name} ({counts.get(name, 0)}" + (f", +{off_map} near airport, off map)" if off_map else ")")

    handles = [Line2D([], [], marker="s", linestyle="", markersize=11, markerfacecolor=color,
                      markeredgecolor=INK_PRIMARY, markeredgewidth=0.7, label=legend_label(name))
               for name, color in COLORS.items()]
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.008, 0.03), frameon=True, facecolor="white", edgecolor=CONTEXT, fontsize=11)

    for i, (_, c) in enumerate(campus[campus.agreement == "All strong"].sort_values("cellLon").iterrows()):
        x, y = to_mercator(c.cellLat, c.cellLon)
        text = "\n".join(f"{op} {c[op]:.1f} dBm" for op in OPERATORS)
        ax.annotate(text, (x, y), xytext=(25, 85) if i == 0 else (-150, -125), textcoords="offset points", fontsize=10,
                    color=INK_PRIMARY, zorder=5, arrowprops={"arrowstyle": "-", "color": INK_SECONDARY, "lw": 0.8},
                    bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "edgecolor": CONTEXT})

    strong = (cells.agreement == "All strong").sum()
    finish(fig, out_dir, f"operator_agreement_map{file_suffix(metres)}.png",
           f"All three operators are strong in only {strong} of {len(cells)} shared grid cells",
           f"~{metres} m cells measured on Jio, Vi and Airtel, median RSRP, at least {MIN_WINDOWS} 30 s windows per operator",
           f"Strong >= -90 dBm, medium -100 to -90, poor < -100. {measured} cells have data from at least one "
           "operator; only those with all three count here. Jio is mostly 5G SS-RSRP.")


def file_suffix(metres):
    return "" if metres == 55 else f"_{metres}m"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--grid", type=int, choices=sorted(GRID_SIZES), default=55, help="cell size in metres")
    metres = parser.parse_args().grid

    df = load_cells(GRID_SIZES[metres])
    cells = agreement_table(df)
    measured = df[["cellLat", "cellLon"]].drop_duplicates().shape[0]
    print(cells.agreement.value_counts().to_string())
    cells.round({"cellLat": 5, "cellLon": 5, **dict.fromkeys(OPERATORS, 1)}).to_csv(
        os.path.join(HERE, f"operator_agreement_cells{file_suffix(metres)}.csv"), index=False)
    draw(cells, measured, metres, HERE)


if __name__ == "__main__":
    main()
