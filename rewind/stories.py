"""Story data: every scene the interface shows, with the numbers that back it.

Headlines are filled from fixed templates. A story whose evidence is missing
is omitted and recorded under chapter["omitted"] with the reason.
"""

from __future__ import annotations

import hashlib
from datetime import date

import pandas as pd

from . import config

THRESHOLD = f"{config.ENGAGED_SHARE * 100:g}%"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------------------------------------------- formatting

def fmt_int(x: float) -> str:
    return f"{int(round(x)):,}"


def fmt_1(x: float) -> str:
    return f"{x:,.1f}"


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def month_label(m: str) -> str:
    y, mm = m.split("-")
    return f"{MONTHS[int(mm) - 1]} {y}"


def date_label(d: str) -> str:
    dt = date.fromisoformat(d)
    return f"{dt.day} {MONTHS[dt.month - 1]} {dt.year}"


def month_bounds(m: str) -> tuple[str, str]:
    p = pd.Period(m, freq="M")
    return p.start_time.date().isoformat(), p.end_time.date().isoformat()


def spotify_url(uri: str | None) -> str | None:
    if not uri or not uri.startswith("spotify:track:"):
        return None
    return "https://open.spotify.com/track/" + uri.split(":")[-1]


def story(chapter: str, kind: str, period: dict, headline: str, body: str, metrics: dict,
          evidence: list[dict], method: str, kicker: str, chart: str | None = None, data: dict | None = None) -> dict:
    return {"id": f"{chapter}.{kind}", "chapter": chapter, "type": kind, "period": period,
            "kicker": kicker, "headline": headline, "body": body, "metrics": metrics,
            "evidence": evidence, "method": method, "chart": chart, "data": data or {}}


def ev(label: str, value: str, source: str) -> dict:
    return {"label": label, "value": value, "source": source}


# ---------------------------------------------------------------- comparisons

def early_late(music: pd.DataFrame, months: list[dict], n: int = 12) -> dict | None:
    """First n complete months vs last n complete months, compared on rates and shares."""
    complete = [m["month"] for m in months if not m["partial"] and not m["low_activity"]]
    if len(complete) < 2 * n:
        return None
    windows = {"early": complete[:n], "late": complete[-n:]}
    out = {"window_months": n}
    for key, ms in windows.items():
        sub = music[music["month"].isin(ms)]
        days = sum(m["days_in_month"] for m in months if m["month"] in ms)
        minutes = sub["ms_played"].sum() / 60000.0
        active = sub.loc[sub["qualified_play"], "local_date"].nunique()
        art = sub.groupby("artist_id").agg(ms=("ms_played", "sum"), name=("artist", "first"))
        art = art.assign(_n=art["name"].str.casefold()).sort_values(["ms", "_n"], ascending=[False, True])
        total = art["ms"].sum()
        out[key] = {
            "start_month": ms[0], "end_month": ms[-1], "days": days,
            "minutes": round(minutes, 1),
            "minutes_per_day": round(minutes / days, 1),
            "active_day_rate": round(active / days, 3),
            "plays_per_active_day": round(int(sub["qualified_play"].sum()) / active, 1) if active else 0.0,
            "distinct_artists": int(sub.loc[sub["qualified_play"], "artist_id"].nunique()),
            "top_artist": {"id": art.index[0], "name": art["name"].iloc[0], "share": round(float(art["ms"].iloc[0] / total), 4)},
            "top10_share": round(float(art["ms"].head(10).sum() / total), 4),
            "top10_ids": list(art.index[:10]),
            "shares": {a: float(v / total) for a, v in art["ms"].items()},
            "names": art["name"].to_dict(),
        }
    out["top10_overlap"] = len(set(out["early"]["top10_ids"]) & set(out["late"]["top10_ids"]))
    # Rows for the comparison chart: union of each window's top 4, by max share.
    ids = list(dict.fromkeys(out["early"]["top10_ids"][:4] + out["late"]["top10_ids"][:4]))
    names = {**out["early"]["names"], **out["late"]["names"]}
    rows = [{"id": a, "name": names[a],
             "early": round(out["early"]["shares"].get(a, 0.0), 4),
             "late": round(out["late"]["shares"].get(a, 0.0), 4)} for a in ids]
    rows.sort(key=lambda r: (-max(r["early"], r["late"]), r["name"].casefold()))
    out["rows"] = rows
    for key in ("early", "late"):
        del out[key]["shares"], out[key]["names"]
    return out


def deterministic_order(items: list[dict], salt: str) -> list[dict]:
    return sorted(items, key=lambda it: hashlib.sha1((salt + it["id"]).encode()).hexdigest())


