"""Validated cosmetic preferences, independent of the service and block lists."""
import json
from pathlib import Path
from .session import write_json
from .storage import data_directory

THEME_NAMES = ('Midnight', 'Light', 'Violet', 'Ocean')
ACCENT_NAMES = ('Theme default', 'Lime', 'Violet', 'Mint', 'Blue', 'Rose', 'Amber')
DENSITY_NAMES = ('Comfortable', 'Compact')
TIMER_STYLES = ('Ring', 'Minimal')
DEFAULT_APPEARANCE = dict(theme='Midnight', accent='Theme default',
                          density='Comfortable', timer_style='Ring')
CHOICES = dict(theme=THEME_NAMES, accent=ACCENT_NAMES,
               density=DENSITY_NAMES, timer_style=TIMER_STYLES)


def preference_path(config_path=None):
    directory = Path(config_path).parent if config_path else data_directory()
    return directory / 'appearance.json'


def load_appearance(config_path=None):
    result = dict(DEFAULT_APPEARANCE)
    try:
        data = json.loads(preference_path(config_path).read_text(encoding='utf-8'))
        if isinstance(data, dict):
            for key, choices in CHOICES.items():
                if isinstance(data.get(key), str) and data[key] in choices:
                    result[key] = data[key]
    except (OSError, ValueError):
        pass
    return result


def save_appearance(values, config_path=None):
    if not isinstance(values, dict) or values.keys() - CHOICES.keys():
        raise ValueError('Unknown appearance setting.')
    result = load_appearance(config_path)
    for key, value in values.items():
        if value not in CHOICES[key]:
            raise ValueError('Unknown ' + key.replace('_', ' ') + '.')
        result[key] = value
    write_json(preference_path(config_path), result)
    return result


def load_theme(config_path=None):
    return load_appearance(config_path)['theme']


def save_theme(name, config_path=None):
    # Older callers keep the user's other appearance choices.
    save_appearance({'theme': name}, config_path)
