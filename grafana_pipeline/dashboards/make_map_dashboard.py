"""
Builds the "NetworkLogger Map", "NetworkLogger Live" and "NetworkLogger Coverage Grid"
Grafana dashboards (Geomap/timeseries panels on the network_logs_v2 bucket) and writes
them next to this script. Copy the JSON into Grafana's provisioned dashboards folder
(/opt/homebrew/etc/grafana/dashboards) to install or update them.

    python dashboards/make_map_dashboard.py
"""

import json
import os

DS = {"type": "influxdb", "uid": "P7C70A67DE99A08E6"}
BUCKET = "network_logs_v2"
CENTER = {"lat": 28.5465, "lon": 77.1885, "zoom": 15}

# Three classes, merged from the app's five signal labels
RSRP_STEPS = [
    {"color": "#d7301f", "value": None},   # poor    < −100
    {"color": "#fee08b", "value": -100},   # medium
    {"color": "#2c7bb6", "value": -90},    # strong  ≥ −90
]
# Band colour = frequency range, as in the presentation charts
BAND_COLORS = {"B5": "#eb6834", "B8": "#eb6834", "n28": "#eb6834",
               "B1": "#1baf7a", "B3": "#1baf7a", "n1": "#1baf7a",
               "B40": "#2a78d6", "B41": "#2a78d6", "n78": "#2a78d6"}


def query(op_filter, fields=("lat", "lon", "rsrp"), keep=("_time", "lat", "lon", "rsrp", "band", "deviceModel"),
          band_filter=True):
    field_or = " or ".join(f'r._field == "{f}"' for f in fields)
    exists = " and ".join(f"exists r.{f}" for f in fields)
    keep_cols = ", ".join(f'"{c}"' for c in keep)
    # Only dashboards that define a $band variable may filter on it
    band = '\n  |> filter(fn: (r) => r.band =~ /^${band:regex}$/)' if band_filter else ""
    return f'''from(bucket: "{BUCKET}")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "network_log")
  |> filter(fn: (r) => {op_filter}){band}
  |> filter(fn: (r) => r.deviceId =~ /^${{deviceId:regex}}$/)
  |> filter(fn: (r) => {field_or})
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> filter(fn: (r) => {exists})
  |> group()
  |> keep(columns: [{keep_cols}])'''


def geomap(pid, title, description, q, color_field, grid, field_config):
    return {
        "id": pid, "type": "geomap", "title": title, "description": description,
        "datasource": DS, "gridPos": grid,
        "targets": [{"refId": "A", "datasource": DS, "query": q}],
        "fieldConfig": field_config,
        "options": {
            "view": {"id": "coords", **CENTER},
            "controls": {"showZoom": True, "mouseWheelZoom": True, "showAttribution": True},
            "basemap": {"type": "default", "name": "Basemap", "config": {}},
            "tooltip": {"mode": "details"},
            "layers": [{
                "type": "markers", "name": title, "tooltip": True,
                "location": {"mode": "coords", "latitude": "lat", "longitude": "lon"},
                "config": {
                    "showLegend": True,
                    "style": {
                        "size": {"fixed": 4},
                        "color": {"field": color_field, "fixed": "dark-green"},
                        "opacity": 0.8,
                        "symbol": {"mode": "fixed", "fixed": "img/icons/marker/circle.svg"},
                    },
                },
            }],
        },
    }


rsrp_field_config = {
    "defaults": {"unit": "dBm", "decimals": 0, "color": {"mode": "thresholds"},
                 "thresholds": {"mode": "absolute", "steps": RSRP_STEPS}},
    "overrides": [],
}
band_field_config = {
    "defaults": {"color": {"mode": "fixed", "fixedColor": "#c3c2b7"}},
    "overrides": [{
        "matcher": {"id": "byName", "options": "band"},
        "properties": [{"id": "mappings", "value": [{"type": "value", "options": {
            b: {"color": c, "index": i} for i, (b, c) in enumerate(BAND_COLORS.items())}}]}],
    }],
}


def variable(name, label, tag, regex=None):
    v = {
        "name": name, "label": label, "type": "query", "datasource": DS,
        "query": f'import "influxdata/influxdb/schema"\nschema.tagValues(bucket: "{BUCKET}", tag: "{tag}", start: -365d)',
        "includeAll": True, "multi": True, "allValue": ".*", "refresh": 1, "sort": 1,
        "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
    }
    if regex:
        v["regex"] = regex
    return v


