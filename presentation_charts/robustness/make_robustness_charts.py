"""
Robustness charts for the Firestore app version: when and how logging stops.

Reads the CSVs written by export_firestore.py and writes PNGs to robustness/charts/:

  01_session_timeline.png   when each phone was actually producing samples
  02_session_outcomes.png   how sessions ended (Stop / watchdog / cut off)
  03_sampling_quality.png   share of session time with normal 5 s sampling, slowed, or gaps
  04_gaps_screen.png        gaps > 1 min vs screen state
  05_gaps_by_hour.png       time lost to gaps by hour of day (Samsung)
  06_upload_delay.png       time from measurement to arrival in Firestore
  07_moto_restarts.png      the Motorola's restart loop, zoomed in

    ./venv/bin/python robustness/make_robustness_charts.py

Phones on older app versions (CSV uploads to Storage) have no session status and
are not included.
"""

import os

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "charts")
TZ = "Asia/Kolkata"

# Reference palette, as in code/make_research_charts.py. Phones take the first three
# categorical slots (validated as an all-pairs set); outcomes use the status colours,
# always with a text label; interval classes use an ordinal blue ramp.
PHONE_COLORS = {"SM-M325F": "#2a78d6", "moto g35 5G": "#eb6834", "A001": "#1baf7a"}
PHONE_NAMES = {"SM-M325F": "Samsung M32", "moto g35 5G": "Motorola g35 5G", "A001": "Nothing A001"}
GOOD, WARNING, SERIOUS, CRITICAL = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"
RAMP = ["#104281", "#2a78d6", "#86b6ef"]          # normal → slowed → gap (dark = good)
CONTEXT = "#c3c2b7"
INK_PRIMARY, INK_SECONDARY, INK_MUTED = "#0b0b0b", "#52514e", "#8a8980"
SURFACE, GRID = "#fcfcfb", "#e6e5e0"

SAMPLE_S = 5
GAP_S = 60            # an interval longer than this is a gap (the app should sample every 5 s)
NORMAL_S = 6          # ≤ this counts as on time (timer jitter)


def apply_style():
    plt.rcParams.update({
        "font.family": "sans-serif", "font.size": 11, "text.color": INK_PRIMARY,
        "axes.edgecolor": GRID, "axes.labelcolor": INK_SECONDARY, "axes.titlesize": 13,
        "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
        "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
        "xtick.color": INK_SECONDARY, "ytick.color": INK_SECONDARY,
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "legend.frameon": False,
    })


