"""End-to-end, reproducible analysis: python3 -m rewind.pipeline

Reads the export (read-only), writes intermediates to work/, reports and charts
to outputs/, and the browser data to web/data/.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import charts, config, eras, habits, ingest, lifecycle, metrics, reports, stories, techlog, validation

STRONG = 0.8   # boundary kept in >= 80% of block resamples
SUPPORTED = 0.5  # below this a boundary is insufficient evidence


def add_months(m: str, k: int) -> str:
    return str(pd.Period(m, freq="M") + k)


def label_eras(space, res, stability: dict) -> list[dict]:
    era_list = eras.describe_segments(space, res)
    last_month = space.months[-1]
    for k, e in enumerate(era_list):
        sig = e["signature_artist"]
        lead = sig if sig else e["top_artists"][0]
        e["label_artist"], e["label_share"] = lead["name"], lead["share"]
        e["label_artist_id"] = lead["id"]
        e["label_share_outside"] = sig["share_outside"] if sig else None
        e["start_stability"] = None if k == 0 else stability[e["start_month"]]
        if k == 0:
            e["confidence"] = "start of export"
        else:
            s = e["start_stability"]
            e["confidence"] = "strong" if s >= STRONG else "moderate"
        notes = []
        if k == 0 and space.months[0] != e["start_month"]:
            notes.append(f"{stories.month_label(space.months[0])} excluded as low activity")
        if e["end_month"] == last_month:
            notes.append("ends at the export cutoff; latest month partial")
        if e["confidence"] == "moderate":
            notes.append(f"start kept in {stories.pct(e['start_stability'])} of resamples")
        e["confidence_note"] = "; ".join(notes) if notes else None
    return era_list


def biggest_transition(space, res, era_list, stability) -> dict | None:
    best = None
    for b in range(1, len(res.segments)):
        month = res.valid_months[res.segments[b][0]]
        if stability.get(month, 0.0) < STRONG:
            continue
        ex = eras.explain_boundary(space, res, b)
        ex.update({"stability": stability[month], "before": era_list[b - 1], "after": era_list[b]})
        if best is None or ex["hellinger"] > best["hellinger"]:
            best = ex
    return best


def pick_sustained(lcs: list[dict]) -> dict | None:
    cands = [a for a in lcs if a.get("sustained") and not a["left_censored"] and a["best_monthly_rank"] == 1]
    if not cands:
        return None
    a = dict(max(cands, key=lambda c: (c["total_minutes"], c["name"])))
    a["window_end"] = add_months(a["first_engaged"], config.SUSTAINED_WINDOW - 1)
    return a


def pick_comeback(lcs: list[dict]) -> dict | None:
    best = None
    for a in lcs:
        for c in a["comebacks"]:
            key = (c["minutes_3m_after_return"], c["gap_months"])
            if best is None or key > best[0]:
                best = (key, {**a, "comeback": c})
    return best[1] if best else None


def pick_stayed(lcs: list[dict], used: set[str], year_ranks: dict[str, dict[str, int]]) -> dict | None:
    cands = [a for a in lcs if len(a["years_in_top"]) >= 3]
    if not cands:
        return None
    def key(c):
        return (len(c["years_in_top"]), c["engaged_months"], c["total_minutes"])
    top_count = max(len(c["years_in_top"]) for c in cands)
    tier = [c for c in cands if len(c["years_in_top"]) == top_count]
    fresh = [c for c in tier if c["id"] not in used] or tier
    a = dict(max(fresh, key=key))
    a["yearly_ranks"] = {y: r[a["id"]] for y, r in year_ranks.items() if a["id"] in r}
    return a


def clock_specs(hab: dict) -> dict:
    """Listening-clock polar charts: share of timed music minutes per 3-hour local window."""
    specs = {}
    periods = [("all", "all years", hab["overall"]["clock"])] + [
        (y, y, v["clock"]) for y, v in hab["years"].items()]
    for key, label, c in periods:
        if not c:
            continue
        cats = [{"label": b["label"], "value": round(b["share"] * 100, 1)} for b in c["bins"]]
        peak = c["peak_bin"]
        specs[f"clock-{key}"] = {
            "type": "polar", "title": f"Listening clock, {label}",
            "desc": (f"Polar chart of the share of music minutes in each 3-hour local window for {label}, "
                     f"clockwise from 00–03 at the top; the peak window is {cats[peak]['label']} at "
                     f"{cats[peak]['value']}%."),
            "unit": "% OF MUSIC MINUTES", "categories": cats, "focal": peak,
            "source": "Local time. Offline plays excluded. Peak window highlighted.",
        }
    return specs


def chart_specs(m, era_list, space, transition, sustained, comeback, stayed_rows, early, years) -> dict:
    specs = {}
    specs["minutes-by-year"] = {
        "type": "bar", "title": "Music minutes per covered day, by year",
        "desc": (f"Bar chart of average music minutes per covered day for each year from {min(years)} to {max(years)}. "
                 + stories.partial_years_note(years)).strip(),
        "unit": "MIN / DAY",
        "bars": [{"label": y, "value": s["minutes_per_covered_day"], "partial": s["coverage"]["partial"],
                  "total": s["minutes"]} for y, s in years.items()],
        "source": "Minutes / covered days. * partial year.",
    }
    specs["eras"] = {
        "type": "gantt", "title": "Musical eras detected by PELT",
        "desc": f"Timeline of {len(era_list)} listening eras from {era_list[0]['start_month']} to {era_list[-1]['end_month']}, each labelled with its defining artist.",
        "months": space.months,
        "rows": [{"id": e["id"], "label": f"Era {e['index']}", "artist": e["label_artist"],
                  "start": e["start_month"], "end": e["end_month"], "confidence": e["confidence"]}
                 for e in era_list],
        "excluded": [mm for mm, v in zip(space.months, space.valid) if not v],
        "focal": transition["after"]["id"] if transition else None,
        "source": "Bar = era span. Label = artist with the largest share lift.",
    }
    if transition:
        rows = []
        for x in transition["rose"][:3] + transition["declined"][:3] + transition["persisted"][:2]:
            if x["id"] not in [r["id"] for r in rows]:
                rows.append(x)
        specs["transition"] = {
            "type": "dumbbell", "title": f"Artist shares around {stories.month_label(transition['boundary_month'])}",
            "desc": "Dumbbell chart of each artist's share of music minutes in the era before and the era after the biggest boundary.",
            "from_label": "Before", "to_label": "After",
            "rows": [{"id": r["id"], "name": r["name"], "from": r["share_before"], "to": r["share_after"]} for r in rows[:8]],
            "source": "Share of music minutes, pooled per era. Rows: risers, fallers, then steady artists.",
        }
    if sustained:
        halves = []
        start = pd.Period(sustained["first_observed"], freq="M")
        h0 = f"{start.year}-H{1 if start.month <= 6 else 2}"
        allh = []
        for mm in space.months:
            p = pd.Period(mm, freq="M")
            allh.append(f"{p.year}-H{1 if p.month <= 6 else 2}")
        order = list(dict.fromkeys(allh))
        order = order[order.index(h0):]
        col = space.artist_ids.index(sustained["id"])
        for h in order:
            idx = [i for i, x in enumerate(allh) if x == h and space.valid[i]]
            tot = space.total_minutes[idx].sum()
            share = float(space.minutes[idx, col].sum() / tot) if tot else 0.0
            partial = any(m["months"][i]["partial"] for i in idx) or len(idx) < 6
            halves.append({"label": h, "value": round(share * 100, 1), "partial": partial})
        specs["sustained"] = {
            "type": "line", "title": f"{sustained['name']}: share of music time",
            "desc": f"Line chart of {sustained['name']}'s share of music minutes in each half-year from {order[0]} to {order[-1]}.",
            "unit": "% OF MINUTES", "points": halves[-12:], "series": sustained["name"],
            "source": "Share of music minutes per half-year. * incomplete half-year.",
        }
    if comeback:
        c = comeback["comeback"]
        end = add_months(c["return_month"], 2)
        start = max(c["last_engaged_before"], add_months(end, -11))
        span = [mm for mm in space.months if start <= mm <= end]
        col = space.artist_ids.index(comeback["id"])
        pts = [{"label": mm, "value": round(float(space.minutes[space.months.index(mm), col]), 1),
                "gap": c["gap_start"] <= mm <= c["gap_end"]} for mm in span]
        specs["comeback"] = {
            "type": "line", "title": f"{comeback['name']}: minutes per month",
            "desc": f"Line chart of monthly listening minutes for {comeback['name']} from {span[0]} to {span[-1]}, showing a {c['gap_months']}-month gap and the return.",
            "unit": "MINUTES", "points": pts, "series": comeback["name"], "monthly": True,
            "band": [c["gap_start"], c["gap_end"]],
            "source": f"Shaded: gap months under {config.ABSENT_MAX_MINUTES} minutes.",
        }
    if stayed_rows:
        specs["stayed"] = {
            "type": "presence", "title": f"Yearly top {config.YEARLY_TOP_N} membership",
            "desc": f"Grid-style timeline showing which years each of {len(stayed_rows['rows'])} artists ranked in the yearly top {config.YEARLY_TOP_N}, with the rank printed.",
            "years": stayed_rows["years"], "rows": stayed_rows["rows"], "focal": stayed_rows["focal"],
            "source": "Rank by minutes within each year. * partial year.",
        }
    if early:
        specs["early-late"] = {
            "type": "dumbbell", "title": "First year vs latest year: artist shares",
            "desc": "Dumbbell chart comparing each artist's share of music minutes in the first and the latest 12 complete months.",
            "from_label": "First 12 months", "to_label": "Latest 12 months",
            "rows": [{"id": r["id"], "name": r["name"], "from": r["early"], "to": r["late"]} for r in early["rows"][:6]],
            "source": f"{early['early']['start_month']} to {early['early']['end_month']} vs {early['late']['start_month']} to {early['late']['end_month']}. Rows: 6 largest shares in either window.",
        }
    for y in years:
        mrows = [r for r in m["months"] if r["month"].startswith(y)]
        specs[f"year-{y}"] = {
            "type": "line", "title": f"{y}: music minutes per day, by month",
            "desc": f"Line chart of average music minutes per covered day in each month of {y}.",
            "unit": "MIN / DAY", "monthly": True, "series": y,
            "points": [{"label": r["month"], "value": round(r["minutes"] / r["days_covered"], 1),
                        "partial": r["partial"] or r["low_activity"]} for r in mrows],
            "source": "Minutes / covered days in the month. * partial or low-activity month.",
        }
    return specs


def run(synthetic_reps: int = 30, bootstrap_reps: int = 200, write: bool = True,
        paths: config.Paths | None = None, tz_overrides: dict | None = None) -> dict:
    paths = paths or config.Paths()
    raw = ingest.load_export(paths.export_dir)  # fails before any output folder is created
    if write:
        for d in (paths.work_dir, paths.output_dir, paths.web_data_dir):
            d.mkdir(parents=True, exist_ok=True)
    records, audit = ingest.clean(raw, tz_overrides)
    audit["technical_log"] = techlog.reconcile_raw_core_stream(records, paths.techlog_dir)
    music = records[records["is_music"]].copy()
    m = metrics.build(records)

    # Eras.
    space = eras.build_space(music, m["months"])
    X = space.embedded[space.valid]
    plays = np.array([r["plays"] for r, v in zip(m["months"], space.valid) if v])
    synthetic = validation.run_synthetic(plays, eras.noise_scale(X), reps=synthetic_reps)
    choice = validation.choose_beta(synthetic)
    beta = config.ERA_BETA or choice["beta"]
    raw_res = eras.detect(space, beta)
    boot = validation.bootstrap(music, space, raw_res, reps=bootstrap_reps)
    stability = boot["boundary_stability"]
    keep = [b for b in raw_res.boundaries if stability[raw_res.valid_months[b]] >= SUPPORTED]
    dropped = [{"month": raw_res.valid_months[b], "stability": stability[raw_res.valid_months[b]]}
               for b in raw_res.boundaries if b not in keep]
    res = eras.keep_boundaries(raw_res, keep)
    era_list = label_eras(space, res, stability)
    transition = biggest_transition(space, res, era_list, stability)
    boundary_explanations = [
        {**eras.explain_boundary(space, res, b), "stability": stability[res.valid_months[res.segments[b][0]]]}
        for b in range(1, len(res.segments))
    ]
    base_k = validation.choose_baseline_k(synthetic)
    baseline = [res.valid_months[b] for b in eras.adjacent_distance_baseline(X, k=base_k)]
    era_validation = {
        "settings": {"beta": beta, "penalty": raw_res.penalty, "noise_scale": raw_res.noise,
                     "min_size": raw_res.min_size, "jump": config.ERA_JUMP,
                     "low_activity_minutes": config.LOW_ACTIVITY_MINUTES,
                     "artist_space_size": len(space.artist_ids)},
        "beta_choice": choice,
        "excluded_months": {mm: r for mm, r in zip(space.months, space.exclusion_reason) if r},
        "pelt_boundaries": [raw_res.valid_months[b] for b in raw_res.boundaries],
        "reported_boundaries": [res.valid_months[b] for b in res.boundaries],
        "dropped_boundaries": dropped,
        "bootstrap": boot,
        "permutation_null": validation.permutation_null(space, beta, raw_res.min_size),
        "baseline": {"k": base_k, "boundaries": baseline},
        "sensitivity": validation.sensitivity(music, m["months"]),
        "synthetic": synthetic,
        "eras": era_list,
        "boundary_explanations": boundary_explanations,
    }

    # Lifecycles.
    year_tops = {y: [a["id"] for a in s["top_artists"][:config.YEARLY_TOP_N]] for y, s in m["years"].items()}
    year_ranks = {y: {a["id"]: a["rank"] for a in s["top_artists"][:config.YEARLY_TOP_N]} for y, s in m["years"].items()}
    lcs = lifecycle.artist_lifecycles(space, year_tops)
    sustained = pick_sustained(lcs)
    comeback = pick_comeback(lcs)
    used = {x["id"] for x in (sustained, comeback) if x}
    stayed = pick_stayed(lcs, used, year_ranks)
    stayed_rows = None
    if stayed:
        ranked = sorted([a for a in lcs if len(a["years_in_top"]) >= 2],
                        key=lambda c: (-len(c["years_in_top"]), -c["engaged_months"], -c["total_minutes"]))[:6]
        if stayed["id"] not in [a["id"] for a in ranked]:
            ranked = [stayed] + ranked[:5]
        stayed_rows = {"years": [{"label": y, "partial": s["coverage"]["partial"]} for y, s in m["years"].items()],
                       "rows": [{"id": a["id"], "name": a["name"],
                                 "ranks": {y: year_ranks[y][a["id"]] for y in year_ranks if a["id"] in year_ranks[y]}}
                                for a in ranked],
                       "focal": stayed["id"]}
    early = stories.early_late(music, m["months"])
    specs = chart_specs(m, era_list, space, transition, sustained, comeback, stayed_rows, early, m["years"])
    hab = habits.build(music, m["overall"]["coverage"], {y: s["coverage"] for y, s in m["years"].items()}, early)
    specs.update(clock_specs(hab))

    # Chapters.
    chapters = []
    o = m["overall"]
    scenes = [
        stories.opening("all", o["coverage"], False, "Spotify Rewind",
                        stories.partial_years_note(m["years"]) or None),
        stories.minutes_scene("all", o, "minutes-by-year"),
        stories.quiz_scene("all", o),
        stories.top_scene("all", o),
        stories.ranking_scene("all", m["months"]),
        stories.clock_scene("all", o["coverage"], hab["overall"]["clock"], "clock-all",
                            shift=hab.get("early_late")),
        stories.biggest_day_scene("all", hab["overall"]["biggest_day"]),
        stories.session_scene("all", hab["overall"]["sessions"]),
        stories.streak_scene("all", hab["overall"]["artist_streaks"], hab["overall"]["active_streak"]),
        stories.repeat_scene("all", hab["overall"]["repeat_week"]),
        stories.transition_scene("all", transition, "transition" if transition else None),
        stories.eras_scene("all", era_list, dropped, "eras"),
        stories.sustained_scene("all", sustained, "sustained" if sustained else None, export_start=m["months"][0]["month"]),
        stories.comeback_scene("all", comeback, "comeback" if comeback else None),
        stories.stayed_scene("all", stayed, len(m["years"]), "stayed" if stayed else None,
                             partial_note=stories.partial_years_note(m["years"])),
        stories.early_late_scene("all", early, "early-late" if early else None,
                                 left_out=[r["month"] for r in m["months"] if r["partial"]]),
    ]
    names = ["opening", "minutes", "quiz", "top", "ranking", "clock", "biggest_day", "session", "streak",
             "repeat", "transition", "eras", "sustained", "comeback", "stayed", "early_late"]
    omitted = [{"type": n, "reason": "not supported by the data under the declared rules"}
               for n, s in zip(names, scenes) if s is None]
    scenes = [s for s in scenes if s]
    scenes.append(stories.summary_scene("all", scenes, "five years of listening"))
    chapters.append({"id": "all", "label": "All years", "partial": False,
                     "period": {"start": o["coverage"]["first_date"], "end": o["coverage"]["last_date"]},
                     "scenes": scenes, "omitted": omitted})
    for y, s in m["years"].items():
        cov = s["coverage"]
        note = None
        if cov["partial"]:
            note = (f"Partial year: {cov['days']} of {cov['days_in_year']} days are in the export "
                    f"({stories.date_label(cov['first_date'])} to {stories.date_label(cov['last_date'])}).")
        ymonths = [r for r in m["months"] if r["month"].startswith(y)]
        year_minutes = music[music["year"] == int(y)].groupby("artist_id")["ms_played"].sum() / 60000.0
        ys = [
            stories.opening(y, cov, cov["partial"], f"Rewind {y}", note),
            stories.minutes_scene(y, s, f"year-{y}"),
            stories.quiz_scene(y, s),
            stories.top_scene(y, s, f"your {y} music time"),
            stories.ranking_scene(y, ymonths),
            stories.clock_scene(y, cov, hab["years"][y]["clock"], f"clock-{y}", label=f" in {y}"),
            stories.biggest_day_scene(y, hab["years"][y]["biggest_day"]),
            stories.streak_scene(y, hab["years"][y]["artist_streaks"], hab["years"][y]["active_streak"],
                                 year_label=f" in {y}"),
            stories.arrival_scene(y, int(y), lcs, year_minutes.to_dict()),
            stories.year_eras_scene(y, int(y), era_list),
        ]
        ynames = ["opening", "minutes", "quiz", "top", "ranking", "clock", "biggest_day", "streak",
                  "arrival", "year_eras"]
        yomit = [{"type": n, "reason": "not supported by the data under the declared rules"}
                 for n, sc in zip(ynames, ys) if sc is None]
        ys = [sc for sc in ys if sc]
        ys.append(stories.summary_scene(y, ys, f"your {y}" + (" (partial year)" if cov["partial"] else "")))
        chapters.append({"id": y, "label": y, "partial": cov["partial"],
                         "partial_note": note,
                         "period": {"start": cov["first_date"], "end": cov["last_date"]},
                         "scenes": ys, "omitted": yomit})

    story_doc = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title": "Spotify Rewind",
        "coverage": o["coverage"],
        "definitions": m["definitions"],
        "chapters": chapters,
    }
    result = {"audit": ingest.coerce_audit(audit), "metrics": m, "era_validation": era_validation,
              "lifecycles": lcs, "early_late": early, "habits": hab, "stories": story_doc, "chart_specs": specs}
    if write:
        write_outputs(result, paths)
    return result


def dump(obj, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(ingest.coerce_audit(obj), handle, indent=1, ensure_ascii=False, default=str)
        handle.write("\n")


def write_outputs(result: dict, paths: config.Paths | None = None) -> None:
    paths = paths or config.Paths()
    dump(result["audit"], paths.output_dir / "data_audit.json")
    dump(result["metrics"], paths.work_dir / "metrics.json")
    dump(result["lifecycles"], paths.work_dir / "lifecycles.json")
    dump(result["era_validation"], paths.output_dir / "era_validation.json")
    dump(result["early_late"], paths.work_dir / "early_late.json")
    dump(result["habits"], paths.work_dir / "habits.json")
    dump(result["chart_specs"], paths.work_dir / "chart_specs.json")
    dump(result["stories"], paths.output_dir / "stories.json")
    dump(result["stories"], paths.web_data_dir / "stories.json")
    chart_dir = paths.output_dir / "charts"
    if chart_dir.exists():
        shutil.rmtree(chart_dir)
    web_chart_dir = paths.web_data_dir / "charts"
    if web_chart_dir.exists():
        shutil.rmtree(web_chart_dir)
    charts.build_all(result["chart_specs"], chart_dir, web_chart_dir)
    reports.write_reports(result, paths.output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-reps", type=int, default=30)
    parser.add_argument("--bootstrap-reps", type=int, default=200)
    args = parser.parse_args()
    result = run(args.synthetic_reps, args.bootstrap_reps)
    o = result["metrics"]["overall"]
    print(f"music records {result['audit']['music_records']:,}; minutes {o['minutes']:,.1f}; "
          f"eras {len(result['era_validation']['eras'])}; chapters {len(result['stories']['chapters'])}")


if __name__ == "__main__":
    main()
