# Project status

_Last updated: 5 Nov 2026. Update this file at the end of a work session._

## Done

- **App → Firestore streaming** (production mode): 1 batch/min, offline queue, typed rows with
  epoch-ms `ts`; throughput excludes the app's own traffic; single Start/Stop button.
- **Robustness fixes (APK `apk/NetworkLogger-public-robustness-2026-10-26.apk`)**: partial wake lock;
  killed sessions resume as the same session (Android restart or watchdog — needs battery-opt
  exemption + "Allow all the time" location); session `events` record why logging stopped.
  Built and unit-tested, **not yet verified on a phone**.
- **Live dashboards**: listener + NetworkLogger Live/Map dashboards on the Mac and on the lab server
  (shared view-only on the IITD network).
- **Robustness analysis** (`presentation_charts/robustness/`, 13–26 Oct data, 8 charts).
- **Region grid on the Live dashboard**: Jio/Vi/Airtel maps side by side; squares = median RSRP per
  cell from all data, precomputed by `grafana_pipeline/grid_builder.py` every 30 min into the
  `grid_cache` bucket. Running on the Mac; `server/nl.sh` has a `grid` service, not yet deployed.
- Docs updated; pushed to GitHub `daksh-iitd/NetworkLogger`, branch `band-logging-dev-mode`
  (3 commits on 26 Oct).

## Key findings (13–26 Oct, Firestore app version)

- Uploads robust: 90% of batches in Firestore within 10 s, max 43 min, none lost.
- Gaps > 1 min almost only with the screen off (1,593 of 1,596), mostly 00:00–08:00 → Doze, no
  wake lock. Samsung: only 46% of session time at normal 5 s sampling.
- Samsung M32 deaths: 2 × Google Play services self-update (16 Oct 14:15, 22 Oct 13:28, from
  `adb exit-info`); 1 unexplained (25 Oct 21:59, service stopped while process alive, screen on).
- Motorola g35: 464 sessions, 373 with no data — Android killing/restarting the service.

## Phones seen so far (20, as of 27 Oct)

Samsung Galaxy M32 (A12), A34 5G, S22 Ultra, S24, S24 FE; moto g35 5G, Motorola edge 50 neo, moto e13;
OnePlus 11R ×2 (A14, rooted, Jio/Vi experiment), OnePlus 8 Pro, CPH2423; Nothing A001; Xiaomi 2201116SI,
2201117PI, 23122PCD1I, 25057PC09I; Infinix X6525; Realme RMX3842; vivo V2518.
Operators: Jio (405-8xx), Vi (404-11), **Airtel (404-10, some 404-93)** — Airtel phones joined 26–27 Oct.
Per-device IITD comparison: `presentation_charts/device_comparison/`.

## Open items

- [ ] Wi-Fi: count only mobile traffic (`TrafficStats.getMobile*`) and add a `transport` field
      (wifi/cellular/none); update the listener so it reaches Grafana.
- [ ] Record `Build.DISPLAY` / security patch per session (OEM build, e.g. One UI / HyperOS).
- [ ] Test the robustness APK on Samsung + Motorola for a week, then re-run the robustness charts
      (and add the session `events` to them).
- [ ] Airtel rows are stored twice in `network_logs_v2` (old `airtel`/`IND airtel` tags plus `Airtel`
      after the rename and a listener reload). `grid_builder.py` counts them once; the raw rows remain.
- [ ] Listener restart reads every Firestore document (53k on 5 Nov, over the 50k/day free quota) and
      sends the history as one InfluxDB write, which timed out at 30 s on 2 Nov. Needs chunked writes,
      and a way to resume instead of re-reading everything.
- [ ] Open a PR from `band-logging-dev-mode` to `main`.
- [ ] Server uses the Firebase admin key — swap for a read-only (Cloud Datastore Viewer) key.
- [ ] Delete Mac backups once happy: `/opt/homebrew/var/lib/influxdb2.backup-2026-10-20`,
      `/opt/homebrew/etc/influxdb2/config.yml.bak-2026-10-20`.
- [ ] Experiment scripts that tap Start/Stop by coordinates need updating for the single button.
- [ ] Optional: faster recovery than the 10–25 min watchdog; keep unsent samples on disk.