def finish(fig, name, title, subtitle, note=None):
    height_in = fig.get_size_inches()[1]
    top = 1 - 0.95 / height_in
    bottom = (0.45 / height_in) if note else 0
    fig.tight_layout(rect=[0, bottom, 1, top])
    fig.text(0.01, 1 - 0.18 / height_in, title, ha="left", va="top", fontsize=16, fontweight="bold")
    fig.text(0.01, 1 - 0.55 / height_in, subtitle, ha="left", va="top", fontsize=11, color=INK_SECONDARY)
    if note:
        fig.text(0.01, 0.1 / height_in, note, ha="left", va="bottom", fontsize=9, color=INK_MUTED)
    fig.savefig(os.path.join(OUT, name), dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {name}")


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def local(ms):
    return pd.to_datetime(ms, unit="ms", utc=True).dt.tz_convert(TZ).dt.tz_localize(None)


# ── Data ─────────────────────────────────────────────────────────────────────

def load():
    s = pd.read_csv(os.path.join(DATA, "sessions.csv"))
    x = pd.read_csv(os.path.join(DATA, "samples.csv"))
    b = pd.read_csv(os.path.join(DATA, "batches.csv"))
    g = pd.read_csv(os.path.join(DATA, "background.csv"))
    s = s[s.deviceModel.isin(PHONE_COLORS)].copy()
    x = x.merge(s[["sessionId", "deviceModel"]], on="sessionId").sort_values(["sessionId", "ts"])
    x["dt"] = x.groupby("sessionId").ts.diff() / 1000
    x["prev_screen"] = x.groupby("sessionId").screenOn.shift()
    x["prev_ts"] = x.groupby("sessionId").ts.shift()
    b = b.merge(s[["sessionId", "deviceModel"]], on="sessionId")
    b["delay_s"] = (b.uploadedAtMs - b.lastTs) / 1000
    g = g.merge(s[["sessionId", "deviceModel", "startedAtMs"]], on="sessionId")

    counts = x.groupby("sessionId").size()
    s["samples"] = s.sessionId.map(counts).fillna(0).astype(int)
    s["outcome"] = np.select(
        [s.status == "ended", s.status == "died", s.samples > 0],
        ["Stopped by the user", "Stopped unexpectedly\n(caught by watchdog)", "Cut off, never closed\n(had data)"],
        "Cut off before the first upload\n(no data)")
    return s, x, b, g


def runs(x):
    """Continuous stretches of sampling (no interval longer than GAP_S) per session."""
    x = x.copy()
    x["new"] = x.dt.isna() | (x.dt > GAP_S)
    x["run"] = x.new.cumsum()
    return x.groupby(["deviceModel", "run"]).agg(start=("ts", "min"), end=("ts", "max")).reset_index()


# ── Charts ───────────────────────────────────────────────────────────────────

def chart_timeline(s, x):
    r = runs(x)
    phones = ["A001", "moto g35 5G", "SM-M325F"]
    fig, ax = plt.subplots(figsize=(12, 4.4))
    for i, p in enumerate(phones):
        rp = r[r.deviceModel == p]
        start, end = local(rp.start), local(rp.end)
        width = (end - start).clip(lower=pd.Timedelta(minutes=8))   # keep 1-minute runs visible
        ax.barh(i, width, left=start, height=0.5, color=PHONE_COLORS[p], linewidth=0)
        sp = s[s.deviceModel == p]
        for outcome, marker, color in [("Stopped by the user", "|", GOOD),
                                       ("Stopped unexpectedly\n(caught by watchdog)", "x", CRITICAL)]:
            e = sp[sp.outcome == outcome]
            ax.scatter(local(e.endedAtMs), [i + 0.42] * len(e), marker=marker, s=70, color=color,
                       linewidths=2, zorder=3)
    ax.set_yticks(range(len(phones)), [f"{PHONE_NAMES[p]}\n{plural((s.deviceModel == p).sum(), 'session')}" for p in phones])
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.set_ylim(-0.6, len(phones) - 0.2)
    ax.grid(axis="y", visible=False)
    ax.scatter([], [], marker="|", s=70, color=GOOD, linewidths=2, label="Stopped by the user")
    ax.scatter([], [], marker="x", s=70, color=CRITICAL, linewidths=2, label="Stopped unexpectedly (watchdog)")
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.12), ncol=2, fontsize=10)
    finish(fig, "01_session_timeline.png", "When were the phones actually logging?",
           "Bars = stretches with no gap longer than 1 minute. The Samsung ran for days; the Motorola "
           "kept restarting in short bursts.",
           note="Firestore app version, 13–26 Oct 2026, IST. Runs shorter than 8 minutes are drawn 8 minutes wide.")


