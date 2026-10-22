"""Score a pipeline run against a synthetic export's planted ground truth."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def _months_apart(a: str, b: str) -> int:
    return abs((pd.Period(a, freq="M") - pd.Period(b, freq="M")).n)


def boundary_scores(found: list[str], truth: list[str], tol: int = 1) -> dict:
    unused = list(truth)
    tp = 0
    for f in found:
        hit = next((t for t in unused if _months_apart(f, t) <= tol), None)
        if hit:
            unused.remove(hit)
            tp += 1
    precision = tp / len(found) if found else (1.0 if not truth else 0.0)
    recall = tp / len(truth) if truth else 1.0
    return {"true_positives": tp, "precision": round(precision, 3), "recall": round(recall, 3)}


def evaluate(result: dict, truth: dict) -> dict:
    audit = result["audit"]
    hab = result["habits"]["overall"]
    scenes = {s["type"]: s for s in result["stories"]["chapters"][0]["scenes"]}
    era = result["era_validation"]
    found = era["reported_boundaries"]
    b = boundary_scores(found, truth["era_boundaries"])
    checks = []

    def check(name, expected, actual, ok=None):
        checks.append({"check": name, "expected": expected, "actual": actual,
                       "pass": bool(expected == actual if ok is None else ok)})

    check("Raw records read", truth["raw_records"], audit["raw_records"])
    check("Exact duplicates removed", truth["exact_duplicates"], audit["exact_duplicates_removed"])
    check("Podcast episodes excluded", truth["podcast_episodes"], audit["non_music_records_excluded"].get("episode", 0))
    check("Music records kept", truth["music_records"], audit["music_records"])
    check("Music minutes", truth["music_minutes"], round(audit["music_minutes"], 1),
          ok=abs(truth["music_minutes"] - audit["music_minutes"]) <= 0.1)
    check("Travel-week records on Asia/Tokyo time", truth["travel_records"],
          audit["records_by_timezone"].get("Asia/Tokyo", 0))
    check("Era boundaries recovered (within 1 month)", truth["era_boundaries"], found,
          ok=b["recall"] == 1.0 and b["precision"] == 1.0)
    cb = scenes.get("comeback", {}).get("metrics", {})
    cb_name = next((a["name"] for a in result["lifecycles"] if a["id"] == cb.get("artist_id")), None)
    check("Comeback artist", truth["comeback"]["artist"], cb_name)
    check("Comeback return month", truth["comeback"]["returns"], cb.get("return_month"))
    check("Biggest day", truth["biggest_day"], hab["biggest_day"]["date"])
    peak = hab["clock"]["bins"][hab["clock"]["peak_bin"]]["start"]
    check("Peak 3-hour window starts", truth["peak_window_start_hour"], peak)
    check("Top artist", truth["top_artist"], result["metrics"]["overall"]["top_artists"][0]["name"])
    check("Longest artist streak (days)", truth["longest_streak"]["days"], hab["artist_streaks"][0]["days"])
    return {"passed": sum(c["pass"] for c in checks), "total": len(checks), "boundaries": b, "checks": checks}


def write(report: dict, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    (out_dir / "evaluation.json").write_text(json.dumps(report, indent=1, default=str))
    rows = ["| Check | Planted | Recovered | Result |", "|---|---|---|---|"]
    for c in report["checks"]:
        rows.append(f"| {c['check']} | {c['expected']} | {c['actual']} | {'pass' if c['pass'] else 'FAIL'} |")
    b = report["boundaries"]
    text = "\n".join([
        "# Ground-truth evaluation", "",
        "A synthetic export with planted structure was run through the full pipeline. Each row compares what was "
        "planted (computed by the generator, independently of the analysis code) with what the pipeline recovered.", "",
        f"Result: {report['passed']} of {report['total']} checks pass. Era boundaries: precision {b['precision']}, "
        f"recall {b['recall']} (match within one month).", "",
        *rows, "",
    ])
    (out_dir / "evaluation.md").write_text(text)
