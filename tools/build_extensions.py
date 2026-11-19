"""Produce a Firefox MV3 event-page variant from the shared extension sources."""
import json
from pathlib import Path
import shutil
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from focuslock.extension_setup import FIREFOX_ID


def main():
    destination = ROOT / 'extension-firefox'
    shutil.copytree(ROOT / 'extension', destination, dirs_exist_ok=True)
    manifest = json.loads((destination / 'manifest.json').read_text(encoding='utf-8'))
    manifest.pop('key', None)
    manifest.pop('minimum_chrome_version', None)
    manifest['background'] = {'scripts': ['policy.js', 'background.js']}
    manifest['browser_specific_settings'] = {'gecko': {
        'id': FIREFOX_ID, 'strict_min_version': '140.0',
        'data_collection_permissions': {'required': ['none']}}}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('Chromium/Yandex and Firefox extension folders are ready.')


if __name__ == '__main__':
    main()
