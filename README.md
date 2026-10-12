# NetworkLogger 📡

An Android application for real-time telecom network and device monitoring. It captures cell tower parameters (including the **frequency band**), GPS location, signal strength, throughput, and device health metrics every 5 seconds — keeping logs on the phone (developer mode) or uploading each session to Firebase Storage (production mode).

> Developed for academic and research purposes at **IIT Delhi**

**Language:** Kotlin  
**Platform:** Android (Min SDK 24 · Target SDK 36)

---

## Table of Contents

- [Motivation](#motivation)
- [What the App Does](#what-the-app-does)
- [Developer Mode vs Production Mode](#developer-mode-vs-production-mode)
- [Build Variants (internal vs public)](#build-variants-internal-vs-public)
- [Project Structure](#project-structure)
- [Architecture](#architecture)
- [Features](#features)
- [Band Detection](#band-detection)
- [Tech Stack & APIs](#tech-stack--apis)
- [CSV Output Format](#csv-output-format)
- [Setup & Installation](#setup--installation)
- [Permissions Explained](#permissions-explained)
- [Root Detection](#root-detection)
- [Known Behaviours](#known-behaviours)
- [Problems Solved](#problems-solved-during-development)
- [Data Pipeline & Analysis](#data-pipeline--analysis)
- [Testing](#testing)
- [Future Scope](#future-scope)

---

## Motivation

Existing Android network monitoring tools often have one or more of the following limitations:

- Require rooted devices to function
- Show only live values without continuous logging
- Do not combine telecom and device health information together
- Do not generate structured datasets suitable for research
- Are expensive professional tools (like Nemo or TEMS) unavailable to students

NetworkLogger was developed to solve these problems — providing a free, lightweight Android app that generates structured telecom datasets using only Android's public APIs, on any phone, without requiring root access.

---

## What the App Does

NetworkLogger runs two logging pipelines:

**Session logging (foreground service, every 5 s)**  
The user taps **START LOGGING**. `LoggingService` — a real foreground service with a persistent notification — samples GPS, the serving cell (ID, band, RSRP/RSRQ/SINR), network type, and throughput every 5 seconds into `network_logs`. Because it is a foreground service, logging keeps running while the app is in the background (e.g. during a browsing or streaming test).

**Background monitoring (WorkManager, every 15 min)**  
While a session is active, `NetworkWorker` records device health (battery, RAM, storage) and coarse network data into `background_logs`. It also acts as a **watchdog**: if a session claims to be active but has not logged for 10 minutes (the OS killed it), it posts a notification so the tester can restart.

On **STOP LOGGING**, what happens to the files depends on the mode (below). The app works on both **rooted and non-rooted** Android devices; root access is not required.

---

## Developer Mode vs Production Mode

| | Developer mode | Production mode |
|---|---|---|
| Where logs go | Stay on the phone | Uploaded to Firebase Storage on Stop |
| File location | `Download/NetworkLogger/session_<start time>/network_logs_<start time>.csv` (+ `background_logs_…`) | `Download/network_logs.csv`, `Download/background_logs.csv` (deleted after a successful upload) |
| App colours | Amber / brown, "DEVELOPER MODE" banner | Original navy / indigo |
| Default | **On** for a fresh install | — |

- Switch with the button in the mode bar under the header. Switching is blocked while a session is running.
- The mode is **captured when a session starts**; Stop acts on that mode, not on the toggle's current position. Developer sessions write straight into their own timestamped folder and never touch the production files, so dev data can never be uploaded later.
- Uploads go to `logs/<firebase uid>/<ANDROID_ID>/<sessionId>/` with metadata (tester name, device model, manufacturer, Android version, app version). **`sessionId` is the upload time, i.e. the end of the session.**

---

## Build Variants (internal vs public)

The app has two product flavors (`app/build.gradle.kts`), sharing one package name (`google-services.json` is registered for it):

| Flavor | Developer mode | Use |
|---|---|---|
| `internal` | Available (toggle shown) | Research phones, scripted experiments |
| `public` | Removed — mode bar hidden, always production | APK to share with ordinary users |

```bash
./gradlew :app:assembleInternalDebug     # app/build/outputs/apk/internal/debug/
./gradlew :app:assemblePublicRelease     # app/build/outputs/apk/public/release/
```

In Android Studio: **Build → Select Build Variant**. The public release is currently signed with the local debug key — fine for sharing with a few testers; switch to a dedicated release keystore before wide or Play Store distribution (users can't update across a signing-key change). Only one flavor can be installed on a phone at a time. Experiment scripts that tap Start/Stop by screen coordinates expect the **internal** build's layout.

---

## Project Structure

```
NetworkLogger/
│
├── README.md · CHANGELOG.md · ROADMAP.md · CONTRIBUTING.md · setupGUIDE.md
│
├── app/
│   ├── build.gradle.kts               ← SDK versions, flavors (internal/public), dependencies
│   ├── google-services.json           ← Firebase project config
│   └── src/
│       ├── main/
│       │   ├── java/com/example/networklogger/
│       │   │   ├── MainActivity.kt    ← UI, permissions, dev-mode toggle & colours, root detection
│       │   │   ├── LoggingService.kt  ← Foreground service: 5 s sampling, upload on Stop
│       │   │   ├── NetworkWorker.kt   ← 15 min device-health logging + session watchdog
│       │   │   ├── LogStorage.kt      ← Where each session's CSV rows go (dev folder vs Downloads)
│       │   │   └── BandInfo.kt        ← Serving-cell band from getBands() or EARFCN/NR-ARFCN tables
│       │   ├── res/layout/activity_main.xml
│       │   └── AndroidManifest.xml
│       └── test/.../BandInfoTest.kt   ← Unit tests for the channel → band lookup
│
├── grafana_pipeline/                  ← Firebase → InfluxDB → Grafana (see its README)
└── presentation_charts/               ← Analysis scripts and charts (see its README)
```

---

## Architecture

```
            User ──► MainActivity (UI, mode toggle, permissions)
                          │ Start / Stop
                          ▼
                   LoggingService  (foreground service, every 5 s)
          ┌───────────────┼──────────────────────────┐
          ▼               ▼                          ▼
 FusedLocationClient  TelephonyManager          TrafficStats
   (GPS fix)          allCellInfo → serving     (DL/UL kbps)
                      cell, BandInfo, RSRP…
          └───────────────┼──────────────────────────┘
                          ▼
              LogStorage.appendRow("network_logs")
                          │
            dev session ──┴── production session
                 │                    │
   Download/NetworkLogger/      Download/network_logs.csv
     session_<start>/                 │ on Stop
                                      ▼
                           Firebase Storage (anonymous auth)

   While a session runs:  WorkManager (every 15 min) ──► NetworkWorker
                          ├─ LogStorage.appendRow("background_logs")
                          └─ watchdog: session silent > 10 min → notification
```

---

## Features

### Telecom Features (network_logs)

- **GPS location** — latitude, longitude (altitude, speed, accuracy shown on screen)
- **Network type** — 2G / 3G / 4G / 4G (CA) / 4G (Advanced Pro) / 5G (NSA) / 5G, using `TelephonyDisplayInfo` so 5G NSA isn't misreported as plain 4G
- **Serving-cell band** — e.g. `B3`, `B41`, `n28`, `n78`, plus channel number and LTE channel width ([Band Detection](#band-detection))
- **Signal strength** — RSRP-based labels (Very Weak → Very Strong)
- **Throughput** — downlink / uplink kbps from `TrafficStats` (all traffic on the phone, not a speed test)
- **Screen state** — whether the screen was on for each sample

**LTE (4G) cell parameters:** MCC, MNC, PCI, TAC, local Cell ID (from ECI = 256 × eNB ID + Cell ID), EARFCN, band, bandwidth, RSRP, RSRQ  
**5G NR cell parameters:** MCC, MNC, NCI (36-bit), PCI, TAC, NR-ARFCN, band, SS-RSRP, SS-RSRQ, SS-SINR

### Device Monitoring Features (background_logs)

- Battery percentage, network type, operator, signal level, Cell ID, TAC
- Storage and RAM — total / used / free in GB
- Screen state
- Runs every 15 minutes while a session is active

### Reliability Features

- Foreground service keeps 5 s sampling alive when the app is backgrounded or the screen is off
- Session watchdog notification if the OS kills logging
- Header check: if an old-format CSV is found (different columns), it is renamed `<name>_old-format_<time>.csv` instead of being appended to

### Security Features

- Root detection using **7 independent methods**, shown as a red / green badge with the triggering method

---

## Band Detection

Implemented in [`BandInfo.kt`](app/src/main/java/com/example/networklogger/BandInfo.kt), called on every sample for the serving (registered) cell:

1. **Reported band (preferred).** On Android 11+ (API 30), `CellIdentityLte.getBands()` / `CellIdentityNr.getBands()` return the band from the modem via the radio HAL. Logged with `bandSource = reported`.
2. **Fallback from the channel number.** Some devices return an empty array, so the EARFCN / NR-ARFCN is mapped through the 3GPP downlink tables (TS 36.101 Table 5.7.3-1 for LTE, TS 38.104 Table 5.4.2.3-1 for NR). Logged with `bandSource = arfcn`.
3. **Overlapping NR bands** (e.g. n78 inside n77) are never guessed: all candidates are logged, narrowest first, e.g. `n78/n77`.
4. **5G NSA:** the registered cell is the LTE anchor, so `band` is the anchor's band. If the modem also lists the NR leg (as an unregistered `CellInfoNr`), its band is logged in `nrLegBand`; many devices don't, and it stays `N/A`.

Field tests (Oct 2026) on Samsung, Motorola, Nothing and moto phones returned the band via `getBands()` on every sample.

---

## Tech Stack & APIs

### Telephony APIs

| API | Purpose |
|-----|---------|
| `TelephonyManager.allCellInfo` | All visible cells; the serving cell is the one with `isRegistered` |
| `CellInfoLte` / `CellIdentityLte` / `CellSignalStrengthLte` | LTE parameters, `earfcn`, `bands`, `bandwidth` |
| `CellInfoNr` / `CellIdentityNr` / `CellSignalStrengthNr` | 5G NR parameters, `nrarfcn`, `bands`; `getDbm()` = SS-RSRP |
| `TelephonyCallback.DisplayInfoListener` (API 31+) / `PhoneStateListener` | `TelephonyDisplayInfo` to detect 5G NSA / LTE-CA |
| `TelephonyCallback.SignalStrengthsListener` | Live signal label while not logging |
| `requestCellInfoUpdate()` | Fresh cell info before the background worker reads it |

### Location, Background Work, Storage

| API | Purpose |
|-----|---------|
| `FusedLocationProviderClient.getCurrentLocation(PRIORITY_HIGH_ACCURACY)` | Fresh GPS fix each sample |
| Foreground `Service` (`location` + `dataSync` types) | 5 s sampling loop that survives backgrounding |
| `WorkManager` periodic (15 min) + one-time request | Background device-health logging and watchdog |
| `TrafficStats.getTotalRx/TxBytes` | Throughput between samples |
| `MediaStore.Downloads` with `RELATIVE_PATH` | Writes CSVs into Downloads or `Download/NetworkLogger/session_…/` |
| Firebase Storage + Firebase Auth (anonymous) | Uploading production sessions with metadata |

### SDK Configuration

```
compileSdk = 36 · targetSdk = 36 · minSdk = 24 · JDK 11
```

### Dependencies

```kotlin
implementation("androidx.appcompat:appcompat:1.6.1")
implementation("com.google.android.gms:play-services-location:21.0.1")
implementation("androidx.work:work-runtime-ktx:2.9.0")
implementation("androidx.cardview:cardview:1.0.0")
implementation("com.google.android.material:material:1.11.0")
implementation(platform("com.google.firebase:firebase-bom:33.13.0"))
implementation("com.google.firebase:firebase-storage-ktx")
implementation("com.google.firebase:firebase-auth-ktx")
```

---

## CSV Output Format

### network_logs

Recorded every **5 seconds** while logging is active. Columns are appended at the end when new fields are added, so scripts that select columns by name keep working.

| Column | Description |
|--------|-------------|
| `time` | `HH:mm:ss` (the date comes from the session — see note below) |
| `lat`, `lon` | GPS latitude / longitude (7 decimals) |
| `network` | 2G / 3G / 4G / 4G (CA) / 4G (Advanced Pro) / 5G (NSA) / 5G / Unknown |
| `signal` | Very Weak / Weak / Medium / Strong / Very Strong (from RSRP) |
| `operator` | Operator name as shown by the phone |
| `mcc`, `mnc` | Mobile country / network code (405-8xx = Jio, 404-11 = Vi) |
| `pci`, `tac` | Physical Cell ID, Tracking Area Code |
| `nci` | NR Cell Identity (5G) or local Cell ID 0–255 (4G) |
| `rsrp` | dBm — LTE RSRP, or SS-RSRP on a 5G serving cell |
| `rsrq` | dB |
| `sinr` | dB — 5G only, `N/A` on 4G |
| `neighborCount` | Number of cells the phone currently sees |
| `dlKbps`, `ulKbps` | Throughput of all phone traffic since the previous sample |
| `screenOn` | `ON` / `OFF` |
| `arfcn` | EARFCN (4G) or NR-ARFCN (5G) |
| `band` | e.g. `B3`, `B41`, `n78`; `n78/n77` when only the channel table was available and bands overlap |
| `bandSource` | `reported` (phone's `getBands()`) or `arfcn` (derived) |
| `bandwidthMHz` | LTE channel width (Android 9+) |
| `nrLegBand` | 5G NSA only: band of the NR leg when the phone reports it |

**Example row (Vi 4G, Delhi — real sample, position rounded):**
```
17:25:13,28.5450,77.1901,4G,Strong,Vi India,404,011,489,52506,21,-83,-16,N/A,1,350.1,19.2,OFF,1421,B3,reported,N/A,N/A
```
`bandwidthMHz` is `N/A` here because this phone (Samsung, Android 12) doesn't report the LTE channel width.

> **Timestamps:** rows only carry `HH:mm:ss`. The uploaded `sessionId` (`yyyyMMdd_HHmmss`) is stamped at **upload — the end of the session** — so reconstruct dates by anchoring the last row on that date and walking backwards.

### background_logs

| Column | Description |
|--------|-------------|
| `Time` | `yyyy-MM-dd HH:mm:ss` |
| `Battery` | 0–100 |
| `NetworkType`, `Operator` | 2G–5G / `No Permission`; operator name |
| `SignalLevel` | RSRP in dBm |
| `CellID`, `TAC` | Serving cell |
| `TotalStorage`, `UsedStorage`, `FreeStorage` | GB |
| `TotalRAM`, `UsedRAM`, `AvailableRAM` | GB |
| `ScreenOn` | `ON` / `OFF` |

---

## Setup & Installation

### Requirements

- Android Studio (latest stable), JDK 11
- Physical Android phone, API 24+ (emulators don't return real cell data)

### Steps to Run

```bash
git clone https://github.com/daksh-iitd/NetworkLogger.git
# Android Studio → File → Open → the project folder → let Gradle sync
# Build → Select Build Variant → internalDebug (research) or publicRelease (sharing)
# Connect the phone with USB debugging enabled → Run ▶
```

See [setupGUIDE.md](setupGUIDE.md) for a step-by-step walkthrough.

### First Launch Checklist

1. Allow **Location** and **Phone** permissions (and **Notifications** on Android 13+)
2. Allow the battery-optimisation exemption
3. **Settings → Apps → NetworkLogger → Battery → No Restrictions**
4. Enable **Autostart** for NetworkLogger (Realme / Xiaomi / OPPO / OnePlus)
5. Enter a tester name and tap **Save** (goes into upload metadata)
6. Internal build only: choose Developer or Production mode

### File Locations on Device

```
Developer mode:  /storage/emulated/0/Download/NetworkLogger/session_<start time>/
Production mode: /storage/emulated/0/Download/network_logs.csv
                 /storage/emulated/0/Download/background_logs.csv   (until uploaded)
```

```bash
adb pull /storage/emulated/0/Download/NetworkLogger/ ./phone_logs/
```

---

## Permissions Explained

| Permission | Why it is needed |
|------------|-----------------|
| `ACCESS_FINE_LOCATION` / `ACCESS_COARSE_LOCATION` | Required by Android for `allCellInfo` and for GPS |
| `READ_PHONE_STATE` | Network type, `TelephonyDisplayInfo` (5G NSA), operator |
| `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_LOCATION`, `FOREGROUND_SERVICE_DATA_SYNC` | The logging service and background worker (mandatory types on Android 14+) |
| `POST_NOTIFICATIONS` | Logging notification and watchdog alerts (Android 13+) |
| `INTERNET` | Uploading production sessions to Firebase |
| `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` | Asks to be exempt so logging isn't killed |

> **Why does the app say "make and manage phone calls"?**  
> `READ_PHONE_STATE` belongs to Android's "Phone" permission group, which uses that generic label. The app **cannot** make calls or read call history; it only reads network state.

---

## Root Detection

The app detects rooted devices using 7 independent methods. If any method fires, the device is marked as Rooted with a red badge.

| Method | What it checks |
|--------|---------------|
| `checkSuBinaries()` | 12 filesystem paths for `su` binary |
| `checkRootPackages()` | 12 known root manager packages (Magisk, SuperSU, KingRoot, etc.) |
| `checkBuildTags()` | `Build.TAGS` system property for `test-keys` string |
| `checkDangerousProps()` | System properties: `ro.debuggable=1`, `ro.secure=0`, `ro.build.type=eng` |
| `checkRWPaths()` | `/system` mounted read-write via `mount` command output |
| `checkRootCloakingApps()` | Xposed Framework, RootCloak, HideMyRoot, Substrate packages |
| `tryExecuteSu()` | Executes `su -c id` and checks output for `uid=0` — most reliable check |

Root access is **not required** for the app to function.

---

## Known Behaviours

### 5G NSA: `rsrp` is the LTE anchor
On 5G NSA (e.g. Vi), the registered cell is the 4G anchor, so `rsrp`/`band` describe the anchor; `network` still shows `5G (NSA)`. The NR leg's signal isn't logged yet.

### 5G SS-RSRP reads lower than LTE RSRP
On a 5G serving cell `rsrp` is SS-RSRP, measured on different reference signals and typically a few dB below LTE RSRP — don't compare them one-to-one.

### Invalid readings from some modems
When the modem has no measurement, Android can return `Integer.MAX_VALUE` (2147483647), and some phones (seen on A001 and Motorola) report RSRP −44 with RSRQ −3 — both at the top of Android's range. Treat these as missing; the analysis and Grafana loaders drop them.

### Throughput is passive
`dlKbps`/`ulKbps` count *all* traffic on the phone; near zero usually means the phone was idle, not that the network is slow. Use a speed test (e.g. the ndt7 experiment scripts) to measure capacity.

### "Unknown" network type
Shown when phone-state permission is missing or the type isn't mapped. The cell data is still valid: an NCI > 255 means a 5G serving cell.

### Cell Info: Not Available (brief flicker)
`allCellInfo` can be empty during the modem's refresh; the app recovers on the next 5 s cycle.

### Logging slows on aggressive OEM battery management
Some OEMs throttle or kill background apps despite the foreground service. Enable **No Restrictions** and **Autostart**; the watchdog notifies if a session dies.

### Force-stopping right after Stop
If the app is killed before the upload finishes (e.g. by a script's `am force-stop`), the CSV isn't cleared and that run is uploaded again inside the next session. Allow ~20 s after Stop; the analysis loaders de-duplicate by device and timestamp.

---

## Problems Solved During Development

| Problem | Root Cause | Fix Applied |
|---------|-----------|-------------|
| CSV files invisible in Files app | `getExternalFilesDir()` saves to a hidden sandboxed folder on Android 10+ | Migrated to `MediaStore.Downloads` |
| New CSV file created every 5 s | `IS_PENDING = 1` hid the file from later queries | `IS_PENDING = 0` filter on queries |
| RSRQ and SINR always N/A on 5G | Read `csiRsrq` / `csiSinr`; modems report SS fields | `ssRsrq` / `ssSinr` with CSI fallback |
| 5 s sampling throttled to minutes with screen off | Handler loop on the Activity was frozen by Doze | Moved to a foreground `LoggingService` |
| 5G NSA reported as plain 4G | `networkType` reports LTE on NSA | `TelephonyDisplayInfo.overrideNetworkType` |
| Serving cell sometimes wrong | `allCellInfo` order isn't guaranteed | Pick the cell with `isRegistered` |
| LTE "Cell ID" was the full ECI | `CellIdentityLte.ci` = 256 × eNB + Cell ID | Decomposed per 3GPP |
| Silent session death | OS killed the process without Stop | WorkManager watchdog + notification |
| Dev-mode data could reach Firebase | Mode was read at Stop, and dev rows shared the upload files | Mode captured at Start; dev sessions write to their own folder |
| Band unknown for analysis | Only shown on screen | `BandInfo` + `arfcn/band/bandSource/bandwidthMHz/nrLegBand` columns |
| App crash on rooted OnePlus (Android 14) | Missing `foregroundServiceType` | Declared service types in manifest + `ForegroundInfo` |
| App crash on rooted Android 12+ | `PhoneStateListener` blocked | `TelephonyCallback` on API 31+ |
| GPS not updating while moving | `lastLocation` is cached | `getCurrentLocation()` each cycle |

---

## Data Pipeline & Analysis

- **[grafana_pipeline/](grafana_pipeline/README.md)** — `fetch_logs.py` downloads all sessions from Firebase Storage (service-account key), `pull_and_load_influx.py --mirror` loads them into InfluxDB with corrected timestamps, de-duplication and an `op` (Jio/Vi) tag, and the **NetworkLogger Map** Grafana dashboard shows RSRP and band on Geomap panels.
- **[presentation_charts/](presentation_charts/README.md)** — scripts for route maps, campus RSRP/band maps, the controlled Jio-vs-Vi experiment, and cross-operator comparisons.

---

## Testing

- **Unit tests:** `./gradlew :app:testDebugUnitTest` — channel → band lookup (`BandInfoTest`).
- **Devices used for field data (2026):** OnePlus 11R CPH2487 ×2 (Android 14, rooted; Jio and Vi, controlled table experiment), Samsung SM-M325F (Android 12, Vi), Nothing A001 (Android 16, Vi), Motorola edge 50 neo (Android 16, Jio), moto g35 (Vi), Xiaomi, Infinix and Realme devices; ~60k GPS-tagged samples around IIT Delhi.
- **Observed with band logging:** Jio on n78 (3.5 GHz) and n28 (700 MHz); Vi on B3, B8 and B41 — Vi's B41 reads ~14 dB weaker than B3 at the same spot.

---

## Future Scope

Done since the first version: cloud upload (Firebase), coverage maps, multi-device aggregation, operator comparison, band logging.

- **NR-leg signal for 5G NSA** (`nrLegRsrp` from `getSignalStrength().getCellSignalStrengths()`)
- **Write `N/A` for invalid readings** (`Integer.MAX_VALUE`, −44/−3) at the source
- **Handover events** — log each serving-cell change explicitly
- **Total channel bandwidth** per connection (`ServiceState.getCellBandwidths()`)
- **Active tests in-app** — periodic latency / throughput probes
- **Session notes** — movement, indoor/outdoor, phone placement, 5G setting, stored with each session
- **Dedicated release keystore** for the public build
