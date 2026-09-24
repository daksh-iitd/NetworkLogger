# Roadmap

Planned features and improvements for NetworkLogger.

---

## Short Term

- **Coverage heatmap** — overlay GPS coordinates + RSRP values on Google Maps to visualize signal strength across a walking route
- **Signal drop alerts** — push notification when RSRP falls below a user-configured threshold (e.g. below -110 dBm)
- **Export button** — one-tap share of CSV files via email, WhatsApp, or Google Drive from inside the app
- **Session summary** — show min/max/average RSRP after tapping Stop Logging

---

## Medium Term

- **Cloud synchronization** — auto-upload CSV files to Firebase or Google Drive after each logging session
- **Excel/chart export** — auto-generate RSRP vs time line chart as an image or Excel file
- **Multi-session view** — browse and compare data from previous logging sessions inside the app
- **Configurable logging interval** — let user set interval from 1 second to 60 seconds instead of fixed 5 seconds

---

## Long Term

- **Multi-device aggregation** — collect signal data from multiple phones simultaneously and merge into one dataset
- **Network quality score** — estimate Mean Opinion Score (MOS) from RSRP / RSRQ / SINR using standard 3GPP formulas
- **Operator benchmarking** — collect and compare JIO vs Airtel vs Vi signal on the same route side by side
- **Indoor vs outdoor detection** — correlate GPS accuracy with signal degradation to infer indoor/outdoor state
- **Automatic report generation** — generate a PDF summary report from logged CSV data

---

## Not Planned

- Root requirement — the app is designed to work without root and this will not change
- Call recording or interception — outside the scope of the project
- iOS version — Android-only by design due to telephony API differences