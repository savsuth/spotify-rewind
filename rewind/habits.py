"""Listening habits and obsessions: clock, weekdays, biggest day, streaks, repeats, sessions.

Timing rules (stated in the methodology):
- Offline records are excluded here. Their timestamp is when the device synced,
  not when the music played, so they would put plays on the wrong hour and day.
- Zero-ms records are excluded (nothing was heard).
- A stream's minutes are split across the local clock hours it actually spanned
  (start = end - ms_played). Streams never exceed 60 minutes, so at most two
  hours are involved.
- Days, weeks and streaks use the local date of the stream's end.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAYPARTS = {"night": (0, 5), "morning": (5, 12), "afternoon": (12, 17), "evening": (17, 24)}
SESSION_GAP_MINUTES = 30


def timed(music: pd.DataFrame) -> pd.DataFrame:
    """Music records with trustworthy timing: online only, something heard."""
    online = ~music["offline"].map(lambda v: v is True)
    return music[online & (music["ms_played"] > 0)].copy()


def hour_minutes(t: pd.DataFrame) -> np.ndarray:
    """Minutes per local clock hour (24), splitting streams across the hour boundary."""
    end = t["local_ts"]
    ms = t["ms_played"].to_numpy(dtype=float)
    start = end - pd.to_timedelta(ms, unit="ms")
    boundary = end.dt.floor("h")
    in_end_hour = np.minimum(ms, (end - boundary).dt.total_seconds().to_numpy() * 1000.0)
    in_prev_hour = ms - in_end_hour
    out = np.zeros(24)
    np.add.at(out, end.dt.hour.to_numpy(), in_end_hour / 60000.0)
    prev_hour = (end.dt.hour.to_numpy() - 1) % 24
    np.add.at(out, prev_hour, in_prev_hour / 60000.0)
    # Sanity: the split never loses or invents time.
    assert abs(out.sum() - ms.sum() / 60000.0) < 1e-6 * max(1.0, ms.sum())
    assert (start <= end).all()
    return out


def clock(t: pd.DataFrame, first_date: pd.Timestamp, last_date: pd.Timestamp) -> dict | None:
    if t.empty:
        return None
    hours = hour_minutes(t)
    total = hours.sum()
    share = hours / total
    peak = int(np.argmax(hours))  # earliest hour on ties
    bins = [{"label": f"{h:02d}–{h + 3:02d}", "start": h, "minutes": round(float(hours[h:h + 3].sum()), 1),
             "share": round(float(share[h:h + 3].sum()), 4)} for h in range(0, 24, 3)]
    dayparts = {k: round(float(share[a:b].sum()), 4) for k, (a, b) in DAYPARTS.items()}
    # Weekday: minutes per occurrence of that weekday inside the covered dates (fair for partial ranges).
    days = pd.date_range(first_date, last_date, freq="D")
    occurrences = np.bincount(days.dayofweek, minlength=7)
    by_wd = t.groupby(t["local_date"].dt.dayofweek)["ms_played"].sum().reindex(range(7), fill_value=0) / 60000.0
    per_occ = by_wd.to_numpy() / np.maximum(occurrences, 1)
    peak_wd = int(np.argmax(per_occ))
    return {
        "minutes": round(float(total), 1),
        "hours": [round(float(x), 1) for x in hours],
        "peak_hour": peak,
        "peak_hour_share": round(float(share[peak]), 4),
        "bins": bins,
        "peak_bin": max(range(8), key=lambda i: (bins[i]["minutes"], -i)),
        "dayparts": dayparts,
        "weekday_minutes_per_day": {WEEKDAYS[i]: round(float(per_occ[i]), 1) for i in range(7)},
        "peak_weekday": WEEKDAYS[peak_wd],
        "peak_weekday_minutes": round(float(per_occ[peak_wd]), 1),
    }


def biggest_day(t: pd.DataFrame) -> dict | None:
    if t.empty:
        return None
    by_day = t.groupby("local_date")["ms_played"].sum()
    # Most minutes; ties go to the earliest date.
    day = by_day[by_day == by_day.max()].index.min()
    sub = t[t["local_date"] == day]
    art = sub.groupby(["artist_id", "artist"])["ms_played"].sum().reset_index()
    art = art.assign(_n=art["artist"].str.casefold()).sort_values(["ms_played", "_n"], ascending=[False, True])
    top = art.iloc[0]
    return {
        "date": day.date().isoformat(),
        "minutes": round(float(by_day[day] / 60000.0), 1),
        "plays": int(sub["qualified_play"].sum()),
        "artists": int(sub["artist_id"].nunique()),
        "top_artist": {"id": top["artist_id"], "name": top["artist"],
                       "minutes": round(float(top["ms_played"] / 60000.0), 1)},
    }


def day_iso(day_no: int) -> str:
    """ISO date for a day number counted from 1970-01-01 (explicit unit; see techlog.py)."""
    return (pd.Timestamp("1970-01-01") + pd.to_timedelta(int(day_no), unit="D")).date().isoformat()


def runs(dates: np.ndarray) -> list[tuple[int, int]]:
    """Consecutive-day runs in a sorted array of day numbers, as (start, length)."""
    if len(dates) == 0:
        return []
    breaks = np.flatnonzero(np.diff(dates) != 1)
    starts = np.concatenate([[0], breaks + 1])
    ends = np.concatenate([breaks, [len(dates) - 1]])
    return [(int(dates[s]), int(e - s + 1)) for s, e in zip(starts, ends)]


def artist_streaks(t: pd.DataFrame, top: int = 3) -> list[dict]:
    """Longest runs of consecutive local days with at least one play of the same artist."""
    played = t[t["qualified_play"]]
    if played.empty:
        return []
    epoch = pd.Timestamp("1970-01-01")
    day_no = ((played["local_date"] - epoch).dt.days).to_numpy()
    frame = pd.DataFrame({"artist_id": played["artist_id"].to_numpy(), "artist": played["artist"].to_numpy(),
                          "day": day_no, "ms": played["ms_played"].to_numpy()})
    best = []
    for (aid, name), g in frame.groupby(["artist_id", "artist"], sort=False):
        days = np.unique(g["day"].to_numpy())
        for start, length in runs(days):
            if length < 2:
                continue
            in_run = g[(g["day"] >= start) & (g["day"] < start + length)]
            best.append({"id": aid, "name": name, "days": length,
                         "start": day_iso(start),
                         "end": day_iso(start + length - 1),
                         "minutes": round(float(in_run["ms"].sum() / 60000.0), 1),
                         "plays": int(len(in_run))})
    # Longest; then more minutes in the run; then earlier start; then name.
    best.sort(key=lambda r: (-r["days"], -r["minutes"], r["start"], r["name"].casefold()))
    out, seen = [], set()
    for r in best:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append(r)
        if len(out) == top:
            break
    return out


def active_streak(t: pd.DataFrame) -> dict | None:
    played = t[t["qualified_play"]]
    if played.empty:
        return None
    epoch = pd.Timestamp("1970-01-01")
    days = np.unique(((played["local_date"] - epoch).dt.days).to_numpy())
    start, length = max(runs(days), key=lambda r: (r[1], -r[0]))
    return {"days": length, "start": day_iso(start), "end": day_iso(start + length - 1)}


def repeat_week(t: pd.DataFrame) -> dict | None:
    """Most plays of one song within a single Monday-to-Sunday week."""
    played = t[t["qualified_play"]].copy()
    if played.empty:
        return None
    played["week"] = played["local_date"] - pd.to_timedelta(played["local_date"].dt.dayofweek, unit="D")
    g = played.groupby(["week", "track_id"]).agg(plays=("ms_played", "size"), ms=("ms_played", "sum"),
                                                track=("track", "first"), artist=("artist", "first"),
                                                uri=("track_uri", "first")).reset_index()
    g = g.assign(_n=g["track"].str.casefold()).sort_values(
        ["plays", "ms", "week", "_n"], ascending=[False, False, True, True])
    r = g.iloc[0]
    return {"track_id": r["track_id"], "track": r["track"], "artist": r["artist"],
            "week_start": r["week"].date().isoformat(),
            "week_end": (r["week"] + pd.to_timedelta(6, unit="D")).date().isoformat(),
            "plays": int(r["plays"]), "minutes": round(float(r["ms"] / 60000.0), 1)}


def sessions(t: pd.DataFrame) -> dict | None:
    """Sessions split where more than SESSION_GAP_MINUTES pass between one stream's end and the next start."""
    if t.empty:
        return None
    # Order and gaps in UTC (local clocks jump when the timezone changes); display in local time.
    s = t.sort_values("ts_utc")
    end = s["ts_utc"].dt.tz_convert(None).to_numpy()
    start = end - pd.to_timedelta(s["ms_played"].to_numpy(), unit="ms").to_numpy()
    local_start = (s["local_ts"] - pd.to_timedelta(s["ms_played"], unit="ms")).to_numpy()
    prev_end = np.maximum.accumulate(end)
    gap = np.empty(len(s), dtype="timedelta64[ns]")
    gap[0] = np.timedelta64(0, "ns")
    gap[1:] = start[1:] - prev_end[:-1]
    new = np.concatenate([[True], gap[1:] > np.timedelta64(SESSION_GAP_MINUTES, "m")])
    sid = np.cumsum(new)
    s = s.assign(_sid=sid, _start=local_start)
    agg = s.groupby("_sid").agg(ms=("ms_played", "sum"), first=("_start", "min"), last=("local_ts", "max"),
                                tracks=("qualified_play", "sum"))
    best_id = agg.sort_values(["ms", "first"], ascending=[False, True]).index[0]
    b = agg.loc[best_id]
    sub = s[s["_sid"] == best_id]
    art = sub.groupby("artist")["ms_played"].sum().sort_values(ascending=False)
    # Longest run of back-to-back plays by one artist, anywhere.
    q = s[s["qualified_play"]]
    same = (q["artist_id"].to_numpy()[1:] == q["artist_id"].to_numpy()[:-1]) & (q["_sid"].to_numpy()[1:] == q["_sid"].to_numpy()[:-1])
    run_len, best_run, best_at = 1, 1, 0
    for i, flag in enumerate(same, start=1):
        run_len = run_len + 1 if flag else 1
        if run_len > best_run:
            best_run, best_at = run_len, i
    run_artist = q["artist"].iloc[best_at] if len(q) else None
    run_date = q["local_date"].iloc[best_at].date().isoformat() if len(q) else None
    return {
        "sessions": int(agg.shape[0]),
        "median_minutes": round(float(np.median(agg["ms"]) / 60000.0), 1),
        "longest": {"date": pd.Timestamp(b["first"]).date().isoformat(),
                    "start": pd.Timestamp(b["first"]).strftime("%H:%M"),
                    "end": pd.Timestamp(b["last"]).strftime("%H:%M"),
                    "end_date": pd.Timestamp(b["last"]).date().isoformat(),
                    "minutes": round(float(b["ms"] / 60000.0), 1),
                    "plays": int(b["tracks"]),
                    "top_artist": art.index[0], "top_artist_minutes": round(float(art.iloc[0] / 60000.0), 1)},
        "longest_artist_run": {"artist": run_artist, "plays": int(best_run), "date": run_date},
    }


