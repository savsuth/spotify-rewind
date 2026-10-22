"""Synthetic Spotify extended-streaming-history exports with planted ground truth.

Writes files in the same JSON schema and file naming as a real export
(Streaming_History_Audio_<year>[_n].json, Streaming_History_Video_<year>.json),
with fictional artists and tracks, so the whole pipeline can run on data that
has known answers and no personal information.

Planted structure (all reproducible from the seed):
- Eras: listening is drawn from a different artist mix in each planted era.
- A comeback: one era-1 favourite is silent for the middle eras, then returns.
- A biggest day: one date with several times the usual volume.
- An evening peak: start times concentrate in one 3-hour window.
- A travel week in Japan (exercises per-country timezones).
- Noise the cleaner must handle: podcasts, exact duplicates, zero-ms skips,
  offline plays logged at sync time, and music played in video files.

The ground truth is computed here from the generated records, independently of
the analysis code, and written next to the export as ground_truth.json.
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ADJ = ["Velvet", "Neon", "Paper", "Static", "Golden", "Hollow", "Silver", "Midnight", "Electric", "Quiet",
       "Crimson", "Lunar", "Wild", "Glass", "Northern", "Faded", "Bright", "Sugar", "Concrete", "Distant",
       "Copper", "Violet", "Broken", "Summer", "Atomic", "Ivory", "Restless", "Paper", "Cosmic", "Tidal"]
NOUN = ["Harbor", "Engines", "Lanterns", "Coast", "Satellites", "Gardens", "Arcade", "Rivers", "Signals",
        "Parade", "Motel", "Comets", "Echoes", "Saints", "Avenue", "Wolves", "Machines", "Tapes", "Season",
        "Club", "Weather", "Pilots", "Hearts", "Radio", "Atlas", "Mirrors", "Orchard", "District", "Waves"]
WORDS = ["Gold", "Rain", "Fever", "Lights", "Hometown", "Overdrive", "Blue", "Afterglow", "Runaway", "Static",
         "Heartbeat", "Mirage", "Sundown", "Velvet", "Highway", "Paper", "Moon", "Cherry", "Wildfire", "Glow",
         "Echo", "Neon", "Satellite", "Ocean", "Polaroid", "Gravity", "Daydream", "Avalanche", "Rewind", "Tides"]
SHOWS = ["The Long Shift", "Weekly Signal", "Notes From Nowhere"]
B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
HOME_TZ = "America/New_York"
TRAVEL_TZ = "Asia/Tokyo"


@dataclass
class Track:
    name: str
    artist: str
    album: str
    uri: str
    seconds: int


def _uri(rng: random.Random, kind: str) -> str:
    return f"spotify:{kind}:" + "".join(rng.choice(B62) for _ in range(22))


def _catalogue(rng: random.Random, n_artists: int) -> dict[str, list[Track]]:
    names: list[str] = []
    while len(names) < n_artists:
        name = f"{rng.choice(ADJ)} {rng.choice(NOUN)}" if rng.random() < .8 else f"The {rng.choice(NOUN)}"
        if name not in names:
            names.append(name)
    cat = {}
    for a in names:
        album = f"{rng.choice(WORDS)} {rng.choice(['Sessions', 'Tapes', 'Hours', 'Lines', 'Days'])}"
        titles = set()
        while len(titles) < 8:
            titles.add(f"{rng.choice(WORDS)} {rng.choice(WORDS)}" if rng.random() < .6 else rng.choice(WORDS))
        cat[a] = [Track(t, a, album, _uri(rng, "track"), rng.randint(140, 260)) for t in sorted(titles)]
    return cat


def _month_add(d: date, k: int) -> date:
    y, m = divmod(d.month - 1 + k, 12)
    return date(d.year + y, m + 1, 1)


def generate(out_dir: Path, seed: int = 7, start: date = date(2022, 3, 1), months: int = 40,
             streams_per_day: float = 30.0) -> dict:
    """Write a synthetic export into out_dir and return its ground truth."""
    rng = random.Random(seed)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    marker = out_dir / ".rewind-synthetic"
    existing = list(out_dir.glob("Streaming_History_*.json"))
    if existing and not marker.exists():
        # Never delete export files this generator did not write: they may be a real export.
        raise FileExistsError(f"{out_dir} already holds Streaming_History files that are not synthetic; "
                              "choose an empty folder")
    for old in existing:
        old.unlink()
    marker.write_text("Written by rewind.synth; safe to regenerate.\n")

    cat = _catalogue(rng, 120)
    artists = list(cat)
    # Planted eras: month index where each era starts (for 40 months: 0, 8, 17, 25, 33).
    if months < 24:
        raise ValueError("synthetic exports need at least 24 months to plant five eras and a comeback")
    era_starts = [0] + [int(round(f * months)) for f in (.2, .425, .625, .825)]
    n_eras = len(era_starts)
    comeback = artists[0]
    steady = artists[1:4]                      # important in every era
    favourites = [artists[4 + 4 * e: 8 + 4 * e] for e in range(n_eras)]
    favourites[3] = [comeback] + favourites[3][1:]  # the comeback artist leads era 4
    tail = artists[4 + 4 * n_eras:]

    def era_of(month_idx: int) -> int:
        return max(i for i, s in enumerate(era_starts) if month_idx >= s)

    def weights(era: int) -> tuple[list[str], list[float]]:
        w = defaultdict(float)
        for a in steady:
            w[a] += .06
        for i, a in enumerate(favourites[era]):
            w[a] += [.24, .14, .09, .06][i]
        if era == 0:
            w[comeback] += .10                  # an era-1 favourite before the silence
        for a in tail:
            w[a] += .23 / len(tail)
        if era in (1, 2):
            w.pop(comeback, None)              # silent through eras 2 and 3
        names = list(w)
        return names, [w[a] for a in names]

    # Start-time distribution (local hour): evening peak 18-21.
    hour_w = [2, 1, .5, .3, .2, .3, .8, 1.5, 2.5, 3, 3.2, 3.5, 4, 4, 4.2, 4.4, 5, 6, 11, 12, 11, 6, 4, 3]
    end_date = _month_add(start, months) - timedelta(days=1)
    biggest_day = start + timedelta(days=(end_date - start).days // 2 + 3)
    travel = [biggest_day + timedelta(days=60 + i) for i in range(7)]

    records = []
    music_meta = []  # parallel info for ground truth: (local_dt, artist, track, ms, offline)
    day = start
    while day <= end_date:
        m_idx = (day.year - start.year) * 12 + day.month - start.month
        names, w = weights(era_of(m_idx))
        travelling = day in travel
        tz, country = (TRAVEL_TZ, "JP") if travelling else (HOME_TZ, "US")
        lam = streams_per_day * (1.25 if day.weekday() >= 5 else 1.0)
        n = int(rng.gauss(lam, lam * .25))
        if day == biggest_day:
            n = int(streams_per_day * 6)
        n = max(n, 0)
        for _ in range(n):
            hour = rng.choices(range(24), hour_w)[0]
            local = datetime(day.year, day.month, day.day, hour, rng.randrange(60), rng.randrange(60))
            if rng.random() < .02:  # podcast episode
                ms = rng.randint(60_000, 1_800_000)
                end = (local.replace(tzinfo=ZoneInfo(tz)) + timedelta(milliseconds=ms)).astimezone(timezone.utc)
                records.append(_record(end, ms, country, None, episode=(rng.choice(SHOWS), _uri(rng, "episode"))))
                continue
            artist = rng.choices(names, w)[0]
            track = rng.choices(cat[artist], [1 / (i + 1) for i in range(len(cat[artist]))])[0]
            r = rng.random()
            if r < .03:
                ms = 0
            elif r < .27:
                ms = rng.randint(1_000, 29_000)       # skip
            else:
                ms = track.seconds * 1000 if rng.random() < .8 else rng.randint(30_000, track.seconds * 1000)
            # The record's timestamp is the stream's end, as in a real export.
            end_local = local + timedelta(milliseconds=ms)
            end = end_local.replace(tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)
            offline = rng.random() < .015
            ts = end
            if offline:                                # logged when the phone next synced
                ts = end + timedelta(hours=rng.randint(2, 30))
            rec = _record(ts, ms, country, track, offline=offline, offline_ms=int(end.timestamp() * 1000) if offline else None,
                          skipped=ms < 30_000, rng=rng)
            records.append(rec)
            music_meta.append((end_local, artist, track.name, ms, offline, len(records) - 1))
        day += timedelta(days=1)

    # Music played in the video player goes to Video files (still music: it has a track URI).
    video_idx = set(rng.sample([meta[5] for meta in music_meta if not meta[4]], 250))
    # Exact duplicates, as seen in real exports.
    dup_src = rng.sample(range(len(records)), 40)
    files: dict[str, list] = defaultdict(list)
    for i, rec in enumerate(records):
        kind = "Video" if i in video_idx else "Audio"
        files[(kind, rec["ts"][:4])].append(rec)
    for i in dup_src:
        kind = "Video" if i in video_idx else "Audio"
        files[(kind, records[i]["ts"][:4])].append(dict(records[i]))
    for (kind, year), recs in files.items():
        recs.sort(key=lambda r: r["ts"])
        chunks = [recs[k:k + 12_000] for k in range(0, len(recs), 12_000)] if kind == "Audio" else [recs]
        for j, chunk in enumerate(chunks):
            suffix = "" if j == 0 else f"_{j}"
            (out_dir / f"Streaming_History_{kind}_{year}{suffix}.json").write_text(json.dumps(chunk, indent=1))

    truth = _ground_truth(records, music_meta, dup_src, start, era_starts, comeback, biggest_day, hour_w)
    truth["generator"] = {"seed": seed, "start": start.isoformat(), "months": months, "artists": len(artists),
                          "home_timezone": HOME_TZ, "travel_timezone": TRAVEL_TZ,
                          "travel_days": [d.isoformat() for d in travel]}
    (out_dir.parent / "ground_truth.json").write_text(json.dumps(truth, indent=1))
    return truth


def _record(ts: datetime, ms: int, country: str, track: Track | None, episode=None, offline=False,
            offline_ms=None, skipped=False, rng: random.Random | None = None) -> dict:
    rec = {
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platform": "ios",
        "ms_played": ms,
        "conn_country": country,
        "ip_addr": "192.0.2.10",  # documentation-only address range (RFC 5737)
        "master_metadata_track_name": track.name if track else None,
        "master_metadata_album_artist_name": track.artist if track else None,
        "master_metadata_album_album_name": track.album if track else None,
        "spotify_track_uri": track.uri if track else None,
        "episode_name": f"Episode {ts.strftime('%Y%m%d')}" if episode else None,
        "episode_show_name": episode[0] if episode else None,
        "spotify_episode_uri": episode[1] if episode else None,
        "audiobook_title": None, "audiobook_uri": None, "audiobook_chapter_uri": None, "audiobook_chapter_title": None,
        "reason_start": "trackdone" if not skipped else "fwdbtn",
        "reason_end": "fwdbtn" if skipped else "trackdone",
        "shuffle": bool(rng and rng.random() < .4),
        "skipped": skipped,
        "offline": offline,
        "offline_timestamp": offline_ms,
        "incognito_mode": False,
    }
    return rec


def _ground_truth(records, music_meta, dup_src, start, era_starts, comeback, biggest_day, hour_w) -> dict:
    """Answers derived from the generated events with plain Python (no analysis code)."""
    n_music = sum(1 for r in records if r["spotify_track_uri"])
    n_episodes = sum(1 for r in records if r["spotify_episode_uri"])
    music_ms = sum(r["ms_played"] for r in records if r["spotify_track_uri"])
    by_artist = Counter()
    for _local, artist, _t, ms, _off, _i in music_meta:
        by_artist[artist] += ms
    top_artist = sorted(by_artist.items(), key=lambda kv: (-kv[1], kv[0].casefold()))[0][0]
    # Longest streak of consecutive local days with a play (>= 30 s), online records only.
    days_by_artist = defaultdict(set)
    for local, artist, _t, ms, offline, _i in music_meta:
        if ms >= 30_000 and not offline:
            days_by_artist[artist].add(local.date())
    best = (0, "")
    for artist, days in days_by_artist.items():
        run = longest = 0
        prev = None
        for d in sorted(days):
            run = run + 1 if prev and (d - prev).days == 1 else 1
            longest = max(longest, run)
            prev = d
        if (longest, artist) > best:
            best = (longest, artist)
    month = lambda k: _month_add(start, k).strftime("%Y-%m")
    peak = max(range(8), key=lambda b: sum(hour_w[3 * b:3 * b + 3]))
    travel_records = sum(1 for r in records if r["conn_country"] == "JP") + sum(
        1 for i in dup_src if records[i]["conn_country"] == "JP")
    return {
        "raw_records": len(records) + len(dup_src),
        "travel_records": travel_records,
        "exact_duplicates": len(dup_src),
        "podcast_episodes": n_episodes,
        "music_records": n_music,
        "music_minutes": round(music_ms / 60000, 1),
        "era_boundaries": [month(k) for k in era_starts[1:]],
        "comeback": {"artist": comeback, "silent_from": month(era_starts[1]), "silent_to": month(era_starts[3] - 1),
                     "returns": month(era_starts[3])},
        "biggest_day": biggest_day.isoformat(),
        "peak_window_start_hour": 3 * peak,
        "top_artist": top_artist,
        "longest_streak": {"artist": best[1], "days": best[0]},
    }
