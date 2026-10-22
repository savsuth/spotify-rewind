"""Habits and obsessions: clock splitting, offline exclusion, streaks, weeks, sessions."""
import json
import unittest

import numpy as np
import pandas as pd

from rewind import config, habits

ROOT = config.ROOT


def frame(rows):
    """rows: (local end 'YYYY-MM-DD HH:MM', minutes, artist, track, offline). Local = UTC for fixtures."""
    out = []
    for end, minutes, artist, track, offline in rows:
        local = pd.Timestamp(end)
        out.append({
            "ts_utc": local.tz_localize("UTC"), "local_ts": local, "local_date": local.normalize(),
            "ms_played": int(minutes * 60000), "offline": offline,
            "qualified_play": minutes * 60000 >= config.QUALIFIED_PLAY_MS,
            "artist": artist, "artist_id": "ar_" + artist, "track": track, "track_id": f"tr_{track}_{artist}",
            "track_uri": None, "year": local.year, "month": local.strftime("%Y-%m"),
        })
    return pd.DataFrame(out)


class ClockTests(unittest.TestCase):
    def test_stream_split_across_hour_boundary(self):
        t = habits.timed(frame([("2024-01-01 10:10", 20, "A", "x", False)]))
        hours = habits.hour_minutes(t)
        self.assertAlmostEqual(hours[10], 10.0)
        self.assertAlmostEqual(hours[9], 10.0)
        self.assertAlmostEqual(hours.sum(), 20.0)

    def test_stream_across_midnight_goes_to_hour_23(self):
        t = habits.timed(frame([("2024-01-02 00:05", 15, "A", "x", False)]))
        hours = habits.hour_minutes(t)
        self.assertAlmostEqual(hours[0], 5.0)
        self.assertAlmostEqual(hours[23], 10.0)

    def test_offline_and_zero_ms_are_not_timed(self):
        f = frame([("2024-01-01 10:00", 3, "A", "x", True), ("2024-01-01 11:00", 0, "A", "x", False),
                   ("2024-01-01 12:00", 3, "A", "x", False)])
        self.assertEqual(len(habits.timed(f)), 1)

    def test_bins_and_dayparts_sum_to_one(self):
        f = frame([("2024-01-01 01:00", 30, "A", "x", False), ("2024-01-01 20:00", 30, "A", "y", False)])
        c = habits.clock(habits.timed(f), pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-07"))
        self.assertAlmostEqual(sum(b["share"] for b in c["bins"]), 1.0, places=3)
        self.assertAlmostEqual(sum(c["dayparts"].values()), 1.0, places=3)
        self.assertEqual(c["peak_hour"], 0)  # tie between 00 and 19 goes to the earliest hour

    def test_weekday_average_divides_by_occurrences(self):
        # Two Mondays in range (Jan 1 and Jan 8, 2024), music on one of them only.
        f = frame([("2024-01-01 12:00", 60, "A", "x", False)])
        c = habits.clock(habits.timed(f), pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-08"))
        self.assertAlmostEqual(c["weekday_minutes_per_day"]["Monday"], 30.0)


class ObsessionTests(unittest.TestCase):
    def test_artist_streak_counts_consecutive_days_only(self):
        f = frame([(f"2024-03-0{d} 12:00", 3, "A", "x", False) for d in (1, 2, 3, 6)]
                  + [("2024-03-04 12:00", 3, "B", "y", False)])
        s = habits.artist_streaks(habits.timed(f))
        self.assertEqual(s[0]["name"], "A")
        self.assertEqual((s[0]["days"], s[0]["start"], s[0]["end"]), (3, "2024-03-01", "2024-03-03"))
        self.assertEqual(len(s), 1)  # B has a single day, which is not a streak

    def test_short_plays_do_not_extend_a_streak(self):
        f = frame([("2024-03-01 12:00", 3, "A", "x", False), ("2024-03-02 12:00", 0.2, "A", "x", False)])
        self.assertEqual(habits.artist_streaks(habits.timed(f)), [])

    def test_repeat_week_uses_monday_to_sunday(self):
        # Sun 2024-03-10 belongs to the week of Mon 2024-03-04; Mon 2024-03-11 starts a new week.
        rows = [("2024-03-10 12:00", 3, "A", "x", False)] * 2 + [("2024-03-11 12:00", 3, "A", "x", False)] * 3
        r = habits.repeat_week(habits.timed(frame(rows)))
        self.assertEqual((r["week_start"], r["plays"]), ("2024-03-11", 3))

    def test_sessions_split_on_gap_over_30_minutes(self):
        rows = [("2024-05-01 10:00", 4, "A", "x", False), ("2024-05-01 10:04", 4, "A", "x", False),
                ("2024-05-01 11:00", 4, "B", "y", False)]  # 52-minute gap before the third
        s = habits.sessions(habits.timed(frame(rows)))
        self.assertEqual(s["sessions"], 2)
        self.assertAlmostEqual(s["longest"]["minutes"], 8.0)
        self.assertEqual(s["longest_artist_run"]["plays"], 2)

    def test_biggest_day_ties_go_to_earliest_date(self):
        f = frame([("2024-01-02 12:00", 10, "A", "x", False), ("2024-01-01 12:00", 10, "B", "y", False)])
        self.assertEqual(habits.biggest_day(habits.timed(f))["date"], "2024-01-01")


@unittest.skipUnless(config.EXPORT_DIR.exists() and (config.WORK_DIR / "metrics.json").exists(),
                     "needs the personal export and a full `python3 -m rewind build`")
class RealDataAgreementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hab = json.loads((ROOT / "work/habits.json").read_text())
        cls.stories = json.loads((ROOT / "outputs/stories.json").read_text())
        cls.specs = json.loads((ROOT / "work/chart_specs.json").read_text())

    def scene(self, chapter, kind):
        ch = next(c for c in self.stories["chapters"] if c["id"] == chapter)
        return next(s for s in ch["scenes"] if s["type"] == kind)

    def test_timed_minutes_reconcile_with_offline_exclusion(self):
        audit = json.loads((ROOT / "outputs/data_audit.json").read_text())
        o = self.hab["overall"]
        self.assertAlmostEqual(o["timed_minutes"] + o["excluded_offline_minutes"], audit["music_minutes"], delta=0.2)

    def test_clock_scene_and_chart_match_analysis(self):
        for key, chapter in [("all", "all")] + [(y, y) for y in self.hab["years"]]:
            c = self.hab["overall"]["clock"] if key == "all" else self.hab["years"][key]["clock"]
            s = self.scene(chapter, "clock")
            self.assertEqual(s["metrics"]["peak_hour"], c["peak_hour"])
            spec = self.specs[f"clock-{key}"]
            self.assertEqual([x["value"] for x in spec["categories"]], [round(b["share"] * 100, 1) for b in c["bins"]])
            self.assertEqual(spec["focal"], c["peak_bin"])

    def test_obsession_scenes_match_analysis(self):
        o = self.hab["overall"]
        self.assertEqual(self.scene("all", "biggest_day")["metrics"]["date"], o["biggest_day"]["date"])
        self.assertEqual(self.scene("all", "streak")["metrics"]["days"], o["artist_streaks"][0]["days"])
        self.assertEqual(self.scene("all", "repeat")["metrics"]["plays"], o["repeat_week"]["plays"])
        self.assertEqual(self.scene("all", "session")["metrics"]["minutes"], o["sessions"]["longest"]["minutes"])

    def test_streak_is_recomputed_independently(self):
        from rewind import ingest
        rec, _ = ingest.clean(ingest.load_export())
        mus = rec[rec["is_music"] & rec["qualified_play"] & ~rec["offline"].map(lambda v: v is True)]
        top = self.hab["overall"]["artist_streaks"][0]
        days = sorted(set(mus.loc[mus["artist_id"] == top["id"], "local_date"].dt.date))
        best = run = 1
        for a, b in zip(days, days[1:]):
            run = run + 1 if (b - a).days == 1 else 1
            best = max(best, run)
        self.assertEqual(best, top["days"])



class DateRangeWordingTests(unittest.TestCase):
    def test_cross_year_ranges_keep_both_years(self):
        from rewind.stories import date_range
        self.assertEqual(date_range("2022-11-01", "2023-06-01"), "1 Nov 2022 to 1 Jun 2023")
        self.assertEqual(date_range("2022-10-22", "2022-12-30"), "22 Oct to 30 Dec 2022")


if __name__ == "__main__":
    unittest.main()
