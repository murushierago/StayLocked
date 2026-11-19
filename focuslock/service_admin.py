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


class SessionInProgress(RuntimeError):
    pass


def require_elevated():
    import ctypes
    if not ctypes.windll.shell32.IsUserAnAdmin():
        raise PermissionError('Run the StayLocked installer as administrator.')


def legacy_acl_entries(acl, all_access, stop_access, sid_text):
    """Recognize only the old allow-only ACL with BA missing just SERVICE_STOP.

    Never remove deny ACEs, edit other principals or replace an unknown policy.
    """
    if acl is None:
        return None
    entries = [acl.GetAce(i) for i in range(acl.GetAceCount())]
    if any(len(ace) != 3 or ace[0][0] != 0 for ace in entries):
        return None
    legacy = all_access & ~stop_access
    matches = [i for i, (header, rights, sid) in enumerate(entries)
               if header[1] == 0 and rights == legacy and sid_text(sid) == 'S-1-5-32-544']
    if len(matches) != 1:
        return None
    index = matches[0]
    header, rights, sid = entries[index]
    entries[index] = (header, rights | stop_access, sid)
    return entries


def repair_legacy_acl(manager):
    import win32service as s
    import win32security as sec
    # READ_CONTROL and WRITE_DAC were present in the broken legacy descriptor.
    service = s.OpenService(manager, SERVICE_NAME, 0x20000)
    try:
        sd = s.QueryServiceObjectSecurity(service, sec.DACL_SECURITY_INFORMATION)
        entries = legacy_acl_entries(sd.GetSecurityDescriptorDacl(), s.SERVICE_ALL_ACCESS,
                                     s.SERVICE_STOP, sec.ConvertSidToStringSid)
    finally:
        s.CloseServiceHandle(service)
    if entries is None:
        return False
    service = s.OpenService(manager, SERVICE_NAME, 0x20000 | 0x40000)
    try:
        # Re-read after acquiring the write handle instead of overwriting a stale ACL.
        sd = s.QueryServiceObjectSecurity(service, sec.DACL_SECURITY_INFORMATION)
        old = sd.GetSecurityDescriptorDacl()
        entries = legacy_acl_entries(old, s.SERVICE_ALL_ACCESS, s.SERVICE_STOP, sec.ConvertSidToStringSid)
        if entries is None:
            return False
        acl = sec.ACL()
        revision = old.GetAclRevision()
        for (kind, flags), rights, sid in entries:
            acl.AddAccessAllowedAceEx(revision, flags, rights, sid)
        sd.SetSecurityDescriptorDacl(True, acl, False)
        s.SetServiceObjectSecurity(service, sec.DACL_SECURITY_INFORMATION, sd)
        return True
    finally:
        s.CloseServiceHandle(service)


def ensure_idle(service):
    import win32service as s
    if s.QueryServiceStatus(service)[1] == s.SERVICE_STOPPED:
        return
    from .service_client import read_state
    state = read_state().get('state')
    if state not in {'IDLE', 'ENDED', 'ERROR', 'INTERRUPTED'}:
        raise SessionInProgress('A focus session is active or its state is unknown. Wait for the timer or restart Windows before updating.')


def manage_service(args):
    import pywintypes
    import win32service as s
    if args not in (['--install'], ['--remove'], ['--prepare-upgrade']):
        raise ValueError('Unknown service management command.')
    require_elevated()
    installing = args == ['--install']
    # A new helper extracted by Setup may inspect/prepare an old installation.
    # Only the protected installed binary may register service code or uninstall.
    path = verify_install_location(check_acl=installing) if args != ['--prepare-upgrade'] else None
    manager = s.OpenSCManager(None, None, s.SC_MANAGER_CONNECT | (s.SC_MANAGER_CREATE_SERVICE if installing else 0))
    service = None
    try:
        try:
            service = s.OpenService(manager, SERVICE_NAME, s.SERVICE_QUERY_STATUS)
        except pywintypes.error as exc:
            if exc.winerror != 1060:
                raise
        if service is not None:
            ensure_idle(service)
            repair_legacy_acl(manager)
            running = s.QueryServiceStatus(service)[1] != s.SERVICE_STOPPED
            if running and installing:
                raise RuntimeError('Restart Windows before replacing the service.')
            if running:
                stopping = s.OpenService(manager, SERVICE_NAME, s.SERVICE_QUERY_STATUS | s.SERVICE_STOP)
                try:
                    stop_service(stopping)
                finally:
                    s.CloseServiceHandle(stopping)
        if args == ['--prepare-upgrade']:
            return
        if args == ['--remove']:
            if service is not None:
                deleting = s.OpenService(manager, SERVICE_NAME, 0x10000)  # DELETE only.
                try:
                    s.DeleteService(deleting)
                finally:
                    s.CloseServiceHandle(deleting)
            return
        if service is not None:
            configured = s.OpenService(manager, SERVICE_NAME, s.SERVICE_CHANGE_CONFIG)
            try:
                s.ChangeServiceConfig(configured, s.SERVICE_WIN32_OWN_PROCESS, s.SERVICE_DEMAND_START,
                                      s.SERVICE_ERROR_NORMAL, f'"{path}"', None, 0, None,
                                      'LocalSystem', None, 'StayLocked Focus Service')
                configure_description(configured)
            finally:
                s.CloseServiceHandle(configured)
        else:
            created = s.CreateService(manager, SERVICE_NAME, 'StayLocked Focus Service',
                s.SERVICE_CHANGE_CONFIG, s.SERVICE_WIN32_OWN_PROCESS, s.SERVICE_DEMAND_START,
                s.SERVICE_ERROR_NORMAL, f'"{path}"', None, 0, None, None, None)
            try:
                configure_description(created)
            finally:
                s.CloseServiceHandle(created)
    finally:
        if service is not None:
            s.CloseServiceHandle(service)
        s.CloseServiceHandle(manager)


def configure_description(service):
    import win32service as s
    s.ChangeServiceConfig2(service, s.SERVICE_CONFIG_DESCRIPTION,
        'User-requested focus sessions. Normal Stop is unavailable during a session; timer expiry or Windows restart unlocks.')
    s.ChangeServiceConfig2(service, s.SERVICE_CONFIG_FAILURE_ACTIONS,
                          {'ResetPeriod': 0, 'RebootMsg': None, 'Command': None, 'Actions': ()})


def main(args):
    quiet = bool(args and args[-1] == '--quiet')
    command = args[:-1] if quiet else args
    try:
        manage_service(command)
        return 0
    except Exception as exc:
        import ctypes
        import tempfile
        import traceback
        try:
            (Path(tempfile.gettempdir()) / 'StayLocked-service-setup-error.txt').write_text(
                traceback.format_exc(), encoding='utf-8')
        except OSError:
            pass
        if not quiet:
            ctypes.windll.user32.MessageBoxW(None, str(exc), 'StayLocked service setup', 0x10)
        return 10 if isinstance(exc, SessionInProgress) else 5 if isinstance(exc, PermissionError) or getattr(exc, 'winerror', None) == 5 else 1
