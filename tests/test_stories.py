"""Trace story claims to metrics, era evidence and lifecycle observations."""
from collections import Counter
import json
import unittest

from rewind import config, stories


def load(path):
    return json.loads((config.ROOT / path).read_text())


@unittest.skipUnless(config.EXPORT_DIR.exists() and (config.WORK_DIR / "metrics.json").exists(),
                     "needs the personal export and a full `python3 -m rewind build`")
class StoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metrics = load('work/metrics.json')
        cls.chapters = load('outputs/stories.json')['chapters']
        cls.eras = load('outputs/era_validation.json')
        cls.lifecycles = load('work/lifecycles.json')

    def test_chapter_totals_rankings_and_headlines(self):
        for chapter in self.chapters:
            ch = chapter['id']
            summary = self.metrics['overall'] if ch == 'all' else self.metrics['years'][ch]
            scenes = {s['type']: s for s in chapter['scenes']}
            with self.subTest(chapter=ch):
                self.assertEqual(scenes['opening']['metrics']['days'], summary['coverage']['days'])
                self.assertEqual(scenes['minutes']['metrics']['minutes'], summary['minutes'])
                self.assertEqual(scenes['minutes']['metrics']['active_days'], summary['active_days'])
                self.assertEqual(scenes['minutes']['headline'], f"{round(summary['minutes']):,} minutes")
                self.assertIn(f"{summary['active_days']:,} active days", scenes['minutes']['body'])
                self.assertIn(f"{summary['minutes_per_covered_day']:,.1f} minutes per covered day", scenes['minutes']['body'])
                for actual, expected in zip(scenes['top']['data']['artists'], summary['top_artists'][:5], strict=True):
                    for key in ['id', 'name', 'minutes', 'plays']:
                        self.assertEqual(actual[key], expected[key])
                answer = summary['top_tracks'][0]
                self.assertEqual(scenes['quiz']['metrics']['answer_id'], answer['id'])
                self.assertEqual(scenes['quiz']['metrics']['minutes'], answer['minutes'])
                self.assertEqual(scenes['quiz']['metrics']['plays'], answer['plays'])
                self.assertEqual(scenes['quiz']['data']['answer_detail']['name'], answer['name'])
                months = [m for m in self.metrics['months'] if ch == 'all' or m['month'].startswith(ch)]
                leaders = Counter(m['top_artists'][0]['id'] for m in months if m['top_artists'])
                self.assertEqual(scenes['ranking']['metrics']['distinct_leaders'], len(leaders))
                self.assertEqual(scenes['ranking']['metrics']['most_months'], max(leaders.values()))
                for actual, expected in zip(scenes['ranking']['data']['months'], months, strict=True):
                    self.assertEqual(actual['month'], expected['month'])
                    self.assertEqual(actual['minutes'], expected['minutes'])
                    self.assertEqual(actual['partial'], expected['partial'])
                    self.assertEqual(actual['top'][0]['id'], expected['top_artists'][0]['id'])
                summary_lines = {r['label']: r['value'] for r in scenes['summary']['data']['lines']}
                self.assertEqual(summary_lines['Minutes'], f"{round(summary['minutes']):,}")
                self.assertEqual(summary_lines['Top artist'], summary['top_artists'][0]['name'])
                self.assertEqual(summary_lines['Top song'], answer['name'])

    def test_all_year_evidence_matches_saved_analysis(self):
        scenes = {s['type']: s for s in self.chapters[0]['scenes']}
        self.assertEqual(scenes['eras']['metrics']['eras'], len(self.eras['eras']))
        strongest = max((b for b in self.eras['boundary_explanations'] if b['stability'] >= .8),
                        key=lambda b: b['hellinger'])
        self.assertEqual(scenes['transition']['metrics']['boundary_month'], strongest['boundary_month'])
        self.assertEqual(scenes['transition']['metrics']['hellinger'], strongest['hellinger'])
        self.assertEqual(scenes['transition']['metrics']['stability'], strongest['stability'])
        self.assertIn(stories.month_label(strongest['boundary_month']), scenes['transition']['headline'])
        comeback = scenes['comeback']['metrics']
        artist = next(a for a in self.lifecycles if a['id'] == comeback['artist_id'])
        self.assertIn({k: v for k, v in comeback.items() if k != 'artist_id'}, artist['comebacks'])
        self.assertIn(f"{comeback['gap_months']} months under", scenes['comeback']['body'])
        self.assertIn(f"{round(comeback['minutes_3m_after_return']):,} minutes", scenes['comeback']['body'])
        sustained = scenes['sustained']['metrics']
        artist = next(a for a in self.lifecycles if scenes['sustained']['headline'] == f"{a['name']} became a constant")
        self.assertTrue(artist['sustained'])
        self.assertFalse(artist['left_censored'])
        for key, value in sustained.items():
            self.assertEqual(value, artist[key])
        stayed = scenes['stayed']
        artist = next(a for a in self.lifecycles if stayed['headline'].startswith(a['name'] + ': top '))
        self.assertEqual(stayed['metrics']['years_in_top'], artist['years_in_top'])
        for year, rank in stayed['data']['ranks'].items():
            row = next(a for a in self.metrics['years'][year]['top_artists'] if a['id'] == artist['id'])
            self.assertEqual(rank, row['rank'])
        comparison = load('work/early_late.json')
        for key in ['early', 'late', 'top10_overlap']:
            self.assertEqual(scenes['early_late']['metrics'][key], comparison[key])

    def test_yearly_era_and_arrival_claims(self):
        for chapter in self.chapters[1:]:
            year = chapter['id']
            scenes = {s['type']: s for s in chapter['scenes']}
            expected = [e['id'] for e in self.eras['eras'] if e['start_month'][:4] <= year <= e['end_month'][:4]]
            self.assertEqual(scenes['year_eras']['metrics']['eras'], expected)
            if 'arrival' in scenes:
                arrival = scenes['arrival']
                artist = next(a for a in self.lifecycles if arrival['headline'] == f"{a['name']} broke through")
                self.assertFalse(artist['left_censored'])
                self.assertEqual(arrival['metrics']['first_observed'], artist['first_observed'])
                self.assertEqual(arrival['metrics']['first_engaged'], artist['first_engaged'])
                self.assertTrue(artist['first_engaged'].startswith(year))

    def test_unsupported_stories_are_omitted(self):
        self.assertIsNone(stories.quiz_scene('test', {'top_tracks': []}))
        self.assertIsNone(stories.ranking_scene('test', []))
        self.assertIsNone(stories.transition_scene('test', None, None))
        self.assertIsNone(stories.eras_scene('test', [], [], None))
        self.assertIsNone(stories.sustained_scene('test', None, None))
        self.assertIsNone(stories.comeback_scene('test', None, None))
        self.assertIsNone(stories.stayed_scene('test', None, 0, None))
        self.assertIsNone(stories.arrival_scene('test', 2024, [], {}))
        self.assertIsNone(stories.year_eras_scene('test', 2024, []))