def chart_outcomes(s):
    order = ["Stopped by the user", "Stopped unexpectedly\n(caught by watchdog)",
             "Cut off, never closed\n(had data)", "Cut off before the first upload\n(no data)"]
    colors = [GOOD, CRITICAL, SERIOUS, WARNING]
    phones = ["A001", "SM-M325F", "moto g35 5G"]
    tab = pd.crosstab(s.deviceModel, s.outcome).reindex(index=phones, columns=order, fill_value=0)
    share = tab.div(tab.sum(axis=1), axis=0) * 100
    fig, ax = plt.subplots(figsize=(12, 4.6))
    left = np.zeros(len(phones))
    for col, c in zip(order, colors):
        ax.barh(range(len(phones)), share[col], left=left, color=c, height=0.55, edgecolor=SURFACE,
                linewidth=2, label=col.replace("\n", " "))
        for i, (v, n) in enumerate(zip(share[col], tab[col])):
            if v >= 7:
                ax.text(left[i] + v / 2, i, f"{n}", ha="center", va="center", fontsize=11, fontweight="bold",
                        color=INK_PRIMARY if c == WARNING else "white")
        left += share[col].values
    ax.set_yticks(range(len(phones)), [f"{PHONE_NAMES[p]}  ({tab.loc[p].sum()})" for p in phones])
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.grid(axis="y", visible=False)
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.1), ncol=2, fontsize=10)
    moto = tab.loc["moto g35 5G"]
    finish(fig, "02_session_outcomes.png", "How did each session end?",
           f"Only {int(tab[order[0]].sum())} of {int(tab.values.sum())} sessions were ended with Stop. "
           f"{moto[order[3]]} Motorola sessions were killed before their first 60-second upload.",
           note="Numbers in bars = sessions. 'Cut off' = the app process ended without Stop and no watchdog "
                "check ran afterwards; samples still in memory (< 60 s) are lost.")


def chart_quality(x):
    v = x.dropna(subset=["dt"])
    v = v.assign(cls=pd.cut(v.dt, [0, NORMAL_S, GAP_S, np.inf],
                            labels=["Normal (every ~5 s)", "Slowed (6–60 s)", "Gap (> 1 min)"]))
    phones = ["A001", "moto g35 5G", "SM-M325F"]
    time_h = v.groupby(["deviceModel", "cls"], observed=False).dt.sum().unstack().reindex(phones) / 3600
    share = time_h.div(time_h.sum(axis=1), axis=0) * 100
    fig, ax = plt.subplots(figsize=(12, 4.2))
    left = np.zeros(len(phones))
    for col, c in zip(share.columns, RAMP):
        ax.barh(range(len(phones)), share[col], left=left, color=c, height=0.55, edgecolor=SURFACE,
                linewidth=2, label=col)
        for i, val in enumerate(share[col]):
            if val >= 6:
                ax.text(left[i] + val / 2, i, f"{val:.0f}%", ha="center", va="center", fontsize=11,
                        fontweight="bold", color=INK_PRIMARY if c == RAMP[2] else "white")
        left += share[col].values
    ax.set_yticks(range(len(phones)),
                  [f"{PHONE_NAMES[p]}  ({time_h.loc[p].sum():.0f} h)" for p in phones])
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda val, _: f"{val:.0f}%"))
    ax.grid(axis="y", visible=False)
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.1), ncol=3, fontsize=10)
    sam = share.loc["SM-M325F"]
    finish(fig, "03_sampling_quality.png", "How much of the logging time had normal 5-second sampling?",
           f"Share of time inside sessions, by the interval to the next sample. On the Samsung only "
           f"{sam.iloc[0]:.0f}% of the time was sampled every 5 s.",
           note="Hours in brackets = total time between samples inside sessions. An interval is "
                "attributed to its whole length, so one 5-minute gap counts as 5 minutes.")


def chart_screen(x):
    v = x.dropna(subset=["dt", "prev_screen"])
    phones = ["A001", "moto g35 5G", "SM-M325F"]
    rate = (v.assign(gap=v.dt > GAP_S).groupby(["deviceModel", "prev_screen"]).gap.mean().unstack()
            .reindex(phones) * 100)
    n = v.assign(gap=v.dt > GAP_S).groupby(["deviceModel", "prev_screen"]).gap.sum().unstack().reindex(phones)
    fig, ax = plt.subplots(figsize=(11, 4.8))
    y = np.arange(len(phones))
    for off, (state, color) in enumerate([("ON", CONTEXT), ("OFF", INK_PRIMARY)]):
        vals = rate[state].fillna(0)
        ax.barh(y + (off - 0.5) * 0.36, vals, height=0.32, color=color, label=f"Screen {state.lower()}")
        for yi, val, k in zip(y, vals, n[state].fillna(0)):
            ax.text(val + 0.15, yi + (off - 0.5) * 0.36, f"{val:.1f}%  ({plural(int(k), 'gap')})", va="center",
                    fontsize=10, color=INK_SECONDARY)
    ax.set_yticks(y, [PHONE_NAMES[p] for p in phones])
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda val, _: f"{val:.0f}%"))
    ax.set_xlim(0, rate.max().max() * 1.35)
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right")
    total, off = int(n.sum().sum()), int(n["OFF"].sum())
    finish(fig, "04_gaps_screen.png", "Gaps happen when the screen is off",
           f"Share of sampling intervals longer than 1 minute. {off} of {total} gaps started with the "
           f"screen off.",
           note="Screen state is the one recorded with the sample before the gap. With the screen off "
                "Android's Doze mode can pause the app's 5-second timer; the app holds no wake lock.")


