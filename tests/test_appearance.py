"""Appearance migrations and writes must never alter the session configuration."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from focuslock.preferences import (DEFAULT_APPEARANCE, load_appearance, load_theme,
                                   preference_path, save_appearance, save_theme)
from focuslock.theme import ACCENTS, PALETTES, contrasting_text, appearance_palette, contrast_ratio


class AppearanceTests(unittest.TestCase):
    def test_old_theme_only_file_migrates_without_losing_theme(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            preference_path(config).write_text('{"theme":"Ocean"}')
            self.assertEqual(load_appearance(config), {**DEFAULT_APPEARANCE, 'theme': 'Ocean'})
            save_appearance({'density': 'Compact', 'accent': 'Rose'}, config)
            save_theme('Light', config)
            self.assertEqual(load_appearance(config), dict(theme='Light', accent='Rose', density='Compact', timer_style='Ring'))
            self.assertEqual(load_theme(config), 'Light')

    def test_bad_values_fall_back_individually(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            path = preference_path(config)
            for contents in ('null', '[]', '{bad json', '{"theme": [], "accent": 17}',
                             '{"theme":"Midnight", "timer_style":"command.exe"}'):
                path.write_text(contents)
                self.assertEqual(load_appearance(config), DEFAULT_APPEARANCE)
            path.write_text('{"theme":"Violet", "density":"Invalid"}')
            self.assertEqual(load_appearance(config), {**DEFAULT_APPEARANCE, 'theme': 'Violet'})

    def test_cosmetics_leave_config_and_invalid_writes_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            original = b'{"schema_version":3,"applications":[],"websites":["youtube.com"]}'
            config.write_bytes(original)
            save_appearance({'theme': 'Light', 'accent': 'Blue', 'timer_style': 'Minimal'}, config)
            before = preference_path(config).read_bytes()
            for invalid in ({'theme': 'unknown'}, {'accent': '#fff'}, {'duration': 5}, {'density': None}, []):
                with self.assertRaises(ValueError):
                    save_appearance(invalid, config)
                self.assertEqual(preference_path(config).read_bytes(), before)
                self.assertEqual(config.read_bytes(), original)
            with patch('focuslock.preferences.write_json', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    save_appearance({'theme': 'Ocean'}, config)
            self.assertEqual(preference_path(config).read_bytes(), before)
            self.assertEqual(config.read_bytes(), original)

    def test_button_text_contrast_meets_wcag_aa(self):
        def luminance(color):
            values = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
            return sum(w * (v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4)
                       for w, v in zip((.2126, .7152, .0722), values))
        for accent in ACCENTS.values():
            foreground = contrasting_text(accent)
            high, low = sorted((luminance(accent), luminance(foreground)), reverse=True)
            self.assertGreaterEqual((high + .05) / (low + .05), 4.5)
        for theme in PALETTES:
            for accent in ACCENTS:
                colors = appearance_palette(theme, {'accent': accent})
                self.assertGreaterEqual(contrast_ratio(colors['accent_ink'], colors['selected']), 4.5)
                self.assertGreaterEqual(contrast_ratio(colors['ring'], colors['card']), 3)
        for colors in PALETTES.values():
            high, low = sorted((luminance(colors['accent']), luminance(colors['accent_text'])), reverse=True)
            self.assertGreaterEqual((high + .05) / (low + .05), 4.5)


if __name__ == '__main__':
    unittest.main()
