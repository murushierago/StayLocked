# StayLocked 0.7.1 verification

This release keeps the 0.7.0 interface and addresses installer upgrades plus ordinary service STOP controls during focus sessions.

## Service behavior

- STARTING/ACTIVE sessions do not advertise SERVICE_ACCEPT_STOP. The STOP handler also checks the session under the same lock as start, so a racing control cannot cancel a session.
- Once acquisition/cleanup and the session finish, ordinary STOP is available again.
- SERVICE_ACCEPT_SHUTDOWN remains available. Windows shutdown/restart can release the session normally.
- This is not protection against an elevated administrator terminating the service process. No critical-process flags, process-hiding, protected-process impersonation, auto-respawn or OS recovery interference is used.
- Update/uninstall refuses an active or unknown session. There is no unauthenticated stop IPC command.

## Upgrade behavior

Setup extracts its NEW service maintenance bundle before copying installed files. It does not execute the old installed maintenance executable to prepare an upgrade. The temporary helper cannot register service code: install/remove still verify the protected Program Files location.

SCM operations request the rights actually needed, rather than SERVICE_ALL_ACCESS. A narrow compatibility migration recognizes the old allow-only Administrators ACE with exactly SERVICE_ALL_ACCESS minus SERVICE_STOP and adds only the missing STOP bit. Unknown policies, deny ACEs, other principals and the SACL are not rewritten.

Quiet installer operations return an actionable error code and record details in `%TEMP%\StayLocked-service-setup-error.txt`. An active/unknown session is code 10 and access-denied is code 5.

## Checks

```text
python -m unittest discover -s tests -v
python tools/check_ui.py --screenshots ui-checks
```

The disposable Windows CI additionally runs `tools/check_installer_windows.py` after building the installer. It refuses machines with an existing StayLocked service/folder and is restricted to GitHub Actions:

1. Silently install the actual compiled installer into Program Files.
2. Give the service the exact legacy DACL reported by the user, with BA lacking STOP.
3. Deliberately make the old installed maintenance EXE unusable, then upgrade with the new installer.
4. Verify the new installer repairs the recognized ACL and restores the correct service binary without executing the old helper.
5. Run a real one-minute session on a disposable copy of where.exe, without touching configured user block lists or closing real applications.
6. Verify the requesting process can exit, the executable remains locked, SCM STOP is refused, prepare/remove operations refuse the active session, and shutdown remains advertised.
7. Wait for the real timer, verify unlock and restoration of ordinary STOP, then uninstall and verify service removal.

This does not reboot the runner or claim that elevated Task Manager cannot terminate a LocalSystem process. Browser/network behavior and the design/layout checks remain covered as documented in VERIFICATION-0.7.0.md and VERIFICATION-0.6.1.md.