# ---------------------------------------------------------------- scene builders

def opening(ch: str, cov: dict, partial: bool, label: str, partial_note: str | None) -> dict:
    period = {"start": cov["first_date"], "end": cov["last_date"]}
    body = partial_note if partial and partial_note else f"{fmt_int(cov['days'])} days of listening history in this export."
    if partial_note and not partial:
        body += " " + partial_note
    return story(ch, "opening", period, f"{date_label(cov['first_date'])} to {date_label(cov['last_date'])}",
                 body, {"days": cov["days"], "partial": partial},
                 [ev("First recorded music", date_label(cov["first_date"]), "metrics.coverage.first_date"),
                  ev("Last recorded music", date_label(cov["last_date"]), "metrics.coverage.last_date"),
                  ev("Days covered", fmt_int(cov["days"]), "metrics.coverage.days")],
                 "Coverage runs from the first to the last local calendar day with a music record. "
                 "Timestamps are stream end times converted from UTC to local time by connection country.",
                 kicker=label)


def minutes_scene(ch: str, s: dict, chart: str | None) -> dict:
    cov = s["coverage"]
    return story(ch, "minutes", {"start": cov["first_date"], "end": cov["last_date"]},
                 f"{fmt_int(s['minutes'])} minutes",
                 f"of music, across {fmt_int(s['active_days'])} active days. "
                 f"That is {fmt_1(s['minutes_per_covered_day'])} minutes per covered day.",
                 {"minutes": s["minutes"], "active_days": s["active_days"],
                  "minutes_per_covered_day": s["minutes_per_covered_day"], "plays": s["plays"],
                  "coverage_days": cov["days"]},
                 [ev("Music minutes", fmt_1(s["minutes"]), "sum(ms_played)/60000 over music records"),
                  ev("Plays (30 s or more)", fmt_int(s["plays"]), "count of music records with ms_played >= 30000"),
                  ev("Active days", fmt_int(s["active_days"]), "local days with at least one play"),
                  ev("Days covered", fmt_int(cov["days"]), "coverage")],
                 "Minutes are the sum of actual ms_played for every music record, including skips. "
                 "Podcasts and duplicate records are excluded. Per-day rates divide by covered days so partial years compare fairly.",
                 kicker="Total music time", chart=chart)


def quiz_scene(ch: str, s: dict) -> dict | None:
    tracks = s["top_tracks"]
    if len(tracks) < 4:
        return None
    top = tracks[0]
    options = deterministic_order(
        [{"id": t["id"], "name": t["name"], "artist": t["artist"]} for t in tracks[:4]], salt=ch)
    by_plays = sorted(tracks, key=lambda t: (-t["plays"], -t["minutes"], t["name"].casefold()))[0]
    note = None
    if by_plays["id"] != top["id"]:
        note = (f"Ranked by plays instead, {by_plays['name']} by {by_plays['artist']} leads among "
                f"your top 10 songs by minutes ({fmt_int(by_plays['plays'])} plays).")
    cov = s["coverage"]
    return story(ch, "quiz", {"start": cov["first_date"], "end": cov["last_date"]},
                 "Which song did you spend the most time with?",
                 f"{top['name']} by {top['artist']}: {fmt_1(top['minutes'])} minutes across {fmt_int(top['plays'])} plays.",
                 {"answer_id": top["id"], "minutes": top["minutes"], "plays": top["plays"]},
                 [ev("Top song by minutes", f"{top['name']} ({top['artist']})", "top_tracks[0]"),
                  ev("Minutes", fmt_1(top["minutes"]), "top_tracks[0].minutes"),
                  ev("Plays (30 s or more)", fmt_int(top["plays"]), "top_tracks[0].plays"),
                  ev("Runner-up", f"{tracks[1]['name']} ({fmt_1(tracks[1]['minutes'])} min)", "top_tracks[1]")],
                 "Songs are ranked by total listening minutes. A song is its title plus artist, so re-releases with the "
                 "same title and artist count together. Ties break by plays, then title.",
                 kicker="Quiz", data={"options": options, "answer": top["id"],
                                      "answer_detail": {"name": top["name"], "artist": top["artist"],
                                                        "minutes": top["minutes"], "plays": top["plays"],
                                                        "url": spotify_url(top.get("uri"))},
                                      "plays_note": note})