def chart_by_hour(x):
    v = x[(x.deviceModel == "SM-M325F")].dropna(subset=["dt"]).copy()
    v["hour"] = local(v.prev_ts).dt.hour
    v["gap_s"] = np.where(v.dt > GAP_S, v.dt, 0)
    by = v.groupby("hour").agg(gap=("gap_s", "sum"), total=("dt", "sum"))
    share = (by.gap / by.total * 100).reindex(range(24), fill_value=0)
    fig, ax = plt.subplots(figsize=(12, 4.8))
    night = [h for h in range(24) if h < 8]
    ax.bar(share.index, share.values, color=[PHONE_COLORS["SM-M325F"] if h in night else CONTEXT
                                             for h in share.index], width=0.75)
    ax.set_xticks(range(0, 24, 2), [f"{h:02d}:00" for h in range(0, 24, 2)])
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda val, _: f"{val:.0f}%"))
    ax.grid(axis="x", visible=False)
    ax.set_ylabel("Time lost to gaps > 1 min")
    nshare = by.loc[night].gap.sum() / by.loc[night].total.sum() * 100
    dshare = by.drop(night, errors="ignore").gap.sum() / by.drop(night, errors="ignore").total.sum() * 100
    ax.text(3.5, share.max() * 1.02, f"00:00–08:00: {nshare:.0f}% of the time lost", ha="center",
            fontsize=11, fontweight="bold", color=INK_PRIMARY)
    ax.text(15.5, share.max() * 0.55, f"08:00–24:00: {dshare:.0f}%", ha="center", fontsize=11,
            color=INK_SECONDARY)
    ax.set_ylim(0, share.max() * 1.15)
    finish(fig, "05_gaps_by_hour.png", "Overnight, the Samsung lost much more logging time",
           "Samsung M32, share of session time inside gaps longer than 1 minute, by hour of day (IST).",
           note="The phone lies idle overnight, which is when Android's Doze mode is deepest.")


def chart_upload(b):
    phones = ["SM-M325F", "moto g35 5G", "A001"]
    fig, ax = plt.subplots(figsize=(11, 5))
    for p in phones:
        d = np.sort(b[b.deviceModel == p].delay_s.clip(lower=0.5).values)
        if not len(d):
            continue
        ax.step(d, np.arange(1, len(d) + 1) / len(d) * 100, where="post", color=PHONE_COLORS[p], linewidth=2,
                label=f"{PHONE_NAMES[p]} ({len(d):,} batches, median {np.median(d):.0f} s)")
    ax.set_xscale("log")
    ax.set_xticks([1, 5, 10, 60, 300, 600, 1800, 3600], ["1 s", "5 s", "10 s", "1 min", "5 min", "10 min",
                                                        "30 min", "1 h"])
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda val, _: f"{val:.0f}%"))
    ax.set_ylim(0, 101)
    ax.set_xlabel("Time from the batch's last sample to its arrival in Firestore")
    ax.set_ylabel("Batches arrived")
    ax.legend(loc="lower right", fontsize=10)
    all_d = b.delay_s
    finish(fig, "06_upload_delay.png", "Batches reach the cloud within seconds, or wait and arrive later",
           f"{(all_d <= 10).mean() * 100:.0f}% arrived within 10 s. The slowest waited "
           f"{all_d.max() / 60:.0f} min (phone offline or asleep) and still arrived.",
           note="Each batch holds ~60 s of samples and is sent at the end of that minute. No batch was lost: "
                "every batch number in every session is present.")