def summarize(music: pd.DataFrame, first_date: str, last_date: str, with_sessions: bool = True) -> dict:
    """All habit stats for one period. Dates are the period's covered first/last local dates."""
    t = timed(music)
    f, l = pd.Timestamp(first_date), pd.Timestamp(last_date)
    out = {
        "excluded_offline_minutes": round(float(music.loc[music["offline"].map(lambda v: v is True), "ms_played"].sum() / 60000.0), 1),
        "timed_minutes": round(float(t["ms_played"].sum() / 60000.0), 1),
        "clock": clock(t, f, l),
        "biggest_day": biggest_day(t),
        "artist_streaks": artist_streaks(t),
        "active_streak": active_streak(t),
        "repeat_week": repeat_week(t),
    }
    if with_sessions:
        out["sessions"] = sessions(t)
    return out


def build(music: pd.DataFrame, overall_cov: dict, year_covs: dict, early_late: dict | None) -> dict:
    res = {"overall": summarize(music, overall_cov["first_date"], overall_cov["last_date"]), "years": {}}
    for y, cov in year_covs.items():
        sub = music[music["year"] == int(y)]
        res["years"][y] = summarize(sub, cov["first_date"], cov["last_date"], with_sessions=False)
    if early_late:
        res["early_late"] = {}
        for key in ("early", "late"):
            w = early_late[key]
            first = pd.Period(w["start_month"], freq="M").start_time
            last = pd.Period(w["end_month"], freq="M").end_time.normalize()
            sub = music[music["month"].between(w["start_month"], w["end_month"])]
            res["early_late"][key] = clock(timed(sub), first, last)
    res["rules"] = {
        "offline_excluded": True,
        "session_gap_minutes": SESSION_GAP_MINUTES,
        "dayparts": {k: f"{a:02d}:00-{b:02d}:00" for k, (a, b) in DAYPARTS.items()},
        "play_threshold_ms": config.QUALIFIED_PLAY_MS,
    }
    return res
