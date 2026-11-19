"""Windows build helper. Writes only generated build/dist/log files."""
from pathlib import Path
import subprocess
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform != 'win32':
        raise RuntimeError('Build the Windows executable on Windows.')
    from build_assets import main as build_assets
    build_assets()
    from build_extensions import main as build_extensions
    build_extensions()
    assets = ROOT / 'assets'
    icon_path = assets / 'staylocked.ico'
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
               '--onedir', '--windowed', '--uac-admin', '--noupx', '--name', 'StayLocked',
               '--icon', str(icon_path), '--add-data', str(assets) + ':assets',
               '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'build' / 'pyinstaller'),
               '--specpath', str(ROOT / 'build'), '--paths', str(ROOT),
               '--hidden-import', 'pystray._win32',
               '--hidden-import', 'focuslock.worker', str(ROOT / 'entrypoint.py')]
    components = ROOT / 'build' / 'components'
    bridge = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
              '--onedir', '--console', '--hide-console', 'hide-early', '--noupx',
              '--name', 'StayLockedBridge', '--distpath', str(components),
              '--workpath', str(ROOT / 'build' / 'bridge'), '--specpath', str(ROOT / 'build'),
              '--paths', str(ROOT), str(ROOT / 'native_bridge.py')]
    setup = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
             '--onedir', '--windowed', '--noupx', '--name', 'ExtensionSetup',
             '--icon', str(icon_path), '--add-data', str(assets) + ':assets', '--distpath', str(components),
             '--workpath', str(ROOT / 'build' / 'setup'), '--specpath', str(ROOT / 'build'),
             '--paths', str(ROOT), str(ROOT / 'extension_setup.py')]
    service = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
               '--onedir', '--console', '--noupx', '--name', 'StayLockedService',
               '--distpath', str(components), '--workpath', str(ROOT / 'build' / 'service'),
               '--specpath', str(ROOT / 'build'), '--paths', str(ROOT),
               '--hidden-import', 'win32timezone', str(ROOT / 'service_entrypoint.py')]
    with (ROOT / 'build.log').open('w', encoding='utf-8') as log:
        for job in (command, bridge, setup, service):
            process = subprocess.Popen(job, cwd=ROOT, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True,
                                       encoding='utf-8', errors='replace')
            for line in process.stdout:
                log.write(line)
                log.flush()
                print(line, end='', flush=True)
            if process.wait():
                raise RuntimeError('PyInstaller failed. See build.log in the project folder.')
    destination = ROOT / 'dist' / 'StayLocked'
    shutil.copytree(components / 'StayLockedBridge', destination / 'bridge', dirs_exist_ok=True)
    shutil.copytree(components / 'ExtensionSetup', destination / 'setup', dirs_exist_ok=True)
    shutil.copytree(components / 'StayLockedService', destination / 'service', dirs_exist_ok=True)
    shutil.copytree(ROOT / 'extension-firefox', destination / 'extension-firefox', dirs_exist_ok=True)
    shutil.copytree(ROOT / 'extension', destination / 'extension', dirs_exist_ok=True)
    shutil.copyfile(ROOT / 'QUICK-START.txt', destination / 'QUICK-START.txt')
    executable = ROOT / 'dist' / 'StayLocked' / 'StayLocked.exe'
    if not executable.is_file():
        raise RuntimeError('Build returned without producing StayLocked.exe.')
    (executable.parent / 'READ-ME.txt').write_text(
        'Install with StayLocked-Setup-0.6.1-x64.exe first. The Windows service is required.\n'
        'This build folder alone is not a portable app. Share the installer.\n'
        'Click Browser setup once to connect your browser. No Python is needed.\n'
        'X hides the window to the tray. Exit interface does not stop an active session.\n'
        'Settings/logs: %LOCALAPPDATA%\\FocusLock\n', encoding='utf-8')
    print(f'\nBUILD COMPLETE: {executable}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'BUILD FAILED: {exc}')
        raise SystemExit(1)
