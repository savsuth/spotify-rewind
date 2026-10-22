"""Listening metrics: coverage, minutes, active days, rankings.

Ranking metric for artists, tracks and albums: total listening minutes (sum of
ms_played, every music record). Ties break by qualified play count (desc), then
name (case-folded, asc), then stable ID (asc). Play counts use the 30 s rule and
are reported beside minutes, never mixed into them.
"""

from __future__ import annotations

import calendar

import pandas as pd

from . import config


def music_only(records: pd.DataFrame) -> pd.DataFrame:
    return records[records["is_music"]].copy()


def rank_table(music: pd.DataFrame, key: str, label_cols: list[str], top: int | None = None) -> pd.DataFrame:
    """Aggregate minutes and plays by an entity key and sort with the declared tie-break."""
    agg = music.groupby(key, sort=False).agg(
        ms=("ms_played", "sum"),
        plays=("qualified_play", "sum"),
        records=("ms_played", "size"),
    )
    labels = music.groupby(key, sort=False)[label_cols].first()
    table = agg.join(labels).reset_index()
    table["minutes"] = table["ms"] / 60000.0
    table["_name"] = table[label_cols[0]].astype(str).str.casefold()
    table = table.sort_values(
        ["ms", "plays", "_name", key], ascending=[False, False, True, True], kind="mergesort"
    ).drop(columns="_name")
    table["rank"] = range(1, len(table) + 1)
    table["plays"] = table["plays"].astype(int)
    return table.head(top) if top else table


def top_track_uri(music: pd.DataFrame) -> pd.Series:
    """Most-played URI per merged track (name + artist), for optional listening links."""
    by = music.groupby(["track_id", "track_uri"])["ms_played"].sum().reset_index()
    by = by.sort_values(["track_id", "ms_played", "track_uri"], ascending=[True, False, True])
    return by.drop_duplicates("track_id").set_index("track_id")["track_uri"]


def coverage(music: pd.DataFrame) -> dict:
    first = music["local_date"].min()
    last = music["local_date"].max()
    return {"first_date": first.date().isoformat(), "last_date": last.date().isoformat(),
            "days": int((last - first).days) + 1}


def year_coverage(music: pd.DataFrame) -> dict[int, dict]:
    first = music["local_date"].min()
    last = music["local_date"].max()
    out = {}
    for year in range(first.year, last.year + 1):
        start = max(first, pd.Timestamp(year=year, month=1, day=1))
        end = min(last, pd.Timestamp(year=year, month=12, day=31))
        days_in_year = 366 if calendar.isleap(year) else 365
        days = int((end - start).days) + 1
        out[year] = {
            "first_date": start.date().isoformat(),
            "last_date": end.date().isoformat(),
            "days": days,
            "days_in_year": days_in_year,
            "partial": days < days_in_year,
        }
    return out


def entity_rows(table: pd.DataFrame, key: str, fields: dict[str, str], uris: pd.Series | None = None) -> list[dict]:
    rows = []
    for _, r in table.iterrows():
        row = {"id": r[key], "rank": int(r["rank"]), "minutes": round(float(r["minutes"]), 1),
               "plays": int(r["plays"])}
        for out_name, col in fields.items():
            row[out_name] = r[col]
        if uris is not None and r[key] in uris.index:
            row["uri"] = uris[r[key]]
        rows.append(row)
    return rows


