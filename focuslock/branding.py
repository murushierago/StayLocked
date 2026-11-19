"""One code-drawn vector mark for the window, tray, EXE and extension."""
from pathlib import Path
import sys

APP_NAME = 'StayLocked'
VERSION = '0.6.1'


def asset_directory():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])) / 'assets'


def make_icon(size=256):
    from PIL import Image, ImageDraw
    n = 768
    image = Image.new('RGBA', (n, n))
    gradient = Image.new('RGBA', (n, n))
    draw = ImageDraw.Draw(gradient)
    for y in range(n):
        t = y / (n - 1)
        color = tuple(round(a * (1-t) + b*t) for a, b in zip((153, 134, 255), (98, 68, 211)))
        draw.line((0, y, n, y), fill=(*color, 255))
    mask = Image.new('L', (n, n))
    ImageDraw.Draw(mask).rounded_rectangle((24, 24, 744, 744), radius=180, fill=255)
    image.paste(gradient, (0, 0), mask)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((247, 158, 521, 474), radius=137, outline='#f9f7ff', width=51)
    draw.rounded_rectangle((184, 329, 584, 620), radius=70, fill='#f9f7ff')
    draw.line([(451, 408), (325, 408), (311, 421), (311, 461),
               (453, 490), (453, 530), (438, 544), (313, 544)],
              fill='#7960df', width=31, joint='curve')
    return image.resize((size, size), Image.Resampling.LANCZOS)


def apply_window_icon(root):
    import tkinter as tk
    path = asset_directory() / 'staylocked-64.png'
    if path.is_file():
        icon = tk.PhotoImage(master=root, file=str(path))
        root.iconphoto(True, icon)
        root.staylocked_window_icon = icon
    if sys.platform == 'win32':
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('StayLocked.Desktop')
            root.iconbitmap(str(asset_directory() / 'staylocked.ico'))
        except (OSError, tk.TclError):
            pass
