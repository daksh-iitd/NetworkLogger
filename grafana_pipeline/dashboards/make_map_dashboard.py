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


def query(op_filter, fields=("lat", "lon", "rsrp"), keep=("_time", "lat", "lon", "rsrp", "band", "deviceModel")):
    field_or = " or ".join(f'r._field == "{f}"' for f in fields)
    exists = " and ".join(f"exists r.{f}" for f in fields)
    keep_cols = ", ".join(f'"{c}"' for c in keep)
    return f'''from(bucket: "{BUCKET}")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "network_log")
  |> filter(fn: (r) => {op_filter})
  |> filter(fn: (r) => r.band =~ /^${{band:regex}}$/)
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

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "network_logger_map.json")
with open(out, "w") as f:
    json.dump(dashboard, f, indent=2)
print(f"wrote {out}")