def top_scene(ch: str, s: dict, scope: str = "all music time") -> dict:
    a, t = s["top_artists"][:5], s["top_tracks"][:5]
    cov = s["coverage"]
    lead = a[0]
    return story(ch, "top", {"start": cov["first_date"], "end": cov["last_date"]},
                 f"Your top artist: {lead['name']}",
                 f"{fmt_int(lead['minutes'])} minutes, {pct(s['top_artist_share'])} of {scope}.",
                 {"top_artist_minutes": lead["minutes"], "top_artist_share": s["top_artist_share"]},
                 [ev(f"#{x['rank']} {x['name']}", f"{fmt_1(x['minutes'])} min, {fmt_int(x['plays'])} plays", "top_artists")
                  for x in a] +
                 [ev(f"Song #{x['rank']} {x['name']}", f"{fmt_1(x['minutes'])} min", "top_tracks") for x in t],
                 "Artists and songs are ranked by total listening minutes; ties break by plays, then name. "
                 "The artist is the primary credited artist in the export.",
                 kicker="Top artists and songs",
                 data={"artists": [{"id": x["id"], "name": x["name"], "minutes": x["minutes"], "plays": x["plays"]} for x in a],
                       "tracks": [{"id": x["id"], "name": x["name"], "artist": x["artist"], "minutes": x["minutes"],
                                   "plays": x["plays"], "url": spotify_url(x.get("uri"))} for x in t]})


def ranking_scene(ch: str, months: list[dict]) -> dict | None:
    rows = [m for m in months if m["top_artists"]]
    if len(rows) < 3:
        return None
    leaders = [m["top_artists"][0] for m in rows]
    counts: dict[str, int] = {}
    names = {}
    for l in leaders:
        counts[l["id"]] = counts.get(l["id"], 0) + 1
        names[l["id"]] = l["name"]
    best = sorted(counts, key=lambda k: (-counts[k], names[k].casefold()))[0]
    # Longest run of consecutive months at #1.
    run, best_run, run_id, best_run_id = 0, 0, None, None
    for l in leaders:
        run = run + 1 if l["id"] == run_id else 1
        run_id = l["id"]
        if run > best_run:
            best_run, best_run_id = run, run_id
    first, last = rows[0]["month"], rows[-1]["month"]
    return story(ch, "ranking", {"start": month_bounds(first)[0], "end": month_bounds(last)[1]},
                 f"{len(counts)} artists held the top spot",
                 f"Month by month, ranked by listening minutes. {names[best]} was #1 in {counts[best]} of {len(rows)} months.",
                 {"distinct_leaders": len(counts), "months": len(rows), "most_months_id": best,
                  "most_months": counts[best], "longest_run": best_run, "longest_run_id": best_run_id},
                 [ev("Months shown", str(len(rows)), "metrics.months"),
                  ev("Different #1 artists", str(len(counts)), "metrics.months[*].top_artists[0]"),
                  ev(f"Most months at #1", f"{names[best]} ({counts[best]})", "count of months ranked #1"),
                  ev("Longest run at #1", f"{names[best_run_id]} ({best_run} months in a row)", "consecutive months ranked #1")],
                 "Each month ranks artists by that month's listening minutes. Partial months and months under "
                 f"{config.LOW_ACTIVITY_MINUTES} minutes are labelled; their ranks rest on less listening.",
                 kicker="Monthly ranking",
                 data={"months": [{"month": m["month"], "label": month_label(m["month"]), "partial": m["partial"],
                                   "low_activity": m["low_activity"], "minutes": m["minutes"],
                                   "top": [{"id": x["id"], "name": x["name"], "minutes": x["minutes"],
                                            "share": x["share"]} for x in m["top_artists"][:5]]}
                                  for m in rows]})


def transition_scene(ch: str, tr: dict | None, chart: str | None) -> dict | None:
    if not tr:
        return None
    r, d = tr["rose"][0] if tr["rose"] else None, tr["declined"][0] if tr["declined"] else None
    if not r or not d:
        return None
    body = (f"{r['name']} went from {pct(r['share_before'])} to {pct(r['share_after'])} of your listening, "
            f"while {d['name']} fell from {pct(d['share_before'])} to {pct(d['share_after'])}.")
    return story(ch, "transition", {"start": month_bounds(tr["before"]["start_month"])[0],
                                    "end": month_bounds(tr["after"]["end_month"])[1]},
                 f"Your biggest shift came in {month_label(tr['boundary_month'])}", body,
                 {"boundary_month": tr["boundary_month"], "hellinger": tr["hellinger"],
                  "stability": tr["stability"], "rose_id": r["id"], "declined_id": d["id"]},
                 [ev("Boundary", month_label(tr["boundary_month"]), "PELT boundary"),
                  ev("Era before", f"{month_label(tr['before']['start_month'])} to {month_label(tr['before']['end_month'])}", "eras"),
                  ev("Era after", f"{month_label(tr['after']['start_month'])} to {month_label(tr['after']['end_month'])}", "eras"),
                  ev("Hellinger distance between eras", f"{tr['hellinger']:.3f}", "largest among strong boundaries"),
                  ev("Kept in block resamples", pct(tr["stability"]), "bootstrap")] +
                 [ev(f"{x['name']}", f"{pct(x['share_before'])} to {pct(x['share_after'])}", "pooled share of music minutes")
                  for x in tr["rose"][:3] + tr["declined"][:3]],
                 "Shares are each artist's portion of music minutes, pooled over the era before and the era after the "
                 "boundary. The shift is the largest Hellinger distance between neighbouring eras among boundaries "
                 "kept in at least 80% of block resamples.",
                 kicker="Biggest taste transition", chart=chart,
                 data={"rose": tr["rose"][:3], "declined": tr["declined"][:3], "persisted": tr["persisted"][:3]})


