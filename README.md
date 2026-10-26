# NetworkLogger 📡

An Android application for real-time telecom network and device monitoring. It captures cell tower parameters (including the **frequency band**), GPS location, signal strength, throughput, and device health metrics every 5 seconds — keeping logs on the phone (developer mode) or streaming them to Cloud Firestore every minute while the session runs (production mode).

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
The user taps **START LOGGING** (one button: it turns into a red **STOP LOGGING** while a session runs). `LoggingService` — a real foreground service with a persistent notification — samples GPS, the serving cell (ID, band, RSRP/RSRQ/SINR), network type, and throughput every 5 seconds into `network_logs`. Because it is a foreground service, logging keeps running while the app is in the background (e.g. during a browsing or streaming test).

**Background monitoring (WorkManager, every 15 min)**  
While a session is active, `NetworkWorker` records device health (battery, RAM, storage) and coarse network data into `background_logs`. It also acts as a **watchdog**: if a session claims to be active but has not logged for 10 minutes (the OS killed it), it **restarts logging and continues the same session**; if Android won't allow that (no battery-optimisation exemption or no "Allow all the time" location), it posts a notification so the tester can restart by hand.

On **STOP LOGGING**, what happens to the files depends on the mode (below). The app works on both **rooted and non-rooted** Android devices; root access is not required.

---

## Developer Mode vs Production Mode

| | Developer mode | Production mode |
|---|---|---|
| Where logs go | Stay on the phone | Streamed to Cloud Firestore every 60 s during the session |
| File location | `Download/NetworkLogger/session_<start time>/network_logs_<start time>.csv` (+ `background_logs_…`) | No CSV on the phone; Firestore queues unsent batches on disk while offline |
| App colours | Amber / brown, "DEVELOPER MODE" banner | Original navy / indigo |
| Default | **On** for a fresh install | — |

- Switch with the button in the mode bar under the header. Switching is blocked while a session is running.
- The mode is **captured when a session starts**; Stop acts on that mode, not on the toggle's current position. Developer sessions write straight into their own timestamped folder and never go through `CloudSync`, so dev data can never be uploaded.
- Production data goes to Firestore (`CloudSync.kt`):
  - `users/<firebase uid>/sessions/<ANDROID_ID>_<start yyyyMMdd_HHmmss>` — tester name, device model, manufacturer, Android/app version, `startedAtMs`, `endedAtMs`, `status` (`active` / `ended` / `died`)
  - `…/batches/<seq>` — one document per minute; `rows` holds that minute's 5 s samples, each with an epoch-ms `ts` and the `network_logs` columns as typed values
  - `…/background/<auto id>` — one document per 15-minute `NetworkWorker` run
  - On the session document, `restarts` counts automatic resumes and `events` records why logging stopped: Android's process-exit reason (e.g. `USER_REQUESTED: stop com.google.android.gms due to installPackageLI` when Google Play services updates), `service_destroyed`, `task_removed` (swiped away), `fgs_timeout`, and each `resumed` with its gap
- Security rules are in [firestore.rules](firestore.rules): a phone may only create documents under its own anonymous uid and cannot read anything.
- Throughput excludes the app's own traffic, so the uploads don't show up as measured DL/UL.
- Sessions uploaded by older app versions (CSV files in Firebase Storage under `logs/…`) are unchanged and still read by `fetch_logs.py`.

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