def chart_moto(s, x, g):
    m = s[s.deviceModel == "moto g35 5G"].copy()
    starts = local(m.startedAtMs)
    # busiest 4-hour window by session starts
    t = starts.sort_values().reset_index(drop=True)
    counts = [(t >= t[i]) & (t < t[i] + pd.Timedelta(hours=4)) for i in range(len(t))]
    i0 = int(np.argmax([c.sum() for c in counts]))
    w0, w1 = t[i0] - pd.Timedelta(minutes=10), t[i0] + pd.Timedelta(hours=4)
    first_bg = g[g.deviceModel == "moto g35 5G"].sort_values("ts").groupby("sessionId").first()
    screen = m.sessionId.map(first_bg.screenOn)

    fig, ax = plt.subplots(figsize=(12, 3.8))
    r = runs(x[x.deviceModel == "moto g35 5G"])
    rs, re = local(r.start), local(r.end)
    sel = (re >= w0) & (rs <= w1)
    ax.barh(0, (re - rs)[sel].clip(lower=pd.Timedelta(seconds=40)), left=rs[sel], height=0.35,
            color=PHONE_COLORS["moto g35 5G"], label="Samples received")
    for state, color, label in [("OFF", INK_PRIMARY, "New session, screen off (most likely restarted by Android)"),
                                ("ON", CONTEXT, "New session, screen on")]:
        tt = starts[(screen == state) & (starts >= w0) & (starts <= w1)]
        ax.vlines(tt, 0.3, 0.75, color=color, linewidth=1.6, label=label)
    ax.set_xlim(w0, w1)
    ax.set_ylim(-0.4, 0.95)
    ax.set_yticks([])
    ax.grid(axis="y", visible=False)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.15), ncol=3, fontsize=10)
    n_win = int(((starts >= w0) & (starts <= w1)).sum())
    off_share = (screen == "OFF").sum() / screen.notna().sum() * 100
    finish(fig, "07_moto_restarts.png",
           f"The Motorola restarted logging {n_win} times in 4 hours ({w0:%d %b})",
           f"Each tick is a new session. {off_share:.0f}% of the Motorola's {len(m)} sessions began with the "
           f"screen off, so most were restarted by Android rather than by a person.",
           note="Android restarts a killed foreground service automatically; the app then starts a fresh "
                "session and the unsent samples of the old one (up to 60 s) are lost.")


# Why each Samsung session ended. Sessions closed with Stop say so in Firestore; the
# three watchdog-ended ones were explained from the phone's own process-exit history
# (`adb shell dumpsys activity exit-info com.example.networklogger`, read 26 Oct 2026).
SAMSUNG_CAUSES = {
    "c99c4ca17246df8a_20261016_095721":
        ("Killed when Google Play services updated itself (\"stop com.google.android.gms due to "
         "installPackageLI\", 14:15:33). Charging. Restarted by hand 30 min later."),
    "c99c4ca17246df8a_20261016_214439":
        ("Killed when Google Play services updated itself again (same exit record, 13:28:17). "
         "Charging. Not restarted for 32 h."),
    "c99c4ca17246df8a_20261023_214206":
        ("Logging stopped mid-use (screen on, 0.5–3 Mbit/s traffic) while the app process stayed alive: "
         "no exit record at 21:59. Cause unknown; the new app version records this case."),
}