def eras_scene(ch: str, era_list: list[dict], dropped: list[dict], chart: str | None) -> dict | None:
    if len(era_list) < 2:
        return None
    first, last = era_list[0], era_list[-1]
    return story(ch, "eras", {"start": month_bounds(first["start_month"])[0], "end": month_bounds(last["end_month"])[1]},
                 f"{len(era_list)} musical eras",
                 "Detected from changes in which artists filled your months, not from a fixed calendar.",
                 {"eras": len(era_list), "dropped_boundaries": len(dropped)},
                 [ev(f"Era {e['index']}: {month_label(e['start_month'])} to {month_label(e['end_month'])}",
                     f"{e['label_artist']} {pct(e['label_share'])}" + (f" ({e['confidence_note']})" if e.get("confidence_note") else ""),
                     "PELT segment, pooled artist shares") for e in era_list] +
                 [ev(f"Not shown: boundary at {month_label(b['month'])}", f"kept in {pct(b['stability'])} of resamples",
                     "insufficient evidence") for b in dropped],
                 "PELT on square-rooted monthly artist shares, squared-error cost, a penalty per boundary of beta times "
                 "the month-to-month noise, minimum era length 3 months. Boundaries kept in fewer than half of the "
                 "block resamples are treated as insufficient evidence and the eras either side are reported together.",
                 kicker="Musical eras", chart=chart,
                 data={"eras": [{k: e[k] for k in ("id", "index", "start_month", "end_month", "label_artist",
                                                   "label_share", "top_artists", "confidence", "start_stability",
                                                   "confidence_note")} for e in era_list]})


def partial_years_note(years: dict) -> str:
    """'2021 and 2026 are partial years.' derived from coverage; empty when every year is complete."""
    part = [y for y, s in years.items() if s["coverage"]["partial"]]
    if not part:
        return ""
    joined = part[0] if len(part) == 1 else ", ".join(part[:-1]) + " and " + part[-1]
    return f"{joined} {'is a partial year' if len(part) == 1 else 'are partial years'}."


def sustained_scene(ch: str, a: dict | None, chart: str | None, export_start: str = "") -> dict | None:
    if not a:
        return None
    return story(ch, "sustained", {"start": month_bounds(a["first_observed"])[0], "end": month_bounds(a["window_end"])[1]},
                 f"{a['name']} became a constant",
                 f"First observed in {month_label(a['first_observed'])}. From {month_label(a['first_engaged'])}, "
                 f"{THRESHOLD} or more of your music time in "
                 f"{a['engaged_in_first_window']} of the next {config.SUSTAINED_WINDOW} months.",
                 {"first_observed": a["first_observed"], "first_engaged": a["first_engaged"],
                  "engaged_in_first_window": a["engaged_in_first_window"], "total_minutes": a["total_minutes"],
                  "peak_start": a["peak_start"], "peak_end": a["peak_end"], "peak_share": a["peak_share"]},
                 [ev("First observed in this export", month_label(a["first_observed"]), "first month with any minutes"),
                  ev("First engaged month", month_label(a["first_engaged"]), f">= {THRESHOLD} and >= {config.ENGAGED_MIN_MINUTES} min"),
                  ev("Engaged months in the next 12", str(a["engaged_in_first_window"]), "sustained if >= 6"),
                  ev("Peak 3 months", f"{month_label(a['peak_start'])} to {month_label(a['peak_end'])}, {pct(a['peak_share'])} of music time", "rolling 3-month window"),
                  ev("Total minutes", fmt_1(a["total_minutes"]), "all music records")],
                 f"First observed means first within this export, which starts in {month_label(export_start) if export_start else 'its first month'}. An engaged month is one where "
                 f"the artist takes at least {THRESHOLD} of music minutes and at least "
                 f"{config.ENGAGED_MIN_MINUTES} minutes. Sustained means engaged in at least {config.SUSTAINED_MIN} of the "
                 f"{config.SUSTAINED_WINDOW} months starting at the first engaged month; artists without 12 months of "
                 "follow-up are not assessed.",
                 kicker="A favourite that stayed", chart=chart)