In Android Studio: **Build → Select Build Variant**. The public release is currently signed with the local debug key — fine for sharing with a few testers; switch to a dedicated release keystore before wide or Play Store distribution (users can't update across a signing-key change). Only one flavor can be installed on a phone at a time. Experiment scripts that tap Start/Stop by screen coordinates expect the **internal** build's layout. Start and Stop are the same full-width button, so a script must tap it once to start and once to stop, and can't recover by tapping "Stop" if the session is already stopped.

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
│       │   │   ├── LoggingService.kt  ← Foreground service: 5 s sampling, 60 s cloud flush
│       │   │   ├── NetworkWorker.kt   ← 15 min device-health logging + session watchdog
│       │   │   ├── LogStorage.kt      ← Session mode; developer-mode CSV files
│       │   │   ├── CloudSync.kt       ← Production: buffers samples, writes Firestore batches, resumes sessions
│       │   │   ├── SessionDiagnostics.kt ← Why logging stopped (Android exit reasons) → session events
│       │   │   └── BandInfo.kt        ← Serving-cell band from getBands() or EARFCN/NR-ARFCN tables
│       │   ├── res/layout/activity_main.xml
│       │   └── AndroidManifest.xml
│       └── test/.../BandInfoTest.kt   ← Unit tests for the channel → band lookup
│
├── firestore.rules                    ← Firestore security rules (phones write only their own data)
├── grafana_pipeline/                  ← Firestore/Storage → InfluxDB → Grafana on the Mac, incl. live listener (see its README)
├── server/                            ← Same pipeline as an always-on service on the lab server (see its README)
└── presentation_charts/               ← Analysis scripts and charts, incl. app robustness (see its README)
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
            dev session ──┴── production session
                 │                    │
   LogStorage.appendRow       CloudSync.addSample (memory)
                 │                    │ every 60 s
   Download/NetworkLogger/            ▼
     session_<start>/        Cloud Firestore (anonymous auth,
                              offline queue on the phone)

   While a session runs:  WorkManager (every 15 min) ──► NetworkWorker
                          ├─ background row → CSV (dev) / Firestore (production)
                          └─ watchdog: session silent > 10 min → resume same session
                                       (or notification if Android won't allow it)
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
- Partial wake lock while logging, so the 5 s timer keeps running when the idle phone sleeps (Doze)
- Firestore keeps unsent batches on the phone while offline and uploads them when the connection returns
- If Android kills logging (e.g. a Google Play services update), the session resumes by itself — after a restart by Android immediately, otherwise via the 15-minute watchdog — with the cause recorded on the session
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
| `TrafficStats.getTotalRx/TxBytes` minus `getUidRx/TxBytes` | Throughput between samples, excluding the app's own uploads |
| `PowerManager.PARTIAL_WAKE_LOCK` | Keeps the sampling timer running while the phone is idle |
| `ActivityManager.getHistoricalProcessExitReasons` (API 30+) | Why the app's process ended, stored on the session |
| `MediaStore.Downloads` with `RELATIVE_PATH` | Writes CSVs into Downloads or `Download/NetworkLogger/session_…/` |
| Cloud Firestore + Firebase Auth (anonymous) | Streaming production sessions with metadata |

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
implementation("com.google.firebase:firebase-firestore")
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

> **Timestamps:** CSV rows (developer mode, and production sessions from older app versions) only carry `HH:mm:ss`. For the old Storage uploads the `sessionId` (`yyyyMMdd_HHmmss`) was stamped at **upload — the end of the session** — so dates are reconstructed by anchoring the last row on that date and walking backwards. Firestore rows carry a full epoch-ms `ts` instead.

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
2. When asked again for location, choose **Allow all the time** — needed for the automatic resume after a kill
3. Allow the battery-optimisation exemption
4. **Settings → Apps → NetworkLogger → Battery → No Restrictions** (Samsung: also add it to *Never sleeping apps*)
5. Enable **Autostart** for NetworkLogger (Realme / Xiaomi / OPPO / OnePlus)
6. Enter a tester name and tap **Save** (goes into the session's cloud metadata)
7. Internal build only: choose Developer or Production mode

### File Locations on Device

```
Developer mode:  /storage/emulated/0/Download/NetworkLogger/session_<start time>/
Production mode: nothing — rows are streamed to Firestore
```

```bash
adb pull /storage/emulated/0/Download/NetworkLogger/ ./phone_logs/
```

---

## Permissions Explained

| Permission | Why it is needed |
|------------|-----------------|
| `ACCESS_FINE_LOCATION` / `ACCESS_COARSE_LOCATION` | Required by Android for `allCellInfo` and for GPS |
| `ACCESS_BACKGROUND_LOCATION` | "Allow all the time": a logging service restarted from the background can only read GPS/cells with it (Android 11+) |
| `WAKE_LOCK` | Keeps the CPU awake during a session so sampling doesn't stall in Doze |
| `READ_PHONE_STATE` | Network type, `TelephonyDisplayInfo` (5G NSA), operator |
| `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_LOCATION`, `FOREGROUND_SERVICE_DATA_SYNC` | The logging service and background worker (mandatory types on Android 14+) |
| `POST_NOTIFICATIONS` | Logging notification and watchdog alerts (Android 13+) |
| `INTERNET` | Streaming production sessions to Firestore |
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
Some OEMs throttle or kill background apps despite the foreground service (the Motorola g35 restarted logging hundreds of times in Oct 2026). Enable **No Restrictions** and **Autostart**; killed sessions now resume by themselves and record the cause.

### Google Play services updates stop the app
When Google Play services updates itself (usually while charging), Android stops every app using it, NetworkLogger included (exit reason `stop com.google.android.gms due to installPackageLI`). Android doesn't restart the service after this kind of stop; the watchdog resumes the session within 10–25 minutes, and that gap is lost.

### Force-stopping right after Stop
Production samples are held in memory for up to 60 s before being handed to Firestore, so if the app is force-stopped (e.g. by a script's `am force-stop`) the last partial minute is lost. Batches already handed over survive: Firestore keeps them on disk and sends them the next time the app runs. The very first sync on a phone needs a network connection for the anonymous sign-in; until it succeeds, samples wait in memory.

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
| >1 min gaps overnight (25% of session time on the Samsung) | No wake lock: the timer stopped while the idle phone slept (Doze) | Partial wake lock while logging |
| Sessions died when Google Play services updated | Android stops apps depending on Play services | Watchdog resumes the same session |
| Hundreds of empty sessions (Motorola) | Each automatic restart started a new session, losing unsent samples | A restart continues the session in progress |
| Causes of deaths unknown | Nothing recorded at the time | Exit reasons and service lifecycle events stored on the session |
| Dev-mode data could reach Firebase | Mode was read at Stop, and dev rows shared the upload files | Mode captured at Start; dev sessions write to their own folder |
| Band unknown for analysis | Only shown on screen | `BandInfo` + `arfcn/band/bandSource/bandwidthMHz/nrLegBand` columns |
| App crash on rooted OnePlus (Android 14) | Missing `foregroundServiceType` | Declared service types in manifest + `ForegroundInfo` |
| App crash on rooted Android 12+ | `PhoneStateListener` blocked | `TelephonyCallback` on API 31+ |
| GPS not updating while moving | `lastLocation` is cached | `getCurrentLocation()` each cycle |

---

## Data Pipeline & Analysis

- **[grafana_pipeline/](grafana_pipeline/README.md)** — on the Mac: `firestore_listener.py` streams new Firestore batches into InfluxDB as they arrive (**NetworkLogger Live** dashboard, ~1 min behind the phone); `fetch_logs.py` + `pull_and_load_influx.py --mirror` load the older Storage CSV sessions with corrected timestamps, de-duplication and an `op` (Jio/Vi) tag; the **NetworkLogger Map** dashboard shows RSRP and band on Geomap panels.
- **[server/](server/README.md)** — the same pipeline as an always-on service on the lab server (no Docker or sudo; cron watchdog). Dashboards for anyone on the IITD network, view-only: http://tejas.cse.iitd.ac.in:3300/d/networklogger-live and `/d/networklogger-map`.
- **[presentation_charts/](presentation_charts/README.md)** — scripts for route maps, campus RSRP/band maps, the controlled Jio-vs-Vi experiment, cross-operator comparisons, and **app robustness** (when and why logging stopped, sampling gaps, upload delay).

---

## Testing

- **Unit tests:** `./gradlew :app:testInternalDebugUnitTest` — channel → band lookup (`BandInfoTest`).
- **Robustness:** `presentation_charts/robustness/` measures how reliably sessions log in the field (13–26 Oct 2026: uploads 90% within 10 s and no batch lost; gaps almost only with the screen off; Samsung deaths traced to Google Play services updates).
- **Devices used for field data (2026):** OnePlus 11R CPH2487 ×2 (Android 14, rooted; Jio and Vi, controlled table experiment), Samsung SM-M325F (Android 12, Vi), Nothing A001 (Android 16, Vi), Motorola edge 50 neo (Android 16, Jio), moto g35 (Vi), Xiaomi, Infinix and Realme devices; ~60k GPS-tagged samples around IIT Delhi.
- **Observed with band logging:** Jio on n78 (3.5 GHz) and n28 (700 MHz); Vi on B3, B8 and B41 — Vi's B41 reads ~14 dB weaker than B3 at the same spot.

---

## Future Scope

Done since the first version: live cloud streaming (Firestore), live and map dashboards (Grafana, also on the lab server), coverage maps, multi-device aggregation, operator comparison, band logging, automatic session resume with recorded causes.

- **Faster recovery** — detect a killed session sooner than the 10–25 min watchdog and keep unsent samples on disk

- **NR-leg signal for 5G NSA** (`nrLegRsrp` from `getSignalStrength().getCellSignalStrengths()`)
- **Write `N/A` for invalid readings** (`Integer.MAX_VALUE`, −44/−3) at the source
- **Handover events** — log each serving-cell change explicitly
- **Total channel bandwidth** per connection (`ServiceState.getCellBandwidths()`)
- **Active tests in-app** — periodic latency / throughput probes
- **Session notes** — movement, indoor/outdoor, phone placement, 5G setting, stored with each session
- **Dedicated release keystore** for the public build