panels = [
    geomap(1, "RSRP — Jio",
           "Every Jio sample, coloured by serving-cell RSRP (poor < −100, medium, strong ≥ −90 dBm). Jio values are "
           "mostly 5G SS-RSRP, a few dB below LTE RSRP by definition.",
           query('r.op == "Jio"'), "rsrp", {"x": 0, "y": 0, "w": 12, "h": 17}, rsrp_field_config),
    geomap(2, "RSRP — Vi",
           "Every Vi sample, coloured by serving-cell RSRP. Points stack where phones sat still.",
           query('r.op == "Vi"'), "rsrp", {"x": 12, "y": 0, "w": 12, "h": 17}, rsrp_field_config),
    geomap(3, "Serving band — ${op}",
           "Serving band as reported by the phone (band-logging app version, Oct 2026 onwards). Orange = low band "
           "(< 1 GHz), green = mid band (1.8–2.1 GHz), blue = high band (2.3–3.5 GHz), grey = no band logged.",
           query('r.op =~ /^${op:regex}$/', keep=("_time", "lat", "lon", "rsrp", "band", "op", "deviceModel")),
           "band", {"x": 0, "y": 17, "w": 24, "h": 17}, band_field_config),
]

dashboard = {
    "uid": "networklogger-map",
    "title": "NetworkLogger Map",
    "tags": ["networklogger", "map"],
    "timezone": "browser",
    "schemaVersion": 39,
    "time": {"from": "now-45d", "to": "now"},
    "refresh": "",
    "templating": {"list": [
        variable("op", "Operator", "op", regex="/^(Jio|Vi|.*[Aa]irtel.*)$/"),
        variable("band", "Band", "band"),
        variable("deviceId", "Device", "deviceId"),
    ]},
    "panels": panels,
}


# ── Live dashboard: last hour, auto-refresh, fed by firestore_listener.py ──

def series_query(fields, by):
    field_or = " or ".join(f'r._field == "{f}"' for f in fields)
    return f'''from(bucket: "{BUCKET}")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "network_log")
  |> filter(fn: (r) => r.deviceId =~ /^${{deviceId:regex}}$/)
  |> filter(fn: (r) => {field_or})
  |> group(columns: [{", ".join(f'"{c}"' for c in by)}])
  |> keep(columns: ["_time", "_value", {", ".join(f'"{c}"' for c in by)}])'''


def timeseries(pid, title, description, q, unit, grid, display_name, thresholds=None):
    defaults = {"unit": unit, "displayName": display_name,
                "custom": {"drawStyle": "line", "lineWidth": 2, "pointSize": 4, "showPoints": "always",
                           "spanNulls": 60000}}
    if thresholds:
        defaults |= {"color": {"mode": "palette-classic"},
                     "thresholds": {"mode": "absolute", "steps": thresholds}}
        defaults["custom"]["thresholdsStyle"] = {"mode": "area"}
    return {"id": pid, "type": "timeseries", "title": title, "description": description,
            "datasource": DS, "gridPos": grid,
            "targets": [{"refId": "A", "datasource": DS, "query": q}],
            "fieldConfig": {"defaults": defaults, "overrides": []},
            "options": {"legend": {"displayMode": "list", "placement": "bottom"},
                        "tooltip": {"mode": "multi"}}}


# The three per-operator maps (grid squares + live points) are inserted below, after
# the grid helpers are defined. Fixed-coords views on purpose: a "fit" view re-fits
# (zooms out) on every 10 s refresh, throwing away the user's pan/zoom.

