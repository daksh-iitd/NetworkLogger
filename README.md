# NetworkLogger 📡

An Android application for real-time telecom network and device monitoring. It captures cell tower parameters, GPS location, signal strength, and device health metrics — saving everything as CSV files directly in the phone's Downloads folder.

> Developed for academic and research purposes at **IIT Delhi**

**Language:** Kotlin  
**Platform:** Android (Min SDK 24 · Target SDK 36)

---

## Table of Contents

- [Motivation](#motivation)
- [What the App Does](#what-the-app-does)
- [Project Structure](#project-structure)
- [Architecture](#architecture)
- [Features](#features)
- [Tech Stack & APIs](#tech-stack--apis)
- [CSV Output Format](#csv-output-format)
- [Setup & Installation](#setup--installation)
- [Permissions Explained](#permissions-explained)
- [Root Detection](#root-detection)
- [Known Behaviours](#known-behaviours)
- [Problems Solved](#problems-solved-during-development)
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

NetworkLogger runs two independent logging systems simultaneously:

**Foreground Logging (manual)**  
The user taps **START LOGGING** and the app records network + GPS data every 5 seconds into `network_logs.csv`.

**Background Logging (automatic)**  
A background worker runs every 15 minutes automatically — even when the app is closed — saving device health data into `background_logs.csv`.

Both files are saved to `/storage/emulated/0/Download/` and are immediately visible in the phone's Files app without any special access.

The app works on both **rooted and non-rooted** Android devices. Root access is not required.

---

## Project Structure

```
NetworkLogger/
│
├── README.md
├── CHANGELOG.md
├── ROADMAP.md
├── CONTRIBUTING.md
│
├── app/
│   └── src/main/
│       ├── java/com/example/networklogger/
│       │   ├── MainActivity.kt        ← Main screen, UI, foreground logging
│       │   └── NetworkWorker.kt       ← Background worker, device monitoring
│       ├── res/
│       │   ├── layout/
│       │   │   └── activity_main.xml  ← App UI layout
│       │   ├── drawable/
│       │   │   ├── badge_green.xml    ← Green badge for Non-Rooted status
│       │   │   ├── badge_red.xml      ← Red badge for Rooted status
│       │   │   └── badge_amber.xml    ← Amber badge for signal display
│       │   └── values/
│       │       └── themes.xml         ← App theme (Material3)
│       └── AndroidManifest.xml        ← Permissions + service declarations
│
└── screenshots/
    ├── home_screen.png
    ├── cell_info_5g.png
    └── logs.png
```

---

## Architecture

```
                        User
                          │
                          ▼
                    MainActivity
                          │
           ┌──────────────┴──────────────┐
           │                             │
           ▼                             ▼
    FusedLocationClient           TelephonyManager
    (GPS coordinates)         (Cell info, signal, network)
           │                             │
           └──────────────┬──────────────┘
                          ▼
                  updateMeasurements()
                     every 5 sec
                          │
                          ▼
                   saveLog() → network_logs.csv
                   (MediaStore Downloads API)

                          │
                          ▼

                     WorkManager
                          │
              ┌───────────┴────────────┐
              │                        │
              ▼                        ▼
    OneTimeWorkRequest        PeriodicWorkRequest
    (fires on app launch)     (every 15 minutes)
              │                        │
              └───────────┬────────────┘
                          ▼
                   NetworkWorker
                          │
                          ▼
              saveBackgroundLog() → background_logs.csv
              (MediaStore Downloads API)
```

---

## Features

### Telecom Features (network_logs.csv)

- **GPS location tracking** — latitude, longitude, altitude, speed, accuracy
- **Network type detection** — 2G / 3G / 4G / 5G
- **Signal strength** — RSRP-based labels (Very Weak → Very Strong)

**LTE (4G) cell parameters:**

| Parameter | Description |
|-----------|-------------|
| MCC | Mobile Country Code |
| MNC | Mobile Network Code |
| CID | Cell Identity |
| PCI | Physical Cell Identifier |
| TAC | Tracking Area Code |
| EARFCN | E-UTRA Absolute Radio Frequency Channel Number |
| RSRP | Reference Signal Received Power |
| RSRQ | Reference Signal Received Quality |

**5G NR cell parameters:**

| Parameter | Description |
|-----------|-------------|
| NCI | NR Cell Identity (36-bit) |
| PCI | Physical Cell Identifier (0-1007) |
| TAC | Tracking Area Code |
| NRARFCN | NR Absolute Radio Frequency Channel Number |
| SS-RSRP | Synchronization Signal RSRP |
| SS-RSRQ | Synchronization Signal RSRQ |
| SS-SINR | Signal to Interference plus Noise Ratio |

- **Neighbor cell detection** — captures handover events when phone switches towers
- **Logging duration timer** — HH:MM:SS display
- **Start / Stop logging buttons**

---

### Device Monitoring Features (background_logs.csv)

- Battery percentage
- Network type and operator name
- Signal level in dBm
- Storage usage — Total / Used / Free in GB (decimal precision)
- RAM usage — Total / Used / Available in GB (decimal precision)
- Runs every 15 minutes via WorkManager
- Also fires once immediately on every app launch

---

### Security Features

- Root detection using **7 independent methods**
- Shows "Rooted" (red badge) or "Non-Rooted" (green badge) in the UI header
- Device card shows which specific detection method triggered

---

## Tech Stack & APIs

### Telephony APIs

| API | Purpose |
|-----|---------|
| `TelephonyManager.allCellInfo` | Reads all visible cell towers (serving + neighbors) |
| `CellInfoLte` / `CellIdentityLte` / `CellSignalStrengthLte` | LTE cell parameters |
| `CellInfoNr` / `CellIdentityNr` / `CellSignalStrengthNr` | 5G NR cell parameters |
| `TelephonyCallback` (API 31+) | Signal strength listener for Android 12+ |
| `PhoneStateListener` (deprecated, API < 31) | Signal strength listener for older Android |
| `telephonyManager.requestCellInfoUpdate()` | Forces fresh cell info from modem |

### Location APIs

| API | Purpose |
|-----|---------|
| `FusedLocationProviderClient` | Google Play Services GPS — combines GPS, WiFi, cell signals |
| `getCurrentLocation(PRIORITY_HIGH_ACCURACY)` | One-shot fresh GPS fix per cycle |

### Background Work APIs

| API | Purpose |
|-----|---------|
| `WorkManager` | Schedules reliable background tasks that survive app kill |
| `OneTimeWorkRequestBuilder` | Fires worker immediately on app launch |
| `PeriodicWorkRequestBuilder` (15 min) | Repeating background schedule |
| `CoroutineWorker` | Worker base class with coroutine/suspend support |
| `setForeground(ForegroundInfo)` | Keeps worker alive on OEM phones with aggressive killing |
| `ExistingPeriodicWorkPolicy.UPDATE` | Replaces old schedule when app is reopened |

### File Storage APIs

| API | Purpose |
|-----|---------|
| `MediaStore.Downloads` | Saves CSV to Downloads folder (Android 10+ standard) |
| `ContentResolver.openOutputStream(uri, "wa")` | Appends rows to existing file |
| `IS_PENDING = 0` filter in query | Prevents duplicate file creation |
| `ContentResolver.insert()` | Creates new file entry in MediaStore |
| `ContentUris.withAppendedId()` | Builds URI from MediaStore row ID |

### Device Monitoring APIs

| API | Purpose |
|-----|---------|
| `ActivityManager.MemoryInfo` | Total, used, and available RAM |
| `StatFs(Environment.getDataDirectory())` | Total, used, and free storage |
| `BatteryManager` via `ACTION_BATTERY_CHANGED` | Battery percentage |
| `PowerManager.isIgnoringBatteryOptimizations` | Checks if app has battery exemption |

### SDK Configuration

```
compileSdk = 36
targetSdk  = 36
minSdk     = 24
```

### Dependencies

```kotlin
implementation("androidx.appcompat:appcompat:1.6.1")
implementation("com.google.android.gms:play-services-location:21.0.1")
implementation("androidx.work:work-runtime-ktx:2.9.0")
implementation("androidx.cardview:cardview:1.0.0")
implementation("com.google.android.material:material:1.11.0")
```

---

## CSV Output Format

### network_logs.csv

Recorded every **5 seconds** while Start Logging is active.

| Column | Description |
|--------|-------------|
| `time` | Timestamp HH:mm:ss |
| `lat` | GPS Latitude (7 decimal places) |
| `lon` | GPS Longitude (7 decimal places) |
| `network` | 2G / 3G / 4G / 5G |
| `signal` | Very Weak / Weak / Medium / Strong / Very Strong |
| `operator` | Operator name (JIO, airtel, etc.) |
| `pci` | Physical Cell Identifier |
| `tac` | Tracking Area Code |
| `nci` | NR Cell Identity (5G) or Cell ID (4G) |
| `rsrp` | Signal power in dBm |
| `rsrq` | Signal quality in dB |
| `sinr` | Signal-to-noise ratio in dB (5G only, N/A for 4G) |
| `neighborCount` | Number of visible cell towers |

**Example row (JIO 5G, Delhi):**
```
15:32:13,28.5451308,77.1971345,5G,Medium,JIO,529,21,4328783889,-93,-7,8,4
```

---

### background_logs.csv

Recorded automatically every **15 minutes** regardless of app state.

| Column | Description |
|--------|-------------|
| `Time` | Timestamp yyyy-MM-dd HH:mm:ss |
| `Battery` | Battery percentage (0-100) |
| `NetworkType` | 2G / 3G / 4G / 5G / No Permission |
| `Operator` | Operator name |
| `SignalLevel` | RSRP in dBm (e.g. -95 dBm) |
| `TotalStorage` | Total internal storage in GB (decimal) |
| `UsedStorage` | Used storage in GB (decimal) |
| `FreeStorage` | Free storage in GB (decimal) |
| `TotalRAM` | Total RAM in GB (decimal) |
| `UsedRAM` | Used RAM in GB (decimal) |
| `AvailableRAM` | Available RAM in GB (decimal) |

**Example row (Airtel 4G):**
```
2026-07-01 15:34:15,23,4G,airtel,-95 dBm,50.43,27.88,22.54,3.70,2.76,0.93
```

---

## Setup & Installation

### Requirements

- Android Studio (latest stable)
- Android phone with API 24+ (Android 7.0 or above)
- JDK 11
- Physical Android device (emulators do not return real cell data)

### Steps to Run

```bash
# 1. Clone the repository
git clone <repository-url>

# 2. Open in Android Studio
# File → Open → select the NetworkLogger folder

# 3. Let Gradle sync complete

# 4. Connect Android phone via USB
# Enable Developer Options → USB Debugging on the phone

# 5. Click Run ▶ in Android Studio
```

### First Launch Checklist

When the app opens for the first time:

1. Tap **Allow** on the Location permission dialog
2. Tap **Allow** on the Phone permission dialog
3. Tap **Allow** on the battery optimization exemption dialog
4. Go to **Settings → Apps → NetworkLogger → Battery → No Restrictions**
5. Search **Autostart** in Settings and enable it for NetworkLogger (Realme / Xiaomi / OPPO phones)

### Generate Release APK

```
Build → Generate Signed Bundle/APK → APK → Choose keystore → Release → Build
```

### File Locations on Device

```
/storage/emulated/0/Download/network_logs.csv
/storage/emulated/0/Download/background_logs.csv
```

Pull files to your computer via ADB:

```bash
adb pull /storage/emulated/0/Download/network_logs.csv
adb pull /storage/emulated/0/Download/background_logs.csv
```

---

## Permissions Explained

| Permission | Why it is needed |
|------------|-----------------|
| `ACCESS_FINE_LOCATION` | Required by Android to call `allCellInfo` and get GPS coordinates |
| `ACCESS_COARSE_LOCATION` | Fallback location permission |
| `READ_PHONE_STATE` | Required to read network type, operator name, and cell tower parameters |
| `FOREGROUND_SERVICE` | Required to run WorkManager as a foreground service |
| `FOREGROUND_SERVICE_DATA_SYNC` | Foreground service type declaration — mandatory on Android 14+ |
| `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` | Requests exemption so background worker is not killed by the OS |

> **Why does the app say "make and manage phone calls"?**  
> `READ_PHONE_STATE` is grouped under Android's "Phone" permission category. Android shows this generic label for the entire group. The app **cannot** make calls, access call history, or interact with phone calls in any way. It only uses this permission to read cell tower signal data.

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

Root access is **not required** for the app to function. All features work identically on non-rooted devices.

---

## Known Behaviours

### Cell Info: Not Available (brief flicker)
`telephonyManager.allCellInfo` returns an empty list during the modem's internal refresh cycle. The app shows "Cell Info: Not Available" for one 5-second cycle then automatically recovers. Data is not lost — the previous valid values are still saved in that CSV row.

### SINR shows N/A on 4G phones
SINR is a 5G NR-only parameter. Android does not expose it for LTE connections by design. This is expected and correct.

### Background worker timing is irregular for first 2 cycles
WorkManager enforces a 15-minute minimum but the first couple of cycles may run slightly early due to the `OneTimeWorkRequest` overlapping with the `PeriodicWorkRequest`. This normalizes after the first two runs.

### Background logging stops at low battery
On Realme, OPPO, OnePlus, and Xiaomi phones, the OS aggressively kills background processes when battery drops to approximately 20%. This is a phone OS restriction. Enable **No Restrictions** in battery settings and enable **Autostart** for NetworkLogger to minimize this.

### Rooted OnePlus / Android 14
Android 14 enforces strict `foregroundServiceType` declaration. The app handles this by declaring `foregroundServiceType="dataSync"` in the manifest and passing `FOREGROUND_SERVICE_TYPE_DATA_SYNC` to `ForegroundInfo` on API 34+.

---

## Problems Solved During Development

| Problem | Root Cause | Fix Applied |
|---------|-----------|-------------|
| CSV files invisible in Files app | `getExternalFilesDir()` saves to hidden sandboxed folder on Android 10+ | Migrated to `MediaStore.Downloads` API |
| New CSV file created on every 5-second cycle | `IS_PENDING = 1` hid the file from subsequent MediaStore queries | Removed `IS_PENDING`; added `IS_PENDING = 0` filter to all queries |
| RSRQ and SINR always N/A on 5G | Was reading `csiRsrq` / `csiSinr`; modems only report SS fields | Changed to `ssRsrq` / `ssSinr` with CSI as fallback |
| Background worker not running on release APK | OEM battery optimization kills WorkManager silently | Added foreground service notification + battery exemption |
| App crash on rooted OnePlus (Android 14) | `InvalidForegroundServiceTypeException` — mandatory on Android 14 | Declared `foregroundServiceType="dataSync"` in manifest + `ForegroundInfo` service type |
| App crash on launch (rooted phone, Android 12+) | `PhoneStateListener` blocked by root security framework | Replaced with `TelephonyCallback` for API 31+; kept `PhoneStateListener` for older |
| GPS coordinates not updating while moving | `lastLocation` returns cached position | Switched to `getCurrentLocation()` for fresh fix each cycle |
| Signal label stuck on "Weak" at -113 dBm | Used Android's generic 0-4 level instead of actual RSRP | Built `getRsrpSignalLabel()` using standard RSRP thresholds |
| Background worker `SignalLevel` always N/A | `allCellInfo` returns empty if modem hasn't refreshed | Added `requestCellInfoUpdate()` + 300ms wait before reading |
| `background_logs.csv` not created until 15 min after launch | `PeriodicWorkRequest` waits before first run | Added `OneTimeWorkRequestBuilder` to fire worker immediately on launch |

---

## Testing

Tested on the following devices:

| Device | Android | Network | Root | Result |
|--------|---------|---------|------|--------|
| Realme RMX3241 | Android 13 (API 33) | JIO 5G | Non-Rooted | Full 5G data — NCI, RSRQ, SINR, handover captured ✓ |
| Sakshi's phone | Android 13 | Airtel 4G | Non-Rooted | LTE data — MCC/MNC/CID/RSRP/RSRQ captured ✓ |
| OnePlus CPH2487 | Android 14 (API 34) | — | Rooted | App stable after Android 14 foreground service fix ✓ |
| Ma'am's phone | Android — | Airtel 4G | Non-Rooted | Data collected; stopped at ~20% battery (OS restriction) |

**Real data observed (JIO 5G, Delhi):**
- Cell handover captured: PCI 529 → 574 → 385
- RSRP range: -93 to -113 dBm
- RSRQ: -3 to -12 dB
- SINR: 0 to 15 dB
- Neighbor cells: 4 to 6 simultaneously visible
- GPS accuracy: 28–40 metres

---

## Future Scope

- **Coverage heatmap** — overlay GPS + RSRP on a map to visualize signal across a route
- **Cloud synchronization** — auto-upload CSV to Google Drive or Firebase
- **Network quality score** — estimate MOS from RSRP / RSRQ / SINR
- **Multi-device aggregation** — collect and compare data from multiple phones simultaneously
- **Excel / chart export** — auto-generate graphs from logged data
- **Signal drop alerts** — notify when RSRP falls below a configurable threshold
- **Operator benchmarking** — compare JIO vs Airtel vs Vi on the same route