def chart_samsung(s, x):
    phone = "SM-M325F"
    ss = s[s.deviceModel == phone].sort_values("startedAtMs").reset_index(drop=True)
    r = runs(x[x.deviceModel == phone])
    last = x[x.deviceModel == phone].groupby("sessionId").ts.max()

    fig = plt.figure(figsize=(12, 7.6))
    gs = fig.add_gridspec(2, 1, height_ratios=[1.15, 1.6], hspace=0.22)
    ax = fig.add_subplot(gs[0])
    start, end = local(r.start), local(r.end)
    ax.barh(0, (end - start).clip(lower=pd.Timedelta(minutes=8)), left=start, height=0.45,
            color=PHONE_COLORS[phone], linewidth=0)
    lines, prev_end, level = [], None, 0
    for i, row in ss.iterrows():
        n = i + 1
        t_end = local(pd.Series([last.get(row.sessionId, row.endedAtMs)])).iloc[0]
        stopped = row.status == "ended"
        color = GOOD if stopped else CRITICAL
        # Stagger markers that would overlap (ends less than a day apart)
        level = 1 - level if prev_end is not None and (t_end - prev_end) < pd.Timedelta(hours=24) else 0
        prev_end = t_end
        my = 0.58 + 0.3 * level
        ax.vlines(t_end, 0.25, my, color=color, linewidth=1)
        ax.scatter([t_end], [my], s=330, color=color, zorder=3, edgecolors=SURFACE, linewidths=1.5)
        ax.text(t_end, my, str(n), ha="center", va="center", fontsize=9.5, fontweight="bold",
                color="white", zorder=4)
        t0 = local(pd.Series([row.startedAtMs])).iloc[0]
        dur_h = (t_end - t0).total_seconds() / 3600
        dur = f"{dur_h / 24:.1f} days" if dur_h >= 48 else f"{dur_h:.1f} h" if dur_h >= 1 else f"{dur_h * 60:.0f} min"
        cause = "Stopped with the Stop button." if stopped else SAMSUNG_CAUSES.get(row.sessionId, "Cause unknown.")
        lines.append((n, color, f"{t0:%d %b %H:%M} → {t_end:%d %b %H:%M}  ({dur})", cause))
    ax.set_ylim(-0.45, 1.1)
    first = local(pd.Series([ss.startedAtMs.min()])).iloc[0]
    ax.set_xlim(first - pd.Timedelta(hours=14), local(pd.Series([last.max()])).iloc[0] + pd.Timedelta(hours=14))
    ax.set_yticks([])
    ax.grid(axis="y", visible=False)
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.spines["left"].set_visible(False)

    tx = fig.add_subplot(gs[1])
    tx.axis("off")
    y, step = 0.97, 1 / (len(lines) + 0.4)
    for n, color, when, cause in lines:
        tx.scatter([0.012], [y - 0.035], s=260, color=color, transform=tx.transAxes, clip_on=False)
        tx.text(0.012, y - 0.035, str(n), transform=tx.transAxes, ha="center", va="center", fontsize=9,
                fontweight="bold", color="white")
        tx.text(0.035, y, when, transform=tx.transAxes, va="top", fontsize=10.5, fontweight="bold")
        tx.text(0.035, y - 0.065, cause, transform=tx.transAxes, va="top", fontsize=10, color=INK_SECONDARY)
        y -= step
    died = int((ss.status == "died").sum())
    finish(fig, "08_samsung_shutdowns.png", "Why did logging stop on the Samsung M32?",
           f"{len(ss)} sessions, 13–26 Oct. {len(ss) - died} were stopped with Stop; "
           f"{died} stopped on their own: two Google Play services updates and one unexplained.",
           note="Bars = logging with no gap over 1 minute. Green = stopped by the user, red = stopped on its own. "
                "Causes from the phone's process-exit history (adb dumpsys activity exit-info).")


def main():
    os.makedirs(OUT, exist_ok=True)
    apply_style()
    s, x, b, g = load()
    chart_samsung(s, x)
    chart_timeline(s, x)
    chart_outcomes(s)
    chart_quality(x)
    chart_screen(x)
    chart_by_hour(x)
    chart_upload(b)
    chart_moto(s, x, g)


if __name__ == "__main__":
    main()
