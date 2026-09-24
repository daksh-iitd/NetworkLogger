"""
Generates a set of map visualizations for one logging session, pulling data
from the local InfluxDB instance loaded by pull_and_load_influx.py.

Usage:
    python make_map_charts.py --device-id <DEVICE_ID> --session-id <SESSION_ID> [--out-dir <DIR>]

Produces 4 PNGs in --out-dir:
    1_route_map.png          - GPS path, colored by elapsed time, gaps >2min not connected
    2_route_rsrp.png         - GPS scatter colored by RSRP (signal strength)
    3_route_network_type.png - GPS scatter colored by network type (4G/5G)
    4_route_throughput.png   - GPS scatter colored by downlink throughput (log scale)

Requires a local InfluxDB with the token available via `influx config` (reads
~/.influxdbv2/configs directly, same as pull_and_load_influx.py).

To find a good session to plot, query the lat/lon bounding-box span per
session in InfluxDB (Flux `reduce` over lat/lon) and pick one with a large
span relative to the others -- a large span means real movement, not GPS
jitter. See the project's README for the exact Flux query used.
"""

import argparse
import io
import os
import subprocess

import contextily as cx
import matplotlib
matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import pandas as pd
import requests

BLUE = "#2a78d6"
ORANGE = "#eb6834"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
SURFACE = "#fcfcfb"

# Break the route line if more than this many seconds passed between
# consecutive points -- treats it as a stop rather than drawing a straight
# "teleport" line across the gap.
GAP_THRESHOLD_S = 120


def get_influx_token():
    return subprocess.run(
        "grep -A2 '\\[default\\]' ~/.influxdbv2/configs | grep token | sed -E 's/.*token = \"(.*)\"/\\1/'",
        shell=True, capture_output=True, text=True
    ).stdout.strip()


def load_session(device_id, session_id, token):
    flux_query = f'''
from(bucket: "network_logs")
  |> range(start: -180d)
  |> filter(fn: (r) => r._measurement == "network_log")
  |> filter(fn: (r) => r.deviceId == "{device_id}")
  |> filter(fn: (r) => r.sessionId == "{session_id}")
  |> filter(fn: (r) => r._field == "lat" or r._field == "lon" or r._field == "rsrp" or r._field == "dlKbps" or r._field == "ulKbps")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> keep(columns: ["_time", "lat", "lon", "rsrp", "dlKbps", "ulKbps", "network", "signal"])
  |> sort(columns: ["_time"])
'''
    resp = requests.post(
        "http://localhost:8086/api/v2/query?org=networklogger",
        headers={"Authorization": f"Token {token}", "Content-Type": "application/vnd.flux"},
        data=flux_query,
    )
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text), comment="#")
    df = df.dropna(subset=["lat", "lon"])
    df["_time"] = pd.to_datetime(df["_time"])
    return df


def apply_style():
    plt.rcParams.update({
        "font.family": "sans-serif",
        "text.color": INK_PRIMARY,
        "axes.edgecolor": "#c3c2b7",
        "axes.labelcolor": INK_SECONDARY,
        "figure.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
    })


def plot_route_by_time(df, out_dir):
    gaps = df["_time"].diff().dt.total_seconds().fillna(0)
    segment_id = (gaps > GAP_THRESHOLD_S).cumsum()

    fig, ax = plt.subplots(figsize=(9, 9))
    t0 = df["_time"].iloc[0]
    elapsed_hours = (df["_time"] - t0).dt.total_seconds() / 3600.0
    cmap = plt.get_cmap("plasma")
    norm = mcolors.Normalize(vmin=elapsed_hours.min(), vmax=elapsed_hours.max())

    for _, seg in df.groupby(segment_id):
        if len(seg) < 2:
            continue
        seg_elapsed = (seg["_time"] - t0).dt.total_seconds() / 3600.0
        points = list(zip(seg["lon"], seg["lat"]))
        for i in range(len(points) - 1):
            ax.plot(
                [points[i][0], points[i + 1][0]], [points[i][1], points[i + 1][1]],
                color=cmap(norm(seg_elapsed.iloc[i])), linewidth=2.2, alpha=0.85, zorder=2
            )

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    cbar = fig.colorbar(sm, ax=ax, shrink=0.7, pad=0.02)
    cbar.set_label("Elapsed time (hours)", color=INK_SECONDARY)

    ax.scatter(df["lon"].iloc[0], df["lat"].iloc[0], color="#1baf7a", s=150, marker="o",
               edgecolor="white", linewidth=1.5, zorder=5, label="Start")
    ax.scatter(df["lon"].iloc[-1], df["lat"].iloc[-1], color="#e34948", s=150, marker="s",
               edgecolor="white", linewidth=1.5, zorder=5, label="End")
    ax.set_title(f"Route (colored by time, gaps >{GAP_THRESHOLD_S // 60}min not connected)",
                 fontsize=13, loc="left", pad=12, color=INK_PRIMARY)
    ax.legend(loc="upper left", frameon=True, facecolor="white", framealpha=0.9)
    ax.set_xticks([])
    ax.set_yticks([])
    cx.add_basemap(ax, crs="EPSG:4326", source=cx.providers.Esri.WorldGrayCanvas)
    fig.tight_layout()
    fig.savefig(f"{out_dir}/1_route_map.png", dpi=180)
    plt.close(fig)
    print(f"Route split into {segment_id.nunique()} segments (gaps > {GAP_THRESHOLD_S}s treated as stops)")
    print("Saved 1_route_map.png")


