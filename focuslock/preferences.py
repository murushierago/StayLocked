"""Cosmetic settings are separate from the session and existing block lists."""
import json
from pathlib import Path
from .session import write_json
from .storage import data_directory

THEME_NAMES = ('Midnight', 'Light', 'Violet', 'Ocean')


def preference_path(config_path=None):
    directory = Path(config_path).parent if config_path else data_directory()
    return directory / 'appearance.json'


def load_theme(config_path=None):
    try:
        data = json.loads(preference_path(config_path).read_text(encoding='utf-8'))
        value = data.get('theme') if isinstance(data, dict) else None
        return value if value in THEME_NAMES else 'Midnight'
    except (OSError, ValueError):
        return 'Midnight'


def save_theme(name, config_path=None):
    if name not in THEME_NAMES:
        raise ValueError('Unknown theme.')
    write_json(preference_path(config_path), {'theme': name})
