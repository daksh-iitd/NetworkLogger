"""
Builds the "NetworkLogger Map" Grafana dashboard (Geomap panels on the network_logs_v2
bucket) and writes it next to this script. Copy the JSON into Grafana's provisioned
dashboards folder (/opt/homebrew/etc/grafana/dashboards) to install or update it.

    python dashboards/make_map_dashboard.py
"""

import json
import os

DS = {"type": "influxdb", "uid": "P7C70A67DE99A08E6"}
BUCKET = "network_logs_v2"
CENTER = {"lat": 28.5465, "lon": 77.1885, "zoom": 15}

# Same five classes as the app's signal labels and the presentation maps
RSRP_STEPS = [
    {"color": "#d7301f", "value": None},   # very weak  < −110
    {"color": "#fc8d59", "value": -110},   # weak
    {"color": "#fee08b", "value": -100},   # medium
    {"color": "#91bfdb", "value": -90},    # strong
    {"color": "#2c7bb6", "value": -80},    # very strong ≥ −80
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
           "Every Jio sample, coloured by serving-cell RSRP (same classes as the app's signal labels). Jio values are "
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
        variable("op", "Operator", "op", regex="/^(Jio|Vi)$/"),
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


live_map = geomap(
    1, "Where the phones are now — RSRP",
    "Every sample in the time range, coloured by RSRP. Phones send a batch every minute, so the newest "
    "points are up to ~1 minute old.",
    query('true', keep=("_time", "lat", "lon", "rsrp", "band", "op", "deviceModel", "testerName"), band_filter=False),
    "rsrp", {"x": 0, "y": 4, "w": 14, "h": 18}, rsrp_field_config)
live_map["options"]["view"] = {"id": "fit", "allLayers": True, "lastOnly": False, "padding": 10, **CENTER}

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
    live_map,
    timeseries(3, "RSRP", "Serving-cell RSRP per phone.",
               series_query(["rsrp"], ["deviceModel", "testerName"]), "dBm",
               {"x": 14, "y": 4, "w": 10, "h": 9},
               "${__field.labels.deviceModel} (${__field.labels.testerName})", RSRP_STEPS),
    timeseries(4, "Throughput", "Device DL/UL throughput, excluding the app's own uploads.",
               series_query(["dlKbps", "ulKbps"], ["deviceModel", "_field"]), "Kbits",
               {"x": 14, "y": 13, "w": 10, "h": 9},
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

here = os.path.dirname(os.path.abspath(__file__))
for name, board in [("network_logger_map.json", dashboard), ("network_logger_live.json", live_dashboard)]:
    out = os.path.join(here, name)
    with open(out, "w") as f:
        json.dump(board, f, indent=2)
    print(f"wrote {out}")
