"""Load the extended streaming history, classify it, and apply cleaning rules.

The export folder is read-only input. Nothing here writes next to it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import config

EXPORT_FIELDS = (
    "ts",
    "platform",
    "ms_played",
    "conn_country",
    "ip_addr",
    "master_metadata_track_name",
    "master_metadata_album_artist_name",
    "master_metadata_album_album_name",
    "spotify_track_uri",
    "episode_name",
    "episode_show_name",
    "spotify_episode_uri",
    "audiobook_title",
    "audiobook_uri",
    "audiobook_chapter_uri",
    "audiobook_chapter_title",
    "reason_start",
    "reason_end",
    "shuffle",
    "skipped",
    "offline",
    "offline_timestamp",
    "incognito_mode",
)


def load_export(export_dir: Path = config.EXPORT_DIR) -> pd.DataFrame:
    """Read every Streaming_History_*.json file into one frame, tagging its source."""
    frames = []
    for path in sorted(Path(export_dir).glob("Streaming_History_*.json")):
        with path.open(encoding="utf-8") as handle:
            rows = json.load(handle)
        frame = pd.DataFrame.from_records(rows)
        for field in EXPORT_FIELDS:
            if field not in frame.columns:
                frame[field] = None
        frame["source_file"] = path.name
        frame["source_kind"] = "video" if "_Video_" in path.name else "audio"
        frame["source_row"] = np.arange(len(frame))
        frames.append(frame)
    if not frames:
        raise FileNotFoundError(f"no Streaming_History_*.json files in {export_dir}")
    frames = [f.astype(object) for f in frames]
    return pd.concat(frames, ignore_index=True)


def classify(frame: pd.DataFrame) -> pd.Series:
    """Content type from URIs: track (music), episode (podcast/video show), audiobook, unknown."""
    kind = pd.Series("unknown", index=frame.index, dtype=object)
    audiobook = frame["audiobook_uri"].notna() | frame["audiobook_chapter_uri"].notna()
    kind[audiobook] = "audiobook"
    kind[frame["spotify_episode_uri"].notna()] = "episode"
    kind[frame["spotify_track_uri"].notna()] = "track"
    return kind


def local_times(ts_utc: pd.Series, country: pd.Series, tz_map: dict | None = None) -> tuple[pd.Series, pd.Series]:
    """Convert UTC end times to naive local wall-clock times using conn_country."""
    tz_names = country.map(tz_map or config.TZ_BY_COUNTRY).fillna(config.FALLBACK_TZ)
    local = pd.Series(pd.NaT, index=ts_utc.index, dtype="datetime64[ns]")
    for tz_name, index in tz_names.groupby(tz_names).groups.items():
        local.loc[index] = ts_utc.loc[index].dt.tz_convert(tz_name).dt.tz_localize(None)
    return local, tz_names


def stable_id(prefix: str, *parts: str) -> str:
    key = "\x1f".join(p.casefold().strip() for p in parts)
    return prefix + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def union_length(starts: np.ndarray, ends: np.ndarray) -> float:
    """Total length covered by a set of intervals (same units as the inputs)."""
    if len(starts) == 0:
        return 0.0
    order = np.argsort(starts, kind="stable")
    s, e = starts[order], ends[order]
    total, cur_s, cur_e = 0.0, s[0], e[0]
    for a, b in zip(s[1:], e[1:]):
        if a > cur_e:
            total += cur_e - cur_s
            cur_s, cur_e = a, b
        else:
            cur_e = max(cur_e, b)
    return float(total + cur_e - cur_s)


def overlap_with(starts: np.ndarray, ends: np.ndarray, ref_s: np.ndarray, ref_e: np.ndarray) -> float:
    """Total time the first interval set spends inside the union of the reference set."""
    if len(starts) == 0 or len(ref_s) == 0:
        return 0.0
    both_s = np.concatenate([starts, ref_s])
    both_e = np.concatenate([ends, ref_e])
    return union_length(starts, ends) + union_length(ref_s, ref_e) - union_length(both_s, both_e)


def clean(raw: pd.DataFrame, tz_overrides: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Apply the cleaning rules and return privacy-safe records plus an audit.

    tz_overrides maps a connection country code to an IANA zone, e.g. {"US": "America/Chicago"}.
    """
    df = raw.copy()
    audit: dict = {"raw_records": int(len(df))}
    audit["records_by_file"] = df.groupby("source_file").size().astype(int).to_dict()
    audit["records_by_source_kind"] = df.groupby("source_kind").size().astype(int).to_dict()

    df["content_type"] = classify(df)
    audit["records_by_content_type"] = df.groupby("content_type").size().astype(int).to_dict()
    audit["content_type_by_source_kind"] = {
        f"{k}/{c}": int(n) for (k, c), n in df.groupby(["source_kind", "content_type"]).size().items()
    }

    # Exact duplicates: identical in every exported field. Keep the first copy.
    present = [f for f in EXPORT_FIELDS if f in df.columns]
    key = df[present].astype(str)
    df["is_duplicate"] = key.duplicated(keep="first")
    audit["exact_duplicates_removed"] = int(df["is_duplicate"].sum())
    ms_numeric = pd.to_numeric(df["ms_played"], errors="coerce")
    audit["exact_duplicate_ms"] = int(ms_numeric[df["is_duplicate"]].fillna(0).sum())
    audit["exact_duplicates_by_kind"] = (
        df[df["is_duplicate"]].groupby("source_kind").size().astype(int).to_dict()
    )
    # Same end time and URI but different ms_played: offline plays synced in a
    # batch share a timestamp. These are distinct plays and are kept.
    uri = df["spotify_track_uri"].fillna(df["spotify_episode_uri"])
    same_ts_uri = pd.DataFrame({"ts": df["ts"], "uri": uri})[~df["is_duplicate"]]
    audit["same_timestamp_and_uri_kept"] = int(same_ts_uri.duplicated(keep="first").sum())

    df["ms_played"] = ms_numeric
    df["invalid_duration"] = df["ms_played"].isna() | (df["ms_played"] < 0)
    df["implausible_duration"] = (df["content_type"] == "track") & (
        df["ms_played"] > config.MAX_PLAUSIBLE_TRACK_MS
    )
    audit["invalid_duration"] = int(df["invalid_duration"].sum())
    audit["implausible_track_duration"] = int(df["implausible_duration"].sum())
    audit["zero_ms_records"] = int((df["ms_played"] == 0).sum())

    df["ts_utc"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    df["invalid_timestamp"] = df["ts_utc"].isna()
    audit["invalid_timestamp"] = int(df["invalid_timestamp"].sum())

    is_track = df["content_type"] == "track"
    df["missing_metadata"] = is_track & (
        df["master_metadata_album_artist_name"].isna() | df["master_metadata_track_name"].isna()
    )
    audit["track_missing_artist_or_name"] = int(df["missing_metadata"].sum())
    audit["track_missing_album"] = int((is_track & df["master_metadata_album_album_name"].isna()).sum())

    tz_map = {**config.TZ_BY_COUNTRY, **(tz_overrides or {})}
    local, tz_names = local_times(df["ts_utc"], df["conn_country"], tz_map)
    # Record only the zones actually used, so reports state the assumption that applied.
    seen = set(df["conn_country"].dropna().unique())
    audit["timezone_map"] = {c: z for c, z in sorted(tz_map.items()) if c in seen}
    df["local_ts"] = local
    df["tz"] = tz_names
    audit["records_by_timezone"] = df.groupby("tz").size().astype(int).to_dict()
    # How many records land in a different calendar year locally than in UTC.
    audit["year_differs_local_vs_utc"] = int(
        (df["local_ts"].dt.year != df["ts_utc"].dt.year).fillna(False).sum()
    )
    # Filename year vs timestamp year, to show why filenames are not used.
    file_year = df["source_file"].str.extract(r"_(\d{4})")[0].astype(float)
    audit["filename_year_differs_from_local_year"] = int(
        (file_year != df["local_ts"].dt.year).sum()
    )

    df["is_music"] = (
        is_track
        & ~df["is_duplicate"]
        & ~df["invalid_duration"]
        & ~df["invalid_timestamp"]
        & ~df["missing_metadata"]
        & ~df["implausible_duration"]
    )
    df["qualified_play"] = df["is_music"] & (df["ms_played"] >= config.QUALIFIED_PLAY_MS)

    # Audio/video overlap: does music from the video files overlap audio plays in time?
    music = df[df["is_music"] & (df["ms_played"] > 0)]
    end = music["ts_utc"].astype("int64").to_numpy() / 1e6  # ms since epoch
    start = end - music["ms_played"].to_numpy(dtype=float)
    vid = (music["source_kind"] == "video").to_numpy()
    offline = music["offline"].map(lambda v: v is True).to_numpy(dtype=bool)
    audit["video_music_records"] = int(vid.sum())
    audit["video_music_minutes"] = round(float(music.loc[vid, "ms_played"].sum()) / 60000, 2)
    audit["video_audio_overlap_minutes"] = round(
        overlap_with(start[vid], end[vid], start[~vid], end[~vid]) / 60000, 2
    )
    online = ~offline
    audit["concurrent_overlap_minutes_online"] = round(
        (float(np.sum(end[online] - start[online])) - union_length(start[online], end[online])) / 60000, 2
    )
    audit["concurrent_overlap_minutes_offline"] = round(
        (float(np.sum(end[offline] - start[offline])) - union_length(start[offline], end[offline])) / 60000, 2
    )

    df["artist"] = df["master_metadata_album_artist_name"]
    df["track"] = df["master_metadata_track_name"]
    df["album"] = df["master_metadata_album_album_name"]
    df["track_uri"] = df["spotify_track_uri"]
    df["show"] = df["episode_show_name"]

    keep = [
        "ts_utc", "local_ts", "tz", "source_file", "source_kind", "source_row",
        "content_type", "ms_played", "artist", "track", "album", "track_uri", "show",
        "reason_start", "reason_end", "shuffle", "skipped", "offline", "incognito_mode",
        "is_duplicate", "invalid_duration", "implausible_duration", "invalid_timestamp",
        "missing_metadata", "is_music", "qualified_play",
    ]
    records = df[keep].copy()
    records["local_date"] = records["local_ts"].dt.normalize()
    records["year"] = records["local_ts"].dt.year.astype("Int64")
    records["month"] = records["local_ts"].dt.strftime("%Y-%m")
    records["artist_id"] = [
        stable_id("ar_", a) if isinstance(a, str) else None for a in records["artist"]
    ]
    records["track_id"] = [
        stable_id("tr_", t, a) if isinstance(t, str) and isinstance(a, str) else None
        for t, a in zip(records["track"], records["artist"])
    ]
    records["album_id"] = [
        stable_id("al_", b, a) if isinstance(b, str) and isinstance(a, str) else None
        for b, a in zip(records["album"], records["artist"])
    ]

    mus = records[records["is_music"]]
    audit["music_records"] = int(len(mus))
    audit["music_ms"] = int(mus["ms_played"].sum())
    audit["music_minutes"] = round(mus["ms_played"].sum() / 60000, 2)
    audit["qualified_plays"] = int(records["qualified_play"].sum())
    audit["non_music_records_excluded"] = {
        c: int(n)
        for c, n in records[~records["is_duplicate"] & (records["content_type"] != "track")]
        .groupby("content_type").size().items()
    }
    audit["non_music_minutes"] = {
        c: round(float(s) / 60000, 2)
        for c, s in records[~records["is_duplicate"] & (records["content_type"] != "track")]
        .groupby("content_type")["ms_played"].sum().items()
    }
    audit["first_local_ts"] = str(mus["local_ts"].min())
    audit["last_local_ts"] = str(mus["local_ts"].max())
    audit["first_utc_ts"] = str(records["ts_utc"].min())
    audit["last_utc_ts"] = str(records["ts_utc"].max())

    # Reconciliation: every raw record lands in exactly one bucket.
    buckets = {
        "music": int(records["is_music"].sum()),
        "exact_duplicate": int(records["is_duplicate"].sum()),
        "non_music": int((~records["is_duplicate"] & (records["content_type"] != "track")).sum()),
        "track_excluded_invalid": int(
            (~records["is_duplicate"] & (records["content_type"] == "track") & ~records["is_music"]).sum()
        ),
    }
    buckets["total"] = sum(buckets.values())
    audit["reconciliation"] = buckets
    if buckets["total"] != audit["raw_records"]:
        raise AssertionError(f"reconciliation failed: {buckets} vs {audit['raw_records']}")
    return records, audit


def coerce_audit(value):
    """Make numpy scalars JSON-serialisable."""
    if isinstance(value, dict):
        return {str(k): coerce_audit(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [coerce_audit(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value
