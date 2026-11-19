"""Rebuild the original StayLocked icon; no network or external assets required."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from focuslock.branding import make_icon


def main():
    assets = ROOT / 'assets'
    assets.mkdir(exist_ok=True)
    for size in (16, 32, 48, 64, 128, 256, 512):
        make_icon(size).save(assets / f'staylocked-{size}.png')
    make_icon(256).save(assets / 'staylocked.ico', sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    (assets / 'staylocked.svg').write_text('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 768 768">
<defs><linearGradient id="bg" x2="0" y2="1"><stop stop-color="#9986ff"/><stop offset="1" stop-color="#6244d3"/></linearGradient></defs>
<rect x="24" y="24" width="720" height="720" rx="180" fill="url(#bg)"/>
<rect x="272.5" y="183.5" width="223" height="265" rx="111.5" fill="none" stroke="#f9f7ff" stroke-width="51"/>
<rect x="184" y="329" width="400" height="291" rx="70" fill="#f9f7ff"/>
<path d="M451 408H325L311 421V461L453 490V530L438 544H313" fill="none" stroke="#7960df" stroke-width="31" stroke-linejoin="round"/>
</svg>''', encoding='utf-8')
    target = ROOT / 'extension' / 'icons'
    target.mkdir(exist_ok=True)
    for size in (16, 32, 48, 128):
        (target / f'icon-{size}.png').write_bytes((assets / f'staylocked-{size}.png').read_bytes())
    print('StayLocked icons ready: SVG, PNG, multi-resolution ICO.')


if __name__ == '__main__':
    main()