def comeback_scene(ch: str, a: dict | None, chart: str | None) -> dict | None:
    if not a:
        return None
    c = a["comeback"]
    return story(ch, "comeback", {"start": month_bounds(c["last_engaged_before"])[0], "end": month_bounds(c["return_month"])[1]},
                 f"{a['name']} came back",
                 f"{c['gap_months']} months under {config.ABSENT_MAX_MINUTES} minutes a month "
                 f"({month_label(c['gap_start'])} to {month_label(c['gap_end'])}), then "
                 f"{fmt_int(c['minutes_3m_after_return'])} minutes in the 3 months from {month_label(c['return_month'])}.",
                 {**c, "artist_id": a["id"]},
                 [ev("Last engaged month before the gap", month_label(c["last_engaged_before"]), "lifecycle"),
                  ev("Gap", f"{c['gap_months']} months, {fmt_1(c['minutes_during_gap'])} minutes in total", "months under 5 minutes"),
                  ev("Return month", month_label(c["return_month"]), f"first month back at >= {THRESHOLD}"),
                  ev("Minutes in the 3 months from the return", fmt_1(c["minutes_3m_after_return"]), "lifecycle")],
                 f"A comeback needs an engaged month, then at least {config.COMEBACK_GAP_MONTHS} consecutive months under "
                 f"{config.ABSENT_MAX_MINUTES} minutes, then another engaged month. The strongest comeback is the one with "
                 "the most minutes in the 3 months from the return.",
                 kicker="A comeback", chart=chart)


def stayed_scene(ch: str, a: dict | None, n_years: int, chart: str | None, partial_note: str = "") -> dict | None:
    if not a:
        return None
    years = a["years_in_top"]
    return story(ch, "stayed", {"start": f"{years[0]}-01-01", "end": f"{years[-1]}-12-31"},
                 f"{a['name']}: top {config.YEARLY_TOP_N} in {len(years)} of {n_years} years",
                 f"In your yearly top {config.YEARLY_TOP_N} every year from {years[0]} to {years[-1]}, "
                 f"with {a['engaged_months']} months at {THRESHOLD} or more of your music time.",
                 {"years_in_top": years, "engaged_months": a["engaged_months"], "total_minutes": a["total_minutes"]},
                 [ev(f"{y}", f"#{a['yearly_ranks'][y]}", "yearly rank by minutes") for y in sorted(a["yearly_ranks"])] +
                 [ev("Engaged months", str(a["engaged_months"]), "lifecycle")],
                 f"Yearly ranks use minutes within each calendar year. {partial_note} The artist with "
                 f"the most years in the top {config.YEARLY_TOP_N} is shown; ties break by engaged months, then minutes.",
                 kicker="Stayed important", chart=chart, data={"ranks": a["yearly_ranks"]})


def early_late_scene(ch: str, el: dict | None, chart: str | None, left_out: list[str] | None = None) -> dict | None:
    if not el:
        return None
    e, l = el["early"], el["late"]
    return story(ch, "early_late", {"start": month_bounds(e["start_month"])[0], "end": month_bounds(l["end_month"])[1]},
                 "Your first year vs your latest year",
                 f"{fmt_1(e['minutes_per_day'])} vs {fmt_1(l['minutes_per_day'])} minutes a day. "
                 f"{l['top_artist']['name']} took {pct(l['top_artist']['share'])} of the latest year; "
                 f"{e['top_artist']['name']} led the first with {pct(e['top_artist']['share'])}.",
                 {"early": e, "late": l, "top10_overlap": el["top10_overlap"]},
                 [ev("First 12 complete months", f"{month_label(e['start_month'])} to {month_label(e['end_month'])}", "complete months"),
                  ev("Latest 12 complete months", f"{month_label(l['start_month'])} to {month_label(l['end_month'])}", "complete months"),
                  ev("Minutes per day", f"{fmt_1(e['minutes_per_day'])} vs {fmt_1(l['minutes_per_day'])}", "minutes / calendar days"),
                  ev("Days with a play", f"{pct(e['active_day_rate'])} vs {pct(l['active_day_rate'])}", "active days / calendar days"),
                  ev("Artists played", f"{fmt_int(e['distinct_artists'])} vs {fmt_int(l['distinct_artists'])}", "distinct artists with a play"),
                  ev("Top 10 artists' share", f"{pct(e['top10_share'])} vs {pct(l['top10_share'])}", "concentration"),
                  ev("Early top 10 still in the latest top 10", f"{el['top10_overlap']} of 10", "overlap")],
                 "Both windows are 12 complete calendar months, so seasons and lengths match. Partial months"
                 + (f" ({', '.join(month_label(m) for m in left_out)})" if left_out else "")
                 + " and months under the activity floor are left out. Rates divide by calendar days.",
                 kicker="Early vs late", chart=chart, data={"rows": el["rows"]})


