"""Cached Windows executable icons with offline, deterministic fallbacks."""
import hashlib
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageTk


def _executable_icon(path, size, background):
    if sys.platform != 'win32' or not Path(path).is_file():
        return None
    import ctypes
    from ctypes import wintypes
    import win32gui

    class BitmapHeader(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('width', wintypes.LONG), ('height', wintypes.LONG),
                    ('planes', wintypes.WORD), ('bits', wintypes.WORD), ('compression', wintypes.DWORD),
                    ('image_size', wintypes.DWORD), ('x_pixels', wintypes.LONG), ('y_pixels', wintypes.LONG),
                    ('colors', wintypes.DWORD), ('important', wintypes.DWORD)]

    class BitmapInfo(ctypes.Structure):
        _fields_ = [('header', BitmapHeader), ('colors', wintypes.DWORD * 1)]

    user = ctypes.WinDLL('user32', use_last_error=True)
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    user.GetDC.argtypes, user.GetDC.restype = [wintypes.HWND], wintypes.HDC
    user.ReleaseDC.argtypes, user.ReleaseDC.restype = [wintypes.HWND, wintypes.HDC], ctypes.c_int
    user.DrawIconEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON,
                               ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.HBRUSH, wintypes.UINT]
    user.DrawIconEx.restype = wintypes.BOOL
    gdi.CreateCompatibleDC.argtypes, gdi.CreateCompatibleDC.restype = [wintypes.HDC], wintypes.HDC
    gdi.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BitmapInfo), wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi.CreateDIBSection.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes, gdi.SelectObject.restype = [wintypes.HDC, wintypes.HANDLE], wintypes.HANDLE
    gdi.DeleteObject.argtypes, gdi.DeleteObject.restype = [wintypes.HANDLE], wintypes.BOOL
    gdi.DeleteDC.argtypes, gdi.DeleteDC.restype = [wintypes.HDC], wintypes.BOOL
    large, small = win32gui.ExtractIconEx(path, 0)
    screen = target = bitmap = previous = None
    try:
        icons = large or small
        if not icons:
            return None
        screen = user.GetDC(None)
        target = gdi.CreateCompatibleDC(screen)
        info = BitmapInfo()
        info.header.size = ctypes.sizeof(BitmapHeader)
        info.header.width, info.header.height = size, -size  # Top-down, 32-bit DIB.
        info.header.planes, info.header.bits = 1, 32
        bits = ctypes.c_void_p()
        bitmap = gdi.CreateDIBSection(screen, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
        if not screen or not target or not bitmap or not bits.value:
            raise OSError('Cannot allocate executable icon bitmap.')
        previous = gdi.SelectObject(target, bitmap)
        if not previous or previous == ctypes.c_void_p(-1).value:
            previous = None
            raise OSError('Cannot select executable icon bitmap.')
        rgb = bytes(int(background[i:i + 2], 16) for i in (5, 3, 1)) + b'\xff'
        ctypes.memmove(bits, rgb * (size * size), size * size * 4)
        if not user.DrawIconEx(target, 0, 0, icons[0], size, size, 0, None, 3):
            raise OSError('Cannot draw executable icon.')
        return Image.frombytes('RGB', (size, size), ctypes.string_at(bits, size * size * 4), 'raw', 'BGRX').convert('RGBA')
    finally:
        if target and previous:
            gdi.SelectObject(target, previous)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if target:
            gdi.DeleteDC(target)
        if screen:
            user.ReleaseDC(None, screen)
        for icon in large + small:
            win32gui.DestroyIcon(icon)


class AppIcons:
    def __init__(self, root):
        self.root, self.cache = root, {}

    def get(self, key, title, website=False):
        size = max(24, round(36 * self.root.focuslock_scale))
        background = self.root.staylocked_palette['card']
        cache_key = (key, website, size, background)
        if cache_key not in self.cache:
            image = None
            if not website:
                try:
                    image = _executable_icon(key, size, background)
                except (ImportError, OSError, RuntimeError):
                    pass
                except Exception:
                    # Broken or icon-less third-party executables must remain usable.
                    image = None
            if image is None:
                n = size * 3
                image = Image.new('RGBA', (n, n))
                draw = ImageDraw.Draw(image)
                colors = ('#647fd0', '#8f72ca', '#398f9d', '#a16687', '#698453')
                color = colors[hashlib.sha256(key.casefold().encode()).digest()[0] % len(colors)]
                draw.rounded_rectangle((0, 0, n - 1, n - 1), radius=n * .29, fill=color)
                if website:
                    box = (n * .24, n * .24, n * .76, n * .76)
                    draw.ellipse(box, outline='#ffffff', width=max(2, size // 6))
                    draw.ellipse((n * .39, n * .24, n * .61, n * .76), outline='#ffffff', width=max(2, size // 8))
                    draw.line((n * .24, n * .5, n * .76, n * .5), fill='#ffffff', width=max(2, size // 8))
                else:
                    face = ImageFont.load_default(size=round(n * .48))
                    draw.text((n / 2, n * .49), (title[:1] or '?').upper(), font=face, fill='#ffffff', anchor='mm')
                image = image.resize((size, size), Image.Resampling.LANCZOS)
            self.cache[cache_key] = ImageTk.PhotoImage(image, master=self.root)
        return self.cache[cache_key]