def summarize(music: pd.DataFrame, cov: dict, uris: pd.Series, top_n: int = 10) -> dict:
    minutes = music["ms_played"].sum() / 60000.0
    active_days = music.loc[music["qualified_play"], "local_date"].nunique()
    any_days = music.loc[music["ms_played"] > 0, "local_date"].nunique()
    artists = rank_table(music, "artist_id", ["artist"])
    tracks = rank_table(music, "track_id", ["track", "artist", "artist_id"])
    albums = rank_table(music, "album_id", ["album", "artist", "artist_id"])
    top_artist_share = float(artists["ms"].iloc[0] / music["ms_played"].sum()) if len(artists) else 0.0
    return {
        "coverage": cov,
        "minutes": round(minutes, 1),
        "music_records": int(len(music)),
        "plays": int(music["qualified_play"].sum()),
        "active_days": int(active_days),
        "days_with_any_music": int(any_days),
        "minutes_per_covered_day": round(minutes / cov["days"], 1),
        "minutes_per_active_day": round(minutes / active_days, 1) if active_days else None,
        "distinct_artists_played": int(music.loc[music["qualified_play"], "artist_id"].nunique()),
        "distinct_tracks_played": int(music.loc[music["qualified_play"], "track_id"].nunique()),
        "top_artist_share": round(top_artist_share, 4),
        "top10_artist_share": round(float(artists["ms"].head(10).sum() / music["ms_played"].sum()), 4),
        "top_artists": entity_rows(artists.head(top_n), "artist_id", {"name": "artist"}),
        "top_tracks": entity_rows(tracks.head(top_n), "track_id",
                                  {"name": "track", "artist": "artist", "artist_id": "artist_id"}, uris),
        "top_albums": entity_rows(albums.head(5), "album_id",
                                  {"name": "album", "artist": "artist", "artist_id": "artist_id"}),
    }


def month_range(music: pd.DataFrame) -> list[str]:
    first = music["local_date"].min().to_period("M")
    last = music["local_date"].max().to_period("M")
    return [str(p) for p in pd.period_range(first, last, freq="M")]


def monthly(music: pd.DataFrame, top_n: int = 10) -> list[dict]:
    """One row per calendar month in coverage, including months with no listening."""
    first = music["local_date"].min()
    last = music["local_date"].max()
    rows = []
    for month in month_range(music):
        period = pd.Period(month, freq="M")
        m_start = max(first, period.start_time.normalize())
        m_end = min(last, period.end_time.normalize())
        days_covered = int((m_end - m_start).days) + 1
        sub = music[music["month"] == month]
        minutes = sub["ms_played"].sum() / 60000.0
        ranked = rank_table(sub, "artist_id", ["artist"]) if len(sub) else pd.DataFrame()
        rows.append({
            "month": month,
            "minutes": round(float(minutes), 1),
            "plays": int(sub["qualified_play"].sum()),
            "active_days": int(sub.loc[sub["qualified_play"], "local_date"].nunique()),
            "days_covered": days_covered,
            "days_in_month": int(period.days_in_month),
            "coverage_ratio": round(days_covered / period.days_in_month, 3),
            "partial": days_covered < period.days_in_month,
            "low_activity": bool(minutes < config.LOW_ACTIVITY_MINUTES),
            "top_artists": [
                {"id": r["artist_id"], "name": r["artist"], "rank": int(r["rank"]),
                 "minutes": round(float(r["minutes"]), 1), "plays": int(r["plays"]),
                 "share": round(float(r["ms"] / sub["ms_played"].sum()), 4)}
                for _, r in ranked.head(top_n).iterrows()
            ] if len(sub) else [],
        })
    return rows


def build(records: pd.DataFrame) -> dict:
    music = music_only(records)
    uris = top_track_uri(music)
    overall = summarize(music, coverage(music), uris)
    years = {}
    for year, cov in year_coverage(music).items():
        sub = music[music["year"] == year]
        summary = summarize(sub, {"first_date": cov["first_date"], "last_date": cov["last_date"],
                                  "days": cov["days"]}, uris)
        summary["coverage"].update({"days_in_year": cov["days_in_year"], "partial": cov["partial"]})
        years[str(year)] = summary
    return {
        "definitions": {
            "listening_minutes": "Sum of ms_played over every music record, divided by 60,000.",
            "play": f"A music record with ms_played >= {config.QUALIFIED_PLAY_MS} ms. Used only for play counts.",
            "active_day": "A local calendar day with at least one play.",
            "ranking": "Minutes desc, then plays desc, then name asc (case-folded), then stable ID asc.",
            "track_identity": "Track name + artist name (merges re-releases that share both).",
            "album_identity": "Album name + album artist name.",
            "artist_identity": "master_metadata_album_artist_name (primary credited artist).",
            "timezone": "Local time inferred from connection country; US = America/New_York.",
        },
        "overall": overall,
        "years": years,
        "months": monthly(music),
    }
