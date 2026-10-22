"""Chart numbers, source agreement and the installed diagram-design validators."""
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

from rewind import config

ROOT = config.ROOT


def load(path):
    return json.loads((ROOT / path).read_text())


@unittest.skipUnless(config.EXPORT_DIR.exists() and (config.WORK_DIR / "metrics.json").exists(),
                     "needs the personal export and a full `python3 -m rewind build`")
class ChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.specs = load('work/chart_specs.json')
        cls.metrics = load('work/metrics.json')
        cls.stories = {s['type']: s for s in load('outputs/stories.json')['chapters'][0]['scenes']}

    def test_every_chart_value_matches_spec_and_embedded_svg(self):
        for slug, spec in self.specs.items():
            with self.subTest(chart=slug):
                html = (ROOT / 'outputs/charts' / f'{slug}.html').read_text()
                svg = re.search(r'<svg\b.*?</svg>', html, re.S).group(0)
                self.assertEqual(svg + '\n', (ROOT / 'web/data/charts' / f'{slug}.svg').read_text())
                elements = list(ET.fromstring(svg).iter())
                if spec['type'] == 'bar':
                    self.assertEqual([(e.get('data-bar'), float(e.get('data-value'))) for e in elements if e.get('data-bar')],
                                     [(r['label'], r['value']) for r in spec['bars']])
                elif spec['type'] == 'line':
                    self.assertEqual([(e.get('data-point'), float(e.get('data-value'))) for e in elements if e.get('data-point')],
                                     [(r['label'], r['value']) for r in spec['points']])
                elif spec['type'] == 'dumbbell':
                    self.assertEqual([(e.get('data-series'), float(e.get('data-from')), float(e.get('data-to')))
                                      for e in elements if e.get('data-from') is not None],
                                     [(r['name'], r['from'], r['to']) for r in spec['rows']])
                elif spec['type'] == 'gantt':
                    self.assertEqual([(e.get('data-era'), e.get('data-start'), e.get('data-end'))
                                      for e in elements if e.get('data-era')],
                                     [(r['id'], r['start'], r['end']) for r in spec['rows']])
                elif spec['type'] == 'presence':
                    actual = {e.get('data-artist'): {c.get('data-year'): int(c.get('data-rank'))
                              for c in e.iter() if c.get('data-rank')} for e in elements if e.get('data-artist')}
                    self.assertEqual(actual, {r['name']: r['ranks'] for r in spec['rows']})
                elif spec['type'] == 'polar':
                    cats = [e for e in elements if e.get('data-polar-category') is not None]
                    self.assertEqual([(e.get('data-polar-category'), float(e.get('data-polar-value'))) for e in cats],
                                     [(c['label'], c['value']) for c in spec['categories']])
                    self.assertEqual([i for i, e in enumerate(cats) if e.get('data-polar-focal') == 'true'], [spec['focal']])
                else:
                    self.fail(f'Chart type has no numeric contract: {spec["type"]}')

    def test_bar_and_year_lines_trace_to_metrics(self):
        for bar in self.specs['minutes-by-year']['bars']:
            summary = self.metrics['years'][bar['label']]
            self.assertEqual(bar['value'], summary['minutes_per_covered_day'])
            self.assertEqual(bar['total'], summary['minutes'])
            self.assertEqual(bar['partial'], summary['coverage']['partial'])
        for year in self.metrics['years']:
            months = [m for m in self.metrics['months'] if m['month'].startswith(year)]
            expected = [{'label': m['month'], 'value': round(m['minutes'] / m['days_covered'], 1),
                         'partial': m['partial'] or m['low_activity']} for m in months]
            self.assertEqual(self.specs[f'year-{year}']['points'], expected)

    def test_transition_eras_stayed_and_comparison_trace_to_stories(self):
        transition = self.stories['transition']['data']
        source = {r['id']: r for group in transition.values() for r in group}
        for row in self.specs['transition']['rows']:
            self.assertEqual(row['from'], source[row['id']]['share_before'])
            self.assertEqual(row['to'], source[row['id']]['share_after'])
        for row, era in zip(self.specs['eras']['rows'], self.stories['eras']['data']['eras'], strict=True):
            self.assertEqual((row['id'], row['start'], row['end'], row['artist']),
                             (era['id'], era['start_month'], era['end_month'], era['label_artist']))
        source = {r['id']: r for r in self.stories['early_late']['data']['rows']}
        for row in self.specs['early-late']['rows']:
            self.assertEqual((row['from'], row['to']), (source[row['id']]['early'], source[row['id']]['late']))
        focal = next(r for r in self.specs['stayed']['rows'] if r['id'] == self.specs['stayed']['focal'])
        self.assertEqual(focal['ranks'], self.stories['stayed']['data']['ranks'])

    def test_lifecycle_lines_trace_to_clean_records(self):
        # The pickle was created during exploration; use fresh cleaning instead.
        from rewind import ingest
        records, _ = ingest.clean(ingest.load_export())
        music = records[records.is_music]
        comeback_id = self.stories['comeback']['metrics']['artist_id']
        for point in self.specs['comeback']['points']:
            sub = music[(music.artist_id == comeback_id) & (music.month == point['label'])]
            self.assertEqual(point['value'], round(float(sub.ms_played.sum()) / 60000, 1))
        valid = {m['month'] for m in self.metrics['months'] if not m['low_activity']}
        for point in self.specs['sustained']['points']:
            year, half = point['label'].split('-H')
            months = {f'{year}-{m:02d}' for m in range(1 if half == '1' else 7, 7 if half == '1' else 13)} & valid
            sub = music[music.month.isin(months)]
            selected = sub[sub.artist == self.specs['sustained']['series']]
            expected = round(float(selected.ms_played.sum() / sub.ms_played.sum()) * 100, 1)
            self.assertEqual(point['value'], expected)

    def test_all_charts_pass_both_skill_validators(self):
        skill = Path.home() / 'Documents/diagram-design'
        validators = [skill / 'skills/diagram-design/scripts/self_check.py', skill / 'scripts/lint-skin.py']
        for validator in validators:
            self.assertTrue(validator.is_file(), f'Required validator missing: {validator}')
            for slug in self.specs:
                with self.subTest(validator=validator.name, chart=slug):
                    result = subprocess.run([sys.executable, str(validator), str(ROOT / 'outputs/charts' / f'{slug}.html')],
                                            capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
