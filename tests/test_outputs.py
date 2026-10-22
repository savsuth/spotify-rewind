"""Recount raw data independently; verify generated deliverables and privacy."""
from collections import Counter, defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
import re
import unittest
from zoneinfo import ZoneInfo

import pandas as pd

from rewind import config, ingest, metrics

ROOT = config.ROOT


def read_json(path):
    return json.loads((ROOT / path).read_text())


@unittest.skipUnless(config.EXPORT_DIR.exists() and (config.WORK_DIR / "metrics.json").exists(),
                     "needs the personal export and a full `python3 -m rewind build`")
class OutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = read_json('outputs/data_audit.json')
        cls.metrics = read_json('work/metrics.json')
        cls.stories = read_json('outputs/stories.json')
        cls.by_year = defaultdict(int)
        cls.artists = defaultdict(lambda: [0, 0])
        cls.tracks = defaultdict(lambda: [0, 0])
        cls.files = {}
        seen = set()
        buckets = Counter()
        # Deliberately do not call ingest.clean, metrics.rank_table or stable_id:
        # this is a separate implementation of the declared accounting rules.
        zones = {'US': 'America/New_York', 'IN': 'Asia/Kolkata', 'JP': 'Asia/Tokyo',
                 'BT': 'Asia/Thimphu', 'AE': 'Asia/Dubai', 'QA': 'Asia/Qatar'}
        for path in sorted(config.EXPORT_DIR.glob('Streaming_History_*.json')):
            rows = json.loads(path.read_text())
            cls.files[path.name] = len(rows)
            for row in rows:
                key = json.dumps(row, sort_keys=True)
                if key in seen:
                    buckets['exact_duplicate'] += 1
                    continue
                seen.add(key)
                if not row.get('spotify_track_uri'):
                    buckets['non_music'] += 1
                    continue
                ms = row.get('ms_played')
                try:
                    valid = (isinstance(ms, (int, float)) and math.isfinite(ms) and
                             0 <= ms <= 3600000 and row.get('master_metadata_album_artist_name') is not None
                             and row.get('master_metadata_track_name') is not None)
                    ts = datetime.fromisoformat(row['ts'].replace('Z', '+00:00'))
                except (ValueError, TypeError, KeyError):
                    valid = False
                if not valid:
                    buckets['track_excluded_invalid'] += 1
                    continue
                buckets['music'] += 1
                year = str(ts.astimezone(ZoneInfo(zones.get(row.get('conn_country'), 'UTC'))).year)
                cls.by_year[year] += ms
                artist = row['master_metadata_album_artist_name'].strip().casefold()
                track = (row['master_metadata_track_name'].strip().casefold(), artist)
                for dest, entity in [(cls.artists, artist), (cls.tracks, track)]:
                    dest[entity][0] += ms
                    dest[entity][1] += ms >= 30000
        cls.buckets = buckets

    def test_reconciliation_matches_raw_files(self):
        self.assertEqual(self.audit['records_by_file'], self.files)
        self.assertEqual(sum(self.files.values()), self.audit['raw_records'])
        for key in ['music', 'exact_duplicate', 'non_music', 'track_excluded_invalid']:
            self.assertEqual(self.buckets[key], self.audit['reconciliation'][key])
        self.assertEqual(sum(self.buckets.values()), self.audit['raw_records'])

    def test_independent_yearly_minutes_and_rates(self):
        for year, milliseconds in self.by_year.items():
            with self.subTest(year=year):
                summary = self.metrics['years'][year]
                self.assertEqual(round(milliseconds / 60000, 1), summary['minutes'])
                self.assertEqual(round(milliseconds / 60000 / summary['coverage']['days'], 1),
                                 summary['minutes_per_covered_day'])
        self.assertEqual(round(sum(self.by_year.values()) / 60000, 1), self.metrics['overall']['minutes'])
        self.assertEqual(self.metrics['years']['2021']['coverage']['days'], 213)
        self.assertEqual(self.metrics['years']['2026']['coverage']['days'], 287)
        self.assertTrue(self.metrics['years']['2021']['coverage']['partial'])
        self.assertTrue(self.metrics['years']['2026']['coverage']['partial'])
        self.assertFalse(self.metrics['years']['2024']['coverage']['partial'])

    def test_independent_top_artist_and_song(self):
        for rows, field in [(self.artists, 'top_artists'), (self.tracks, 'top_tracks')]:
            best = min(rows, key=lambda k: (-rows[k][0], -rows[k][1], k))
            actual = self.metrics['overall'][field][0]
            name = actual['name'].strip().casefold()
            identity = (name, actual['artist'].strip().casefold()) if field == 'top_tracks' else name
            self.assertEqual(best, identity)
            self.assertEqual(round(rows[best][0] / 60000, 1), actual['minutes'])
            self.assertEqual(rows[best][1], actual['plays'])

    def test_fresh_metrics_match_saved_outputs(self):
        records, audit = ingest.clean(ingest.load_export())
        self.assertEqual(metrics.build(records), self.metrics)
        self.assertEqual(ingest.coerce_audit(audit), {k: v for k, v in self.audit.items() if k != 'technical_log'})

    def test_browser_story_copy_and_identifiers(self):
        self.assertEqual((ROOT / 'outputs/stories.json').read_bytes(),
                         (ROOT / 'web/data/stories.json').read_bytes())
        scenes = [s for c in self.stories['chapters'] for s in c['scenes']]
        self.assertEqual(len({s['id'] for s in scenes}), len(scenes))
        for scene in scenes:
            self.assertTrue(scene['evidence'], scene['id'])
            self.assertTrue(scene['method'], scene['id'])
            if scene['chart']:
                self.assertTrue((ROOT / 'web/data/charts' / (scene['chart'] + '.svg')).is_file())

    def test_early_late_uses_twelve_complete_months(self):
        early = read_json('work/early_late.json')
        complete = [m for m in self.metrics['months'] if not m['partial'] and not m['low_activity']]
        for key, months in [('early', complete[:12]), ('late', complete[-12:])]:
            self.assertEqual(early[key]['start_month'], months[0]['month'])
            self.assertEqual(early[key]['end_month'], months[-1]['month'])
            self.assertEqual(early[key]['days'], sum(m['days_in_month'] for m in months))
        self.assertEqual(early['window_months'], 12)
        self.assertLess(early['early']['end_month'], early['late']['start_month'])

    def test_deliverables_do_not_export_private_fields_or_ip_addresses(self):
        forbidden = re.compile(r'\b(?:' + '|'.join(config.PRIVATE_FIELDS) + r')\b', re.I)
        ipv4 = re.compile(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])')
        ipv6 = re.compile(r'(?<![\w:])(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}(?![\w:])', re.I)
        for directory in ['web/data', 'outputs']:
            for path in (ROOT / directory).rglob('*'):
                if path.suffix not in {'.json', '.md', '.html', '.svg'}:
                    continue
                text = path.read_text()
                with self.subTest(path=path.relative_to(ROOT)):
                    self.assertIsNone(forbidden.search(text), 'Private field name in deliverable')
                    self.assertIsNone(ipv4.search(text), 'IPv4-like value in deliverable')
                    self.assertIsNone(ipv6.search(text), 'IPv6-like value in deliverable')
