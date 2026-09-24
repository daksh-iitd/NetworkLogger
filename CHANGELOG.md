# Changelog

All notable changes to NetworkLogger are documented here, organized by version.

---

## [Current] — July 2026

### Added
- 7-layer root detection system (su binaries, root packages, build tags, dangerous props, RW paths, cloaking apps, su execution)
- Red/green/amber badge UI for root status, signal strength, and network display
- Dark-themed professional UI using Material3 and CardView layout
- Device card showing which root detection method triggered
- Battery optimization exemption request on first launch
- `badge_red.xml` drawable for rooted device status

### Fixed
- App crash on OnePlus CPH2487 running Android 14
    - Cause: `InvalidForegroundServiceTypeException` — Android 14 made `foregroundServiceType` mandatory
    - Fix: Declared `foregroundServiceType="dataSync"` in manifest; passed `FOREGROUND_SERVICE_TYPE_DATA_SYNC` to `ForegroundInfo`; changed `catch (e: Exception)` to `catch (t: Throwable)`
- App crash on rooted Android 12+ devices
    - Cause: `PhoneStateListener` blocked by root security framework
    - Fix: Replaced with `TelephonyCallback` for API 31+; kept `PhoneStateListener` as fallback for older versions

---

## [v0.4] — June 2026 (late)

### Added
- Null-check on `openOutputStream` with automatic recovery — detects broken MediaStore entries, deletes them, and recreates the file

### Fixed
- Duplicate CSV file created on every 5-second logging cycle
    - Cause: `IS_PENDING = 1` hid newly created files from subsequent MediaStore queries
    - Fix: Removed `IS_PENDING` from file creation entirely; added `IS_PENDING = 0` filter to all queries

---

## [v0.3] — June 2026 (mid)

### Added
- `OneTimeWorkRequestBuilder` fires `NetworkWorker` immediately on every app launch
- `requestCellInfoUpdate()` in Worker before reading `allCellInfo` + 300ms wait for modem to respond
- `getRsrpSignalLabel()` — signal labels now based on actual RSRP thresholds (-80/-90/-100/-110 dBm)
- `TelephonyCallback` for Android 12+ alongside deprecated `PhoneStateListener` for older devices
- Root detection expanded: Magisk package check, `Build.TAGS` test-keys check, 4 additional su binary paths
- `getCellTowerInfo()` fully wrapped in try-catch for stability on rooted devices
- `updateMeasurements()` wraps `telephonyManager.networkType` in try-catch

### Fixed
- RSRQ and SINR always showing N/A on 5G devices
    - Cause: Was reading `csiRsrq` / `csiSinr` fields which most modems do not populate
    - Fix: Changed to `ssRsrq` / `ssSinr` (Synchronization Signal fields) with CSI as fallback
- Signal label stuck on "Weak" regardless of actual signal strength
    - Cause: Used Android's generic 0-4 level instead of actual RSRP dBm values
    - Fix: Built `getRsrpSignalLabel()` using standard 3GPP RSRP thresholds
- Background worker `SignalLevel` column always N/A
    - Cause: `allCellInfo` returns empty list if modem not refreshed when worker fires
    - Fix: Added `requestCellInfoUpdate()` call before reading + sleep to allow modem response
- GPS coordinates not updating while moving
    - Cause: `lastLocation` returns cached position, not a fresh GPS fix
    - Fix: Replaced with `getCurrentLocation()` for a fresh fix on every 5-second cycle
- `background_logs.csv` not created until 15 minutes after app launch
    - Cause: `PeriodicWorkRequest` waits before its first run
    - Fix: Added `OneTimeWorkRequestBuilder` to fire worker once immediately on launch

---

## [v0.2] — June 2026 (early)

### Added
- `NetworkWorker` converted from `Worker` to `CoroutineWorker`
- `setForeground(ForegroundInfo)` with notification to keep worker alive on OEM phones
- `FOREGROUND_SERVICE` and `FOREGROUND_SERVICE_DATA_SYNC` permissions in manifest
- `SystemForegroundService` declaration in manifest with `foregroundServiceType="dataSync"`
- Battery optimization exemption request on first launch
- `READ_PHONE_STATE` permission check before `telephonyManager.dataNetworkType` in Worker
- Signal level reading in Worker from `allCellInfo`
- RAM and storage values changed from `Long` (whole GB) to `Float` (decimal GB precision)

### Fixed
- `background_logs.csv` not being created on release APK on Realme and OnePlus devices
    - Cause: OEM battery optimization kills background WorkManager tasks silently
    - Fix: Promoted worker to foreground service + requested battery exemption
- Worker crash before `saveBackgroundLog()` on devices with denied permissions
    - Fix: Added `ContextCompat.checkSelfPermission` check before reading `telephonyManager.dataNetworkType`

---

## [v0.1] — June 2026 (initial)

### Added
- GPS location tracking via `FusedLocationProviderClient`
- Network type detection — 2G / 3G / 4G / 5G
- LTE cell info: MCC, MNC, CID, TAC, EARFCN, RSRP, RSRQ, PCI
- 5G NR cell info: NCI, PCI, TAC, NRARFCN, RSRP, RSRQ, SINR
- Neighbor cell detection
- Background monitoring via WorkManager
- Battery, RAM, storage monitoring in `NetworkWorker`
- Basic root detection (su binary paths)
- CSV logging with header row for both files
- Start / Stop logging buttons with duration timer
- CSV file path display in UI

### Fixed
- CSV files invisible in phone's Files app
    - Cause: `getExternalFilesDir()` saves to sandboxed `/Android/data/` hidden from file managers on Android 10+
    - Fix: Migrated to `MediaStore.Downloads` API
- App crash with `FileNotFoundException EACCES (Permission denied)`
    - Cause: Attempted to write to `Environment.getExternalStoragePublicDirectory(DIRECTORY_DOWNLOADS)` without storage permission
    - Fix: Changed to `getExternalFilesDir(null)` (later fully replaced with MediaStore)