latest_rsrp = {
    "id": 2, "type": "stat", "title": "Latest RSRP per phone",
    "description": "Most recent RSRP from each phone in the time range.",
    "datasource": DS, "gridPos": {"x": 0, "y": 0, "w": 24, "h": 4},
    "targets": [{"refId": "A", "datasource": DS,
                 "query": series_query(["rsrp"], ["deviceModel", "testerName"]) + "\n  |> last()"}],
    "fieldConfig": {"defaults": {**rsrp_field_config["defaults"],
                                 "displayName": "${__field.labels.deviceModel} (${__field.labels.testerName})"},
                    "overrides": []},
    "options": {"colorMode": "background", "graphMode": "none", "textMode": "value_and_name",
                "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
}

live_panels = [
    latest_rsrp,
    timeseries(3, "RSRP", "Serving-cell RSRP per phone.",
               series_query(["rsrp"], ["deviceModel", "testerName"]), "dBm",
               {"x": 0, "y": 18, "w": 12, "h": 8},
               "${__field.labels.deviceModel} (${__field.labels.testerName})", RSRP_STEPS),
    timeseries(4, "Throughput", "Device DL/UL throughput, excluding the app's own uploads.",
               series_query(["dlKbps", "ulKbps"], ["deviceModel", "_field"]), "Kbits",
               {"x": 12, "y": 18, "w": 12, "h": 8},
               "${__field.labels.deviceModel} ${__field.labels._field}"),
]

live_dashboard = {
    "uid": "networklogger-live",
    "title": "NetworkLogger Live",
    "tags": ["networklogger", "live"],
    "timezone": "browser",
    "schemaVersion": 39,
    "time": {"from": "now-1h", "to": "now"},
    "refresh": "10s",
    "templating": {"list": [variable("deviceId", "Device", "deviceId")]},
    "panels": live_panels,
}

# ── Coverage-grid dashboard: median RSRP per lat/lon cell, one panel per operator ──
# Bins every sample into a square of $gridSize degrees, takes the median RSRP of the
# cell (median, not mean: robust against the odd -140 dBm glitch and against one phone
# sitting in a basement) and colours the cell with the same three classes as the point
# maps. $minSamples hides cells a phone only drove through once or twice.

def grid_query(op_filter, start="v.timeRangeStart", stop="v.timeRangeStop"):
    return f'''base = from(bucket: "{BUCKET}")
  |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => r._measurement == "network_log")
  |> filter(fn: (r) => {op_filter})
  |> filter(fn: (r) => r.deviceId =~ /^${{deviceId:regex}}$/)
  |> filter(fn: (r) => r._field == "lat" or r._field == "lon" or r._field == "rsrp")
  |> aggregateWindow(every: 30s, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> filter(fn: (r) => exists r.lat and exists r.lon and exists r.rsrp)
  |> map(fn: (r) => ({{r with
      cellLat: string(v: (float(v: int(v: r.lat / ${{gridSize}})) + 0.5) * ${{gridSize}}),
      cellLon: string(v: (float(v: int(v: r.lon / ${{gridSize}})) + 0.5) * ${{gridSize}})}}))
  |> group(columns: ["cellLat", "cellLon"])

med = base |> median(column: "rsrp")
cnt = base |> count(column: "rsrp") |> rename(columns: {{rsrp: "samples"}})

join(tables: {{med: med, cnt: cnt}}, on: ["cellLat", "cellLon"])
  |> filter(fn: (r) => r.samples >= ${{minSamples}})
  |> map(fn: (r) => ({{r with
      lat: float(v: r.cellLat), lon: float(v: r.cellLon),
      quality: if r.rsrp >= -90.0 then "strong"
               else if r.rsrp >= -100.0 then "medium"
               else "poor"}}))
  |> group()
  |> drop(columns: ["cellLat", "cellLon"])'''


def grid_panel(pid, op_name, op_filter, grid):
    fc = {
        "defaults": {"unit": "dBm", "decimals": 1, "color": {"mode": "thresholds"},
                     "thresholds": {"mode": "absolute", "steps": RSRP_STEPS}},
        "overrides": [
            {"matcher": {"id": "byName", "options": c},
             "properties": [{"id": "custom.hideFrom",
                             "value": {"tooltip": True, "viz": False, "legend": False}}]}
            for c in ("lat", "lon")
        ],
    }
    p = geomap(pid, f"{op_name} — median RSRP per cell",
               f"Each square is one $gridSize°-wide grid cell; its colour is the median RSRP of every "
               f"{op_name} sample inside it in the time range (hover for the value, the quality class and "
               f"the sample count). Cells with fewer than $minSamples samples are hidden.",
               grid_query(op_filter), "rsrp", grid, fc)
    p["options"]["layers"][0]["config"]["style"] |= {
        "size": {"fixed": 12}, "opacity": 0.75,
        "symbol": {"mode": "fixed", "fixed": "img/icons/marker/square.svg"},
    }
    return p


def custom_variable(name, label, options, default):
    return {
        "name": name, "label": label, "type": "custom", "multi": False, "includeAll": False,
        "query": ", ".join(f"{t} : {v}" for t, v in options),
        "options": [{"text": t, "value": v, "selected": v == default} for t, v in options],
        "current": {"selected": True,
                    "text": next(t for t, v in options if v == default), "value": default},
    }


GRID_OPS = [("Jio", 'r.op == "Jio"'),
            ("Vi", 'r.op == "Vi"'),
            # listener normalises Airtel from 31 Oct; the regex also catches older raw names
            ("Airtel", 'r.op =~ /(?i)airtel/')]

grid_dashboard = {
    "uid": "networklogger-grid",
    "title": "NetworkLogger Coverage Grid",
    "tags": ["networklogger", "map", "grid"],
    "timezone": "browser",
    "schemaVersion": 39,
    "time": {"from": "now-45d", "to": "now"},
    "refresh": "",
    "templating": {"list": [
        custom_variable("gridSize", "Grid size",
                        [("27 m", "0.00025"), ("55 m", "0.0005"),
                         ("110 m", "0.001"), ("220 m", "0.002")], "0.0005"),
        custom_variable("minSamples", "Min samples/cell",
                        [("1", "1"), ("3", "3"), ("5", "5"), ("10", "10"), ("20", "20")], "3"),
        variable("deviceId", "Device", "deviceId"),
    ]},
    "panels": [grid_panel(i + 1, op, flt, {"x": 8 * i, "y": 0, "w": 8, "h": 18})
               for i, (op, flt) in enumerate(GRID_OPS)],
}


# ── Live per-operator maps: precomputed region grid + live phones ──
# The region squares come from the "grid_cache" bucket, which ../grid_builder.py
# rebuilds every 30 min from *all* data so far (op names already
# normalised there, samples = 30 s windows per phone). Looking the cells up costs
# milliseconds; recomputing them from raw samples took ~6 s per operator and made the
# dashboard buffer for ~15 s on every load. $deviceId only filters the live dots and
# time series, not the precomputed squares.

def grid_lookup_query(op_name):
    # -3d lookback + last(): normally the newest cells are minutes old, but if the Mac
    # sleeps and the task misses runs, the maps keep showing the last computed grid
    # instead of going blank (grid_cache retention is 72 h to match)
    return f'''from(bucket: "grid_cache")
  |> range(start: -3d)
  |> filter(fn: (r) => r._measurement == "grid_rsrp")
  |> filter(fn: (r) => r.op == "{op_name}")
  |> filter(fn: (r) => r.gridSize == "${{gridSize}}")
  |> filter(fn: (r) => r._field == "rsrp" or r._field == "samples")
  |> last()
  |> group(columns: ["cellLat", "cellLon"])
  |> pivot(rowKey: ["cellLat", "cellLon"], columnKey: ["_field"], valueColumn: "_value")
  |> filter(fn: (r) => r.samples >= float(v: ${{minSamples}}))
  |> map(fn: (r) => ({{r with
      lat: float(v: r.cellLat), lon: float(v: r.cellLon),
      quality: if r.rsrp >= -90.0 then "strong"
               else if r.rsrp >= -100.0 then "medium"
               else "poor"}}))
  |> group()
  |> keep(columns: ["lat", "lon", "rsrp", "samples", "quality"])'''


def live_op_map(pid, op_name, points_filter, grid):
    p = geomap(pid, f"{op_name} — regions + live phones",
               f"Squares: $gridSize cells coloured by the median RSRP of all {op_name} data so far "
               f"(precomputed every 30 min; hover for median, quality class and 30 s-window count; cells "
               f"with fewer than $minSamples windows are hidden). Dots: live samples from the dashboard "
               f"time range, up to ~1 min behind the phone.",
               query(points_filter, keep=("_time", "lat", "lon", "rsrp", "band", "op", "deviceModel", "testerName"),
                     band_filter=False),
               "rsrp", grid, rsrp_field_config)
    p["targets"].append({"refId": "B", "datasource": DS, "query": grid_lookup_query(op_name)})
    points_layer = p["options"]["layers"][0]
    points_layer["name"] = "Live phones"
    points_layer["filterData"] = {"id": "byRefId", "options": "A"}
    p["options"]["layers"].insert(0, {
        "type": "markers", "name": "Region quality (all data)", "tooltip": True,
        "filterData": {"id": "byRefId", "options": "B"},
        "location": {"mode": "coords", "latitude": "lat", "longitude": "lon"},
        "config": {
            "showLegend": False,  # same classes as the points layer, one legend is enough
            "style": {
                "size": {"fixed": 12},
                "color": {"field": "rsrp", "fixed": "dark-green"},
                "opacity": 0.6,
                "symbol": {"mode": "fixed", "fixed": "img/icons/marker/square.svg"},
            },
        },
    })
    return p


LIVE_OPS = [("Jio", 'r.op == "Jio"'),
            ("Vi", 'r.op == "Vi"'),
            ("Airtel", 'r.op =~ /(?i)airtel/')]
for i, (op_name, flt) in enumerate(LIVE_OPS):
    live_panels.insert(1 + i, live_op_map(10 + i, op_name, flt,
                                          {"x": 8 * i, "y": 4, "w": 8, "h": 14}))

live_dashboard["templating"]["list"] = [
    custom_variable("gridSize", "Grid size",
                    [("27 m", "0.00025"), ("55 m", "0.0005"),
                     ("110 m", "0.001"), ("220 m", "0.002")], "0.0005"),
    custom_variable("minSamples", "Min windows/cell",
                    [("1", "1"), ("3", "3"), ("5", "5"), ("10", "10"), ("20", "20")], "3"),
    variable("deviceId", "Device", "deviceId"),
]

here = os.path.dirname(os.path.abspath(__file__))
for name, board in [("network_logger_map.json", dashboard), ("network_logger_live.json", live_dashboard),
                    ("network_logger_grid.json", grid_dashboard)]:
    out = os.path.join(here, name)
    with open(out, "w") as f:
        json.dump(board, f, indent=2)
    print(f"wrote {out}")
