"""Current-user browser registration and an explicit, removable setup wizard."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from .storage import data_directory

HOST = 'com.focuslock.bridge'
EXTENSION_ID = 'mmcnhdgobmfalggffgjfhbogfoblhheo'
FIREFOX_ID = 'staylocked@staylocked.local'
FIREFOX_REGISTRY = r'Software\Mozilla\NativeMessagingHosts'
REGISTRY_ROOTS = [r'Software\Google\Chrome\NativeMessagingHosts',
                  r'Software\Microsoft\Edge\NativeMessagingHosts',
                  r'Software\Yandex\YandexBrowser\NativeMessagingHosts']


def extension_id(manifest):
    digest = hashlib.sha256(base64.b64decode(manifest['key'], validate=True)).hexdigest()[:32]
    return ''.join(chr(ord('a') + int(char, 16)) for char in digest)


def project_root():
    if getattr(sys, 'frozen', False):
        # ExtensionSetup.exe lives in <app>/setup/.
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parents[1]


def manifest_path(root, firefox=False):
    identity = hashlib.sha256(os.path.normcase(str(root.resolve())).encode('utf-8')).hexdigest()[:16]
    return data_directory() / 'native' / f'host-{identity}{"-firefox" if firefox else ""}.json'


def register(root=None):
    if sys.platform != 'win32':
        raise OSError('Browser setup requires Windows.')
    import winreg
    root = project_root() if root is None else Path(root)
    extension = root / 'extension'
    manifest = json.loads((extension / 'manifest.json').read_text(encoding='utf-8'))
    if extension_id(manifest) != EXTENSION_ID:
        raise ValueError('The extension key does not match this StayLocked build.')
    target = manifest_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    if getattr(sys, 'frozen', False):
        launcher = root / 'bridge' / 'StayLockedBridge.exe'
        if not launcher.is_file():
            raise FileNotFoundError('StayLockedBridge.exe is missing. Reinstall the complete app.')
    else:
        # Source mode remains available for development, no manual registration needed.
        python = Path(sys.executable).with_name('python.exe').resolve()
        entry = root / 'native_bridge.py'
        if not python.is_file() or not entry.is_file():
            raise FileNotFoundError('Source Python or native_bridge.py is missing.')
        for path in (python, entry):
            if any(c in str(path) for c in '%!\r\n"'):
                raise ValueError('Move the source project to a path without %, ! or quotes.')
        launcher = target.with_suffix('.cmd')
        launcher.write_text('@echo off\nsetlocal DisableDelayedExpansion\nchcp 65001 >nul\n'
                            + f'"{python}" -u "{entry}" %*\n', encoding='utf-8', newline='\r\n')
    host = {'name': HOST, 'description': 'StayLocked read-only session bridge',
            'path': str(launcher), 'type': 'stdio',
            'allowed_origins': [f'chrome-extension://{EXTENSION_ID}/']}
    firefox_host = {key: value for key, value in host.items() if key != 'allowed_origins'}
    firefox_host['allowed_extensions'] = [FIREFOX_ID]
    firefox_target = manifest_path(root, firefox=True)
    for file, data in ((target, host), (firefox_target, firefox_host)):
        temp = file.with_suffix('.tmp')
        temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
        os.replace(temp, file)
    # Chromium and Firefox check both Windows registry views.
    for registry, file in [*((r, target) for r in REGISTRY_ROOTS), (FIREFOX_REGISTRY, firefox_target)]:
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, registry + '\\' + HOST,
                                   0, winreg.KEY_WRITE | view) as key:
                winreg.SetValueEx(key, '', 0, winreg.REG_SZ, str(file))
    return extension


def unregister(root=None):
    import winreg
    root = project_root() if root is None else Path(root)
    target = manifest_path(root)
    for registry in [*REGISTRY_ROOTS, FIREFOX_REGISTRY]:
        target = manifest_path(root, firefox=registry == FIREFOX_REGISTRY)
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            key_path = registry + '\\' + HOST
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                                    winreg.KEY_READ | view) as key:
                    existing, _ = winreg.QueryValueEx(key, '')
                if os.path.normcase(existing) == os.path.normcase(str(target)):
                    winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, key_path, view)
            except FileNotFoundError:
                pass
    for target in (manifest_path(root), manifest_path(root, firefox=True)):
        target.unlink(missing_ok=True)
        target.with_suffix('.cmd').unlink(missing_ok=True)


def recent_connection():
    try:
        modified = (data_directory() / 'bridge-heartbeat').stat().st_mtime
        return 0 <= time.time() - modified < 6
    except OSError:
        return False


def launch_setup():
    if getattr(sys, 'frozen', False):
        root = Path(sys.executable).resolve().parent
        command = [str(root / 'setup' / 'ExtensionSetup.exe')]
    else:
        root = Path(__file__).resolve().parents[1]
        command = [str(Path(sys.executable).with_name('pythonw.exe')), str(root / 'extension_setup.py')]
    env = os.environ.copy()
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    subprocess.Popen(command, cwd=root, env=env, close_fds=True)


def build_wizard(root):
    """Build separately from mainloop so the actual layout can be tested."""
    import tkinter as tk
    from tkinter import ttk, messagebox
    from .theme import apply_theme, size_window
    root.title('StayLocked — Browser extension')
    from .preferences import load_theme
    from .branding import apply_window_icon
    apply_theme(root, load_theme())
    apply_window_icon(root)
    size_window(root, 760, 650, (710, 620))
    px = lambda n: max(1, round(n * root.focuslock_scale))
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=1)
    frame = ttk.Frame(root, padding=px(24))
    frame.grid(row=0, column=0, sticky='nsew')
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(12, weight=1)
    ttk.Label(frame, text='Connect your browser', style='Title.TLabel').grid(row=0, column=0, sticky='w')
    ttk.Label(frame, text='One setup. Every focus session stays in sync.', style='Muted.TLabel').grid(
        row=1, column=0, sticky='w', pady=(px(4), px(16)))
    registration = tk.StringVar(value='Preparing desktop connection…')
    ttk.Label(frame, textvariable=registration, wraplength=px(650)).grid(row=2, column=0, sticky='w')
    extension = project_root() / 'extension'
    def repair():
        try:
            register()
            registration.set('Desktop bridge is ready. Add the extension below.')
        except Exception as exc:
            registration.set('Setup failed. Click Repair connection to retry.')
            messagebox.showerror('Browser setup failed', str(exc), parent=root)
    repair()
    browser = tk.StringVar(value='Opera / Opera GX')
    selector = ttk.Combobox(frame, textvariable=browser, state='readonly',
                           values=('Opera / Opera GX', 'Chrome', 'Edge', 'Yandex', 'Firefox'), width=25)
    selector.grid(row=3, column=0, sticky='w', pady=(px(16), px(14)))
    urls = {'Opera / Opera GX': 'opera://extensions', 'Chrome': 'chrome://extensions', 'Edge': 'edge://extensions',
            'Yandex': 'browser://extensions', 'Firefox': 'about:debugging#/runtime/this-firefox'}
    copied = tk.StringVar(value='')
    def copy(value):
        root.clipboard_clear()
        root.clipboard_append(value)
        copied.set('Copied. Paste with Ctrl+V.')
    ttk.Label(frame, text='1. Open the extensions page in your browser', style='Heading.TLabel').grid(row=4, column=0, sticky='w')
    address = tk.StringVar(value=urls[browser.get()])
    def select_browser(event=None):
        firefox = browser.get() == 'Firefox'
        address.set(urls[browser.get()])
        path_value.set(str(project_root() / 'extension-firefox' / 'manifest.json') if firefox else str(extension))
        step_two.set('2. Click Load Temporary Add-on…' if firefox else '2. Enable Developer mode, then Load unpacked')
        step_three.set('3. Select manifest.json (temporary until Firefox closes)' if firefox else '3. Select the extension folder')
        path_button.configure(text='Copy file path' if firefox else 'Copy folder path')
        note.set('Firefox test build: allow access to websites if prompted. Load again after Firefox restarts. '
                 'Permanent installation requires a Mozilla-signed release.' if firefox else default_note)
    selector.bind('<<ComboboxSelected>>', select_browser)
    row = ttk.Frame(frame)
    row.grid(row=5, column=0, sticky='ew', pady=(px(8), px(18)))
    row.columnconfigure(0, weight=1)
    ttk.Entry(row, textvariable=address, state='readonly').grid(row=0, column=0, sticky='ew')
    address_button = ttk.Button(row, text='Copy address', command=lambda: copy(address.get()))
    address_button.grid(row=0, column=1, padx=(px(8), 0))
    step_two = tk.StringVar(value='2. Enable Developer mode, then Load unpacked')
    step_three = tk.StringVar(value='3. Select the extension folder')
    ttk.Label(frame, textvariable=step_two, style='Heading.TLabel').grid(
        row=6, column=0, sticky='w', pady=(0, px(18)))
    ttk.Label(frame, textvariable=step_three, style='Heading.TLabel').grid(row=7, column=0, sticky='w')
    path_value = tk.StringVar(value=str(extension))
    path_entry = ttk.Entry(frame, textvariable=path_value, state='readonly')
    path_entry.grid(row=8, column=0, sticky='ew', pady=px(8))
    row = ttk.Frame(frame)
    row.grid(row=9, column=0, sticky='ew')
    path_button = ttk.Button(row, text='Copy folder path', style='Accent.TButton', command=lambda: copy(path_value.get()))
    path_button.pack(side='left')
    def open_folder():
        try:
            os.startfile(str(project_root() / ('extension-firefox' if browser.get() == 'Firefox' else 'extension')))
        except OSError as exc:
            messagebox.showerror('Cannot open folder', str(exc), parent=root)
    ttk.Button(row, text='Open folder', command=open_folder).pack(side='left', padx=px(8))
    ttk.Label(row, textvariable=copied, style='Muted.TLabel').pack(side='left', padx=px(8))
    default_note = ('After updating: remove the old extension copy and load the installed folder once. '
                    'Pin StayLocked for easy access. Your browser data is not changed.')
    note = tk.StringVar(value=default_note)
    ttk.Label(frame, textvariable=note, style='Muted.TLabel', wraplength=px(650)).grid(
        row=10, column=0, sticky='w', pady=(px(16), px(12)))
    connection = tk.StringVar()
    ttk.Label(frame, textvariable=connection, style='Heading.TLabel').grid(row=11, column=0, sticky='w')
    def poll():
        connection.set('Connected to browser' if recent_connection() else 'Waiting for the extension…')
        root.after(1000, poll)
    poll()
    row = ttk.Frame(frame)
    row.grid(row=13, column=0, sticky='ew', pady=(px(14), 0))
    ttk.Button(row, text='Repair connection', command=repair).pack(side='left')
    done_button = ttk.Button(row, text='Done', command=root.destroy)
    done_button.pack(side='right')
    root.focuslock_setup_variables = (registration, browser, copied, address, path_value, connection, step_two, step_three, note)
    return {'path_entry': path_entry, 'copy_address': address_button, 'copy_path': path_button, 'done': done_button,
            'browser': browser, 'selector': selector, 'connection': connection}


def show_wizard():
    import tkinter as tk
    root = tk.Tk()
    build_wizard(root)
    root.mainloop()
