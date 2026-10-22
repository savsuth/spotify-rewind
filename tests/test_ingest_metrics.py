"""Cleaning and metric contracts, independent of the personal export."""
import unittest

import pandas as pd

from rewind import config, ingest, metrics


def raw_frame(changes):
    rows = []
    for i, change in enumerate(changes):
        row = dict.fromkeys(ingest.EXPORT_FIELDS)
        row.update(ts='2024-01-01T12:00:00Z', ms_played=60000, conn_country='US',
                   master_metadata_track_name='Song', master_metadata_album_artist_name='Artist',
                   master_metadata_album_album_name='Album', spotify_track_uri='spotify:track:sample',
                   source_file='Streaming_History_Audio_1999_0.json', source_kind='audio', source_row=i)
        row.update(change)
        rows.append(row)
    return pd.DataFrame(rows)


class CleaningTests(unittest.TestCase):
    def test_exact_duplicates_and_offline_batch_are_distinct(self):
        records, audit = ingest.clean(raw_frame([{}, {}, {'ms_played': 90000}]))
        self.assertEqual(audit['reconciliation'], {'music': 2, 'exact_duplicate': 1,
                         'non_music': 0, 'track_excluded_invalid': 0, 'total': 3})
        self.assertEqual(audit['same_timestamp_and_uri_kept'], 1)
        self.assertEqual(records.loc[records.is_music, 'ms_played'].sum(), 150000)

    def test_invalid_records_and_content_types(self):
        records, audit = ingest.clean(raw_frame([
            {}, {'ms_played': -1}, {'ms_played': float('nan')},
            {'master_metadata_album_artist_name': None}, {'master_metadata_track_name': None},
            {'ts': 'invalid'}, {'ms_played': config.MAX_PLAUSIBLE_TRACK_MS + 1},
            {'spotify_track_uri': None, 'spotify_episode_uri': 'spotify:episode:sample'},
            {'spotify_track_uri': None, 'audiobook_uri': 'spotify:audiobook:sample'},
            {'spotify_track_uri': None}, {'ms_played': 0},
        ]))
        self.assertEqual(records.index[records.is_music].tolist(), [0, 10])
        self.assertFalse(records.loc[10, 'qualified_play'])
        self.assertEqual(audit['non_music_records_excluded'], {'audiobook': 1, 'episode': 1, 'unknown': 1})
        self.assertEqual(audit['reconciliation']['total'], 11)
        self.assertEqual(audit['reconciliation']['track_excluded_invalid'], 6)

    def test_timezone_midnight_and_filename_year(self):
        records, _ = ingest.clean(raw_frame([
            {'ts': '2024-01-01T02:00:00Z', 'conn_country': 'US'},
            {'ts': '2023-12-31T20:00:00Z', 'conn_country': 'IN'},
            {'ts': '2024-01-01T02:00:00Z', 'conn_country': 'XX'},
        ]))
        self.assertEqual(records.local_date.dt.strftime('%Y-%m-%d').tolist(),
                         ['2023-12-31', '2024-01-01', '2024-01-01'])
        self.assertEqual(records.year.tolist(), [2023, 2024, 2024])
        self.assertEqual(records.tz.tolist(), ['America/New_York', 'Asia/Kolkata', 'UTC'])

    def test_minutes_and_play_threshold_are_separate(self):
        records, audit = ingest.clean(raw_frame([{'ms_played': x} for x in [0, 29999, 30000, 60000]]))
        self.assertEqual(records.qualified_play.tolist(), [False, False, True, True])
        table = metrics.rank_table(metrics.music_only(records), 'artist_id', ['artist'])
        self.assertAlmostEqual(table.iloc[0]['minutes'], 119999 / 60000)
        self.assertEqual(table.iloc[0]['plays'], 2)
        self.assertEqual(audit['music_ms'], 119999)

    def test_private_columns_do_not_leave_clean(self):
        raw = raw_frame([{}])
        for name in config.PRIVATE_FIELDS:
            raw[name] = 'PRIVATE_SENTINEL' if name != 'conn_country' else 'US'
        records, audit = ingest.clean(raw)
        self.assertFalse(set(config.PRIVATE_FIELDS) & set(records.columns))
        self.assertNotIn('PRIVATE_SENTINEL', records.to_json())
        self.assertNotIn('PRIVATE_SENTINEL', str(audit))

    def test_rank_ties_use_plays_name_then_id(self):
        frame = pd.DataFrame([
            ('z', 'Alpha', 60000, True), ('b', 'alpha', 60000, True),
            ('a', 'Beta', 60000, True), ('c', 'Aardvark', 60000, False),
            ('d', 'Zulu', 120000, False),
        ], columns=['artist_id', 'artist', 'ms_played', 'qualified_play'])
        self.assertEqual(metrics.rank_table(frame, 'artist_id', ['artist']).artist_id.tolist(),
                         ['d', 'b', 'z', 'a', 'c'])

    def test_coverage_includes_silent_days_and_leap_day(self):
        frame = pd.DataFrame({'local_date': pd.to_datetime(['2023-12-31', '2025-01-01'])})
        years = metrics.year_coverage(frame)
        self.assertEqual([years[y]['days'] for y in years], [1, 366, 1])
        self.assertEqual([years[y]['partial'] for y in years], [True, False, True])

    def test_monthly_retains_empty_months(self):
        records, _ = ingest.clean(raw_frame([
            {'ts': '2024-01-01T12:00:00Z'}, {'ts': '2024-03-31T12:00:00Z'}]))
        months = metrics.monthly(metrics.music_only(records))
        self.assertEqual([m['month'] for m in months], ['2024-01', '2024-02', '2024-03'])
        self.assertEqual(months[1]['minutes'], 0)
        self.assertEqual(months[1]['days_covered'], 29)
        self.assertEqual(months[1]['top_artists'], [])
        self.assertTrue(months[1]['low_activity'])
