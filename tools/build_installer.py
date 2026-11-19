"""Compile a self-contained machine-wide installer with an installed Inno Setup."""
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def find_compiler():
    candidates = []
    if shutil.which('ISCC.exe'):
        candidates.append(Path(shutil.which('ISCC.exe')))
    for version in (7, 6):
        for key in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
            directory = os.environ.get(key)
            if directory:
                base = Path(directory)
                if key == 'LOCALAPPDATA':
                    base /= 'Programs'
                candidates.append(base / f'Inno Setup {version}' / 'ISCC.exe')
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError('Install Inno Setup 6.3+ or 7 from https://jrsoftware.org/isdl.php '
                       '(only needed on YOUR build PC), then run Build-Installer.cmd again.')


def main():
    if sys.platform != 'win32':
        raise RuntimeError('Installer compilation requires Windows.')
    if struct.calcsize('P') != 8 or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise RuntimeError('This installer recipe needs 64-bit Intel/AMD Python on Windows.')
    compiler = find_compiler()
    executable = ROOT / 'dist' / 'StayLocked' / 'StayLocked.exe'
    for required in (executable, executable.parent / 'bridge' / 'StayLockedBridge.exe',
                     executable.parent / 'setup' / 'ExtensionSetup.exe',
                     executable.parent / 'extension' / 'manifest.json',
                     executable.parent / 'extension-firefox' / 'manifest.json',
                     executable.parent / 'service' / 'StayLockedService.exe'):
        if not required.is_file():
            raise RuntimeError(f'Build the full app first. Missing: {required}')
    with (ROOT / 'installer-build.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([str(compiler), str(ROOT / 'installer' / 'StayLocked.iss')],
                                   cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, errors='replace')
        for line in process.stdout:
            log.write(line)
            log.flush()
            print(line, end='', flush=True)
        if process.wait():
            raise RuntimeError('Installer compile failed. See installer-build.log.')
    output = ROOT / 'release' / 'StayLocked-Setup-0.7.0-x64.exe'
    if not output.is_file():
        raise RuntimeError('Compiler did not produce the expected setup file.')
    print(f'\nSEND THIS ONE FILE: {output}')
    if '--no-open' not in sys.argv:
        subprocess.Popen(['explorer.exe', str(output.parent)])
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'INSTALLER BUILD FAILED: {exc}')
        raise SystemExit(1)