def arrival_scene(ch: str, year: int, lifecycles: list[dict], year_minutes: dict[str, float]) -> dict | None:
    cands = [a for a in lifecycles if a["first_engaged"] and a["first_engaged"].startswith(str(year))
             and not a["left_censored"]]
    if not cands:
        return None
    # Most minutes in the year; ties break by name (case-folded, ascending).
    a = min(cands, key=lambda c: (-year_minutes.get(c["id"], 0.0), c["name"].casefold()))
    mins = year_minutes.get(a["id"], 0.0)
    if mins < 60:
        return None
    return story(ch, "arrival", {"start": month_bounds(a["first_engaged"])[0], "end": f"{year}-12-31"},
                 f"{a['name']} broke through",
                 f"First observed in {month_label(a['first_observed'])}; first month at "
                 f"{THRESHOLD} or more of your listening was {month_label(a['first_engaged'])}. "
                 f"{fmt_int(mins)} minutes in {year}.",
                 {"first_observed": a["first_observed"], "first_engaged": a["first_engaged"], "minutes_in_year": round(mins, 1)},
                 [ev("First observed", month_label(a["first_observed"]), "lifecycle"),
                  ev("First engaged month", month_label(a["first_engaged"]), "lifecycle"),
                  ev(f"Minutes in {year}", fmt_1(mins), "metrics")],
                 "Of the artists whose first engaged month falls in this year (and who were not already present when the "
                 "export begins), the one with the most minutes in the year.",
                 kicker=f"New in {year}")


def year_eras_scene(ch: str, year: int, era_list: list[dict]) -> dict | None:
    inside = [e for e in era_list if e["start_month"][:4] <= str(year) <= e["end_month"][:4]]
    if not inside:
        return None
    return story(ch, "year_eras", {"start": f"{year}-01-01", "end": f"{year}-12-31"},
                 f"{len(inside)} era{'s' if len(inside) > 1 else ''} touched {year}",
                 "; ".join(f"{month_label(e['start_month'])} to {month_label(e['end_month'])}, defined by {e['label_artist']}" for e in inside) + ".",
                 {"eras": [e["id"] for e in inside]},
                 [ev(f"Era {e['index']}", f"{month_label(e['start_month'])} to {month_label(e['end_month'])}, "
                     f"{e['label_artist']} {pct(e['label_share'])}", "eras") for e in inside],
                 "Eras are detected over the whole history, then intersected with this year.",
                 kicker="Eras this year", data={"eras": [e["id"] for e in inside]})



# ---------------------------------------------------------------- habits and obsessions

def hour_label(h: int) -> str:
    h = h % 24
    suffix = "AM" if h < 12 else "PM"
    return f"{(h % 12) or 12} {suffix}"


def short_date(d: str) -> str:
    dt = date.fromisoformat(d)
    return f"{dt.day} {MONTHS[dt.month - 1]}"


def date_range(start: str, end: str) -> str:
    """'22 Oct to 30 Dec 2022', or '1 Nov 2022 to 1 Jun 2023' when the years differ."""
    first = short_date(start) if start[:4] == end[:4] else date_label(start)
    return f"{first} to {date_label(end)}"


def duration_label(minutes: float) -> str:
    total = int(round(minutes))
    h, m = divmod(total, 60)
    if h and m:
        return f"{h} hour{'s' if h != 1 else ''} {m} minute{'s' if m != 1 else ''}"
    if h:
        return f"{h} hour{'s' if h != 1 else ''}"
    return f"{m} minute{'s' if m != 1 else ''}"


TIMING_RULE = ("Offline plays are left out: their timestamp is when the phone synced, not when the music "
               "played. Each stream's minutes are split across the clock hours it covered, in local time.")


