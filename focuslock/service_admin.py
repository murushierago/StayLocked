"""Installer-only service management. No auto-start or failure restart actions."""
import os
from pathlib import Path
import sys
import time
from .service_core import SERVICE_NAME


def verify_install_location(check_acl=True):
    import win32security as sec
    path = Path(sys.executable).resolve()
    program_files = Path(os.environ['ProgramFiles']).resolve()
    expected = program_files / 'StayLocked' / 'service' / 'StayLockedService.exe'
    if not getattr(sys, 'frozen', False) or path != expected:
        raise RuntimeError('Install the complete build in Program Files using the StayLocked installer.')
    if not check_acl:
        return path
    # Refuse redirected or user-writable service code, including bundled DLLs/Python.
    trusted = {'S-1-5-18', 'S-1-5-32-544',
               'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464'}
    service_dir = path.parent
    paths = [program_files, service_dir.parent, service_dir, *service_dir.rglob('*')]
    for item in paths:
        if item.lstat().st_file_attributes & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
            raise RuntimeError(f'Service location must not contain junctions/symlinks: {item}')
        sd = sec.GetNamedSecurityInfo(str(item), sec.SE_FILE_OBJECT, sec.DACL_SECURITY_INFORMATION)
        acl = sd.GetSecurityDescriptorDacl()
        if acl is None:
            raise RuntimeError(f'Service files require a Windows access-control list: {item}')
        for index in range(acl.GetAceCount()):
            ace = acl.GetAce(index)
            (kind, flags), rights = ace[:2]
            if kind == 0 and not flags & 0x8:  # effective ACCESS_ALLOWED, not inherit-only
                sid = sec.ConvertSidToStringSid(ace[-1])
                if sid not in trusted and rights & (0x40000000 | 0x10000000 | 0xD0000 | 0x116):
                    raise RuntimeError(f'Service location is writable by a non-system account: {item}')
    return path


def stop_service(service):
    import pywintypes
    import win32service as s
    try:
        s.ControlService(service, s.SERVICE_CONTROL_STOP)
    except pywintypes.error as exc:
        if exc.winerror != 1062:
            raise
    deadline = time.monotonic() + 60
    while s.QueryServiceStatus(service)[1] != s.SERVICE_STOPPED:
        if time.monotonic() >= deadline:
            raise RuntimeError('Service is still stopping. Restart Windows before updating.')
        time.sleep(.2)


def main(args):
    import ctypes
    import pywintypes
    import win32service as s
    try:
        if args not in (['--install'], ['--remove'], ['--prepare-upgrade']):
            raise ValueError('Unknown service management command.')
        path = verify_install_location(check_acl=args == ['--install'])
        manager = s.OpenSCManager(None, None, s.SC_MANAGER_CONNECT | s.SC_MANAGER_CREATE_SERVICE)
        try:
            try:
                service = s.OpenService(manager, SERVICE_NAME, s.SERVICE_ALL_ACCESS)
            except pywintypes.error as exc:
                if exc.winerror != 1060:
                    raise
                service = None
            try:
                if args == ['--prepare-upgrade']:
                    if service and s.QueryServiceStatus(service)[1] != s.SERVICE_STOPPED:
                        from .service_client import read_state
                        if read_state()['state'] in {'ACTIVE', 'STARTING'}:
                            raise RuntimeError('A focus session is running. Wait for the timer or restart Windows before updating StayLocked.')
                        stop_service(service)
                elif args == ['--remove']:
                    if service:
                        stop_service(service)
                        s.DeleteService(service)
                else:
                    if service:
                        if s.QueryServiceStatus(service)[1] != s.SERVICE_STOPPED:
                            raise RuntimeError('Restart Windows before replacing the service.')
                        s.ChangeServiceConfig(service, s.SERVICE_WIN32_OWN_PROCESS, s.SERVICE_DEMAND_START,
                                              s.SERVICE_ERROR_NORMAL, f'"{path}"', None, 0, None,
                                              'LocalSystem', None, 'StayLocked Focus Service')
                    else:
                        service = s.CreateService(manager, SERVICE_NAME, 'StayLocked Focus Service',
                            s.SERVICE_ALL_ACCESS, s.SERVICE_WIN32_OWN_PROCESS, s.SERVICE_DEMAND_START,
                            s.SERVICE_ERROR_NORMAL, f'"{path}"', None, 0, None, None, None)
                    s.ChangeServiceConfig2(service, s.SERVICE_CONFIG_DESCRIPTION,
                        'Temporary app and website restrictions, started by the user. End on timer expiry or Windows restart.')
                    s.ChangeServiceConfig2(service, s.SERVICE_CONFIG_FAILURE_ACTIONS,
                                          {'ResetPeriod': 0, 'RebootMsg': None, 'Command': None, 'Actions': ()})
                    # Keep normal SCM administrator control. Never set protected/critical status.
            finally:
                if service:
                    s.CloseServiceHandle(service)
        finally:
            s.CloseServiceHandle(manager)
        return 0
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(None, str(exc), 'StayLocked service setup', 0x10)
        return 1