def plot_route_by_rsrp(df, out_dir):
    fig, ax = plt.subplots(figsize=(10, 9))
    sc = ax.scatter(df["lon"], df["lat"], c=df["rsrp"], cmap="RdYlGn", s=18,
                     vmin=df["rsrp"].quantile(0.02), vmax=df["rsrp"].quantile(0.98), zorder=3)
    cbar = fig.colorbar(sc, ax=ax, shrink=0.7, pad=0.02)
    cbar.set_label("RSRP (dBm)", color=INK_SECONDARY)
    ax.set_title("Signal Strength Along the Route (RSRP)", fontsize=15, loc="left", pad=12, color=INK_PRIMARY)
    ax.set_xticks([])
    ax.set_yticks([])
    cx.add_basemap(ax, crs="EPSG:4326", source=cx.providers.Esri.WorldGrayCanvas)
    fig.tight_layout()
    fig.savefig(f"{out_dir}/2_route_rsrp.png", dpi=180)
    plt.close(fig)
    print("Saved 2_route_rsrp.png")


def plot_route_by_network_type(df, out_dir):
    if "network" not in df.columns:
        print("No 'network' column present, skipping network-type map.")
        return
    fig, ax = plt.subplots(figsize=(10, 9))
    net_colors = {"4G": ORANGE, "4G (CA)": ORANGE, "5G": BLUE, "5G (NSA)": BLUE}
    for net_val, group in df.groupby("network"):
        color = net_colors.get(net_val, "#898781")
        ax.scatter(group["lon"], group["lat"], color=color, s=18, label=net_val, zorder=3)
    ax.set_title("Network Type Along the Route", fontsize=15, loc="left", pad=12, color=INK_PRIMARY)
    ax.legend(loc="upper left", frameon=True, facecolor="white", framealpha=0.9)
    ax.set_xticks([])
    ax.set_yticks([])
    cx.add_basemap(ax, crs="EPSG:4326", source=cx.providers.Esri.WorldGrayCanvas)
    fig.tight_layout()
    fig.savefig(f"{out_dir}/3_route_network_type.png", dpi=180)
    plt.close(fig)
    print("Saved 3_route_network_type.png")


def plot_route_by_throughput(df, out_dir):
    fig, ax = plt.subplots(figsize=(10, 9))
    dl = df["dlKbps"].fillna(0).clip(lower=0.01)
    sc = ax.scatter(df["lon"], df["lat"], c=dl, cmap="viridis", s=18,
                     norm=mcolors.LogNorm(vmin=max(dl.min(), 0.1), vmax=dl.max()), zorder=3)
    cbar = fig.colorbar(sc, ax=ax, shrink=0.7, pad=0.02)
    cbar.set_label("Downlink kbps (log scale)", color=INK_SECONDARY)
    ax.set_title("Downlink Throughput Along the Route", fontsize=15, loc="left", pad=12, color=INK_PRIMARY)
    ax.set_xticks([])
    ax.set_yticks([])
    cx.add_basemap(ax, crs="EPSG:4326", source=cx.providers.Esri.WorldGrayCanvas)
    fig.tight_layout()
    fig.savefig(f"{out_dir}/4_route_throughput.png", dpi=180)
    plt.close(fig)
    print("Saved 4_route_throughput.png")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--out-dir", default=os.path.join(os.path.dirname(__file__), "map_charts"))
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    token = get_influx_token()
    df = load_session(args.device_id, args.session_id, token)

    print(f"Loaded {len(df)} rows with GPS data.")
    print(f"Lat range: {df['lat'].min()} to {df['lat'].max()}")
    print(f"Lon range: {df['lon'].min()} to {df['lon'].max()}")
    if "network" in df.columns:
        print(f"Network values: {df['network'].unique()}")

    if len(df) < 2:
        raise SystemExit(f"Not enough GPS points ({len(df)}) for device={args.device_id} session={args.session_id}")

    apply_style()
    plot_route_by_time(df, args.out_dir)
    plot_route_by_rsrp(df, args.out_dir)
    plot_route_by_network_type(df, args.out_dir)
    plot_route_by_throughput(df, args.out_dir)
    print(f"\nAll maps saved to {args.out_dir}")


if __name__ == "__main__":
    main()