def clock_scene(ch: str, cov: dict, c: dict | None, chart: str | None, label: str = "",
                shift: dict | None = None) -> dict | None:
    if not c:
        return None
    d = c["dayparts"]
    body = (f"{pct(d['evening'])} of your music time fell between 5 PM and midnight, "
            f"{pct(d['night'])} between midnight and 5 AM.")
    metrics = {"peak_hour": c["peak_hour"], "peak_hour_share": c["peak_hour_share"], "dayparts": d,
               "peak_weekday": c["peak_weekday"], "peak_weekday_minutes": c["peak_weekday_minutes"]}
    evidence = [ev("Peak hour", f"{hour_label(c['peak_hour'])} to {hour_label(c['peak_hour'] + 1)}, "
                   f"{pct(c['peak_hour_share'])} of music time", "minutes per local clock hour"),
                ev("Evening (5 PM to midnight)", pct(d["evening"]), "daypart share"),
                ev("Afternoon (noon to 5 PM)", pct(d["afternoon"]), "daypart share"),
                ev("Morning (5 AM to noon)", pct(d["morning"]), "daypart share"),
                ev("Night (midnight to 5 AM)", pct(d["night"]), "daypart share"),
                ev("Busiest weekday", f"{c['peak_weekday']}, {fmt_1(c['peak_weekday_minutes'])} min on an average {c['peak_weekday']}",
                   "minutes per occurrence of each weekday in the covered dates")]
    if shift:
        e, l = shift["early"], shift["late"]
        body += (f" After-midnight listening went from {pct(e['dayparts']['night'])} in your first year "
                 f"to {pct(l['dayparts']['night'])} in your latest.")
        metrics["night_share_early"] = e["dayparts"]["night"]
        metrics["night_share_late"] = l["dayparts"]["night"]
        evidence.append(ev("Peak hour, first vs latest 12 complete months",
                           f"{hour_label(e['peak_hour'])} vs {hour_label(l['peak_hour'])}", "same windows as Early vs late"))
    return story(ch, "clock", {"start": cov["first_date"], "end": cov["last_date"]},
                 f"Your peak hour{label}: {hour_label(c['peak_hour'])}", body, metrics, evidence,
                 TIMING_RULE + " Weekday averages divide by how many of that weekday the period covers.",
                 kicker="Listening clock", chart=chart,
                 data={"bins": c["bins"], "dayparts": d, "peak_hour_label": hour_label(c["peak_hour"]),
                       "weekdays": c["weekday_minutes_per_day"], "peak_weekday": c["peak_weekday"]})


def biggest_day_scene(ch: str, b: dict | None) -> dict | None:
    if not b:
        return None
    t = b["top_artist"]
    return story(ch, "biggest_day", {"start": b["date"], "end": b["date"]},
                 f"Your biggest day: {date_label(b['date'])}",
                 f"{fmt_int(b['minutes'])} minutes of music, {fmt_int(b['plays'])} plays, {b['artists']} artists. "
                 f"{t['name']} took {fmt_int(t['minutes'])} minutes of it.",
                 {"date": b["date"], "minutes": b["minutes"], "plays": b["plays"], "artists": b["artists"],
                  "top_artist_id": t["id"], "top_artist_minutes": t["minutes"]},
                 [ev("Date", date_label(b["date"]), "local day with the most music minutes"),
                  ev("Music minutes", fmt_1(b["minutes"]), "sum of ms_played that day"),
                  ev("Plays (30 s or more)", fmt_int(b["plays"]), "qualified plays that day"),
                  ev("Different artists", str(b["artists"]), "artists with any minutes that day"),
                  ev(f"Top artist that day", f"{t['name']}, {fmt_1(t['minutes'])} min", "most minutes that day")],
                 TIMING_RULE + " Ties go to the earliest date.",
                 kicker="Biggest day", data={"top_artist": t})


def streak_scene(ch: str, streaks: list[dict], active: dict | None, year_label: str = "") -> dict | None:
    if not streaks:
        return None
    s = streaks[0]
    body = (f"{date_range(s['start'], s['end'])}: at least one play every day, "
            f"{fmt_int(s['plays'])} plays in total.")
    evidence = [ev(f"#{i + 1} {x['name']}", f"{x['days']} days, {date_range(x['start'], x['end'])}",
                   "consecutive local days with a play") for i, x in enumerate(streaks)]
    if active:
        body += f" Your longest run of days with any music: {fmt_int(active['days'])} days."
        evidence.append(ev("Longest run of days with any play", f"{active['days']} days, "
                           f"{date_label(active['start'])} to {date_label(active['end'])}", "consecutive active days"))
    return story(ch, "streak", {"start": s["start"], "end": s["end"]},
                 f"{s['days']} days in a row with {s['name']}{year_label}", body,
                 {"artist_id": s["id"], "days": s["days"], "start": s["start"], "end": s["end"], "plays": s["plays"],
                  "active_streak_days": active["days"] if active else None},
                 evidence,
                 TIMING_RULE + " A streak counts consecutive local days with at least one play (30 s or more) of "
                 "the artist; within a year chapter, streaks are cut at the year boundaries. Ties go to more "
                 "minutes in the run, then the earlier start.",
                 kicker="Streak", data={"streaks": streaks})


