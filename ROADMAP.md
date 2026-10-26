# Roadmap

Planned features and improvements for NetworkLogger.

---

## Done

- **Cloud synchronization** — production sessions stream to Cloud Firestore every minute (offline-safe), replacing CSV uploads on Stop
- **Coverage maps** — campus RSRP and band maps (`presentation_charts/`) and the Grafana map dashboard
- **Live dashboard** — Grafana updates about a minute behind the phones; runs on the lab server for anyone on the IITD network
- **Multi-device aggregation** — all phones' sessions in one InfluxDB bucket, filterable by device and operator
- **Operator benchmarking** — Jio vs Vi controlled experiment and same-spot comparisons
- **Robustness** — wake lock, automatic session resume, recorded causes of stops, robustness charts

---

## Short Term

- **Faster recovery** — notice a killed session sooner than the 15-minute watchdog, and keep unsent samples on disk so a kill loses nothing
- **Robustness charts from session events** — break stops down by the recorded cause
- **Read-only Firestore key on the server** — replace the admin key used by the lab server's listener
- **Signal drop alerts** — push notification when RSRP falls below a user-configured threshold (e.g. below -110 dBm)
- **Export button** — one-tap share of CSV files via email, WhatsApp, or Google Drive from inside the app
- **Session summary** — show min/max/average RSRP after tapping Stop Logging

---

## Medium Term

- **Excel/chart export** — auto-generate RSRP vs time line chart as an image or Excel file
- **Multi-session view** — browse and compare data from previous logging sessions inside the app
- **Configurable logging interval** — let user set interval from 1 second to 60 seconds instead of fixed 5 seconds

---

## Long Term

- **Network quality score** — estimate Mean Opinion Score (MOS) from RSRP / RSRQ / SINR using standard 3GPP formulas
- **Operator benchmarking with Airtel** — add Airtel to the Jio vs Vi comparisons
- **Indoor vs outdoor detection** — correlate GPS accuracy with signal degradation to infer indoor/outdoor state
- **Automatic report generation** — generate a PDF summary report from logged CSV data

---

## Not Planned

- Root requirement — the app is designed to work without root and this will not change
- Call recording or interception — outside the scope of the project
- iOS version — Android-only by design due to telephony API differences