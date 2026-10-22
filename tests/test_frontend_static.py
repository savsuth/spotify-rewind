"""Static design contracts that must hold for every scene palette and the page shell."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / 'web/styles.css').read_text()


def luminance(colour):
    channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
    return sum(a * b for a, b in zip(linear, [.2126, .7152, .0722]))


def contrast(a, b):
    light, dark = sorted([luminance(a), luminance(b)], reverse=True)
    return (light + .05) / (dark + .05)


def palettes():
    found = {}
    for number, body in re.findall(r'\.palette-(\d)\s*\{([^}]*)\}', CSS):
        found[number] = dict(re.findall(r'--(bg2|bg|fg|accent):\s*(#[0-9a-f]{6})', body))
    return found


class FrontendStaticTests(unittest.TestCase):
    def test_all_seven_palettes_meet_text_contrast(self):
        css = CSS
        pal = re.findall(r'\.palette-(\d)\s*\{\s*--bg:\s*(#[0-9a-f]{6});\s*--fg:\s*(#[0-9a-f]{6});', css)
        self.assertEqual({p[0] for p in pal}, set('0123456'))
        for palette, background, foreground in pal:
            with self.subTest(palette=palette):
                self.assertGreaterEqual(contrast(background, foreground), 4.5)

    def test_text_stays_readable_across_the_whole_gradient(self):
        # Scene backgrounds run from --bg to --bg2; body text must clear 4.5:1 at both ends.
        for number, p in palettes().items():
            with self.subTest(palette=number):
                self.assertGreaterEqual(contrast(p['fg'], p['bg']), 4.5)
                self.assertGreaterEqual(contrast(p['fg'], p['bg2']), 4.5)

    def test_accent_display_type_meets_large_text_contrast(self):
        # Accent colours set the oversized hero type; large text needs 3:1.
        for number, p in palettes().items():
            with self.subTest(palette=number):
                self.assertGreaterEqual(contrast(p['accent'], p['bg']), 3.0)
                self.assertGreaterEqual(contrast(p['accent'], p['bg2']), 3.0)

    def test_hidden_attribute_always_hides(self):
        # Component display rules (the quiz reveal is display: grid) must not show
        # [hidden] content; without this rule the quiz answer showed before answering.
        self.assertRegex(CSS, r'\[hidden\]\s*\{\s*display:\s*none\s*!important;\s*\}')

    def test_reduced_motion_disables_animation(self):
        self.assertIn('@media (prefers-reduced-motion: reduce)', CSS)
        self.assertRegex(CSS, r'\.reduced \*, \.reduced \*::before, \.reduced \*::after \{ animation: none !important; transition: none !important; \}')


if __name__ == '__main__':
    unittest.main()