def repeat_scene(ch: str, r: dict | None) -> dict | None:
    if not r:
        return None
    return story(ch, "repeat", {"start": r["week_start"], "end": r["week_end"]},
                 f"{r['track']}: {r['plays']} plays in one week",
                 f"{r['artist']}, week of {date_label(r['week_start'])}. {fmt_int(r['minutes'])} minutes on one song.",
                 {"track_id": r["track_id"], "plays": r["plays"], "minutes": r["minutes"], "week_start": r["week_start"]},
                 [ev("Song", f"{r['track']} ({r['artist']})", "most plays of one song in a Monday-to-Sunday week"),
                  ev("Week", f"{date_label(r['week_start'])} to {date_label(r['week_end'])}", "local dates"),
                  ev("Plays (30 s or more)", str(r["plays"]), "that week"),
                  ev("Minutes", fmt_1(r["minutes"]), "those plays")],
                 TIMING_RULE + " Weeks run Monday to Sunday. Ties go to more minutes, then the earlier week.",
                 kicker="On repeat", data={"track": r["track"], "artist": r["artist"]})


def session_scene(ch: str, s: dict | None) -> dict | None:
    if not s:
        return None
    b, run = s["longest"], s["longest_artist_run"]
    span = f"{b['start']} to {b['end']}" + ("" if b["end_date"] == b["date"] else " the next day")
    body = (f"{date_label(b['date'])}, {span}: {fmt_int(b['plays'])} plays without a break of more than "
            f"30 minutes.")
    if run["artist"]:
        body += f" Your longest back-to-back run: {run['plays']} {run['artist']} plays in a row."
    return story(ch, "session", {"start": b["date"], "end": b["end_date"]},
                 f"Your longest session: {duration_label(b['minutes'])}", body,
                 {"minutes": b["minutes"], "plays": b["plays"], "date": b["date"], "sessions": s["sessions"],
                  "median_minutes": s["median_minutes"], "artist_run": run["plays"]},
                 [ev("Longest session", f"{fmt_1(b['minutes'])} min, {date_label(b['date'])} {span}", "sessions"),
                  ev("Plays in it", fmt_int(b["plays"]), "qualified plays"),
                  ev("Most-played artist in it", f"{b['top_artist']}, {fmt_1(b['top_artist_minutes'])} min", "minutes"),
                  ev("All sessions", f"{fmt_int(s['sessions'])}, median {fmt_1(s['median_minutes'])} min", "sessions"),
                  ev("Longest same-artist run", f"{run['plays']} plays, {run['artist']}, {date_label(run['date'])}" if run["artist"] else "none",
                     "back-to-back plays within one session")],
                 TIMING_RULE + " A session ends when more than 30 minutes pass between one stream ending and the "
                 "next starting (timed in UTC so a timezone change cannot split or merge sessions).",
                 kicker="Longest session", data={"run": run})

def summary_scene(ch: str, scenes: list[dict], label: str) -> dict:
    lines = []
    for s in scenes:
        if s["type"] in ("minutes",):
            lines.append({"label": "Minutes", "value": fmt_int(s["metrics"]["minutes"])})
        elif s["type"] == "top":
            lines.append({"label": "Top artist", "value": s["data"]["artists"][0]["name"]})
            lines.append({"label": "Top song", "value": s["data"]["tracks"][0]["name"]})
        elif s["type"] == "eras":
            lines.append({"label": "Eras", "value": str(s["metrics"]["eras"])})
        elif s["type"] == "ranking":
            lines.append({"label": "Different #1 artists", "value": str(s["metrics"]["distinct_leaders"])})
        elif s["type"] == "clock":
            lines.append({"label": "Peak hour", "value": hour_label(s["metrics"]["peak_hour"])})
        elif s["type"] == "streak":
            lines.append({"label": "Longest streak", "value": f"{s['metrics']['days']} days"})
    period = {"start": scenes[0]["period"]["start"], "end": scenes[0]["period"]["end"]}
    return story(ch, "summary", period, f"That was {label}", "Replay it, or pick a year.",
                 {"lines": len(lines)}, [ev(l["label"], l["value"], "earlier scenes") for l in lines],
                 "Every number here repeats a number from an earlier scene in this chapter.",
                 kicker="Summary", data={"lines": lines})
