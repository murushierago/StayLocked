"""Disposable Windows CI: fresh install, legacy ACL upgrade and uninstall.
Never run against an existing user installation. Does not reboot the runner.
"""
import argparse
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_setup(exe, log):
    command = [str(exe), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/LOG=' + str(log)]
    result = subprocess.run(command, timeout=120)
    if result.returncode:
        for path in (log, Path(tempfile.gettempdir()) / 'StayLocked-service-setup-error.txt'):
            if path.is_file():
                print(path.read_text(errors='replace')[-10000:], flush=True)
        raise RuntimeError(f'{exe.name} exited with {result.returncode}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'win32' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('This machine-install smoke check is restricted to a disposable Windows Actions runner.')
    if not ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError('Elevated Windows runner required.')
    import win32service as s
    import win32security as sec
    from focuslock.service_client import service_status
    from focuslock.service_core import SERVICE_NAME
    if service_status() is not None:
        raise RuntimeError('Refusing to modify an existing StayLocked service.')
    installed = Path(os.environ['ProgramFiles']) / 'StayLocked'
    if installed.exists():
        raise RuntimeError('Refusing to modify an existing StayLocked installation folder.')
    logs = ROOT / 'installer-checks'
    logs.mkdir(exist_ok=True)
    run_setup(args.installer.resolve(), logs / 'fresh-install.log')
    print('PASS: fresh install registered the service in Program Files.', flush=True)
    manager = s.OpenSCManager(None, None, s.SC_MANAGER_CONNECT)
    service = s.OpenService(manager, SERVICE_NAME, 0x20000 | 0x40000)
    legacy = 'D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPDTLOCRSDRCWDWO;;;BA)(A;;CCLCSWLOCRRC;;;IU)(A;;CCLCSWLOCRRC;;;SU)'
    try:
        sd = sec.ConvertStringSecurityDescriptorToSecurityDescriptor(legacy, 1)
        s.SetServiceObjectSecurity(service, sec.DACL_SECURITY_INFORMATION, sd)
    finally:
        s.CloseServiceHandle(service)
        s.CloseServiceHandle(manager)
    # The old helper is intentionally unusable. Upgrade must execute its newly
    # bundled helper before replacing any installed service files.
    binary = installed / 'service' / 'StayLockedService.exe'
    binary.write_bytes(b'Unusable legacy maintenance executable for upgrade regression test')
    run_setup(args.installer.resolve(), logs / 'upgrade-legacy-acl.log')
    assert binary.read_bytes()[:2] == b'MZ'
    manager = s.OpenSCManager(None, None, s.SC_MANAGER_CONNECT)
    service = s.OpenService(manager, SERVICE_NAME, s.SERVICE_ALL_ACCESS)
    try:
        assert s.QueryServiceStatus(service)[1] == s.SERVICE_STOPPED
        assert s.QueryServiceConfig(service)[1] == s.SERVICE_DEMAND_START
    finally:
        s.CloseServiceHandle(service)
        s.CloseServiceHandle(manager)
    print('PASS: upgrade ignored the broken old helper and repaired the exact legacy ACL.', flush=True)
    subprocess.run([sys.executable, str(ROOT / 'tools' / 'check_service_windows.py'), '--exercise'],
                   cwd=ROOT, check=True, timeout=160)
    # The previous test's timer has ended; normal maintenance is available again.
    run_setup(installed / 'unins000.exe', logs / 'uninstall.log')
    deadline = time.monotonic() + 10
    while service_status() is not None and time.monotonic() < deadline:
        time.sleep(.1)
    assert service_status() is None
    print('PASS: timed canary, active STOP refusal, unlock and uninstall.', flush=True)


if __name__ == '__main__':
    main()
