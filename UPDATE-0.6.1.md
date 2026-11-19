# StayLocked 0.6.1

## Restored behavior

- Timed sessions are back: 1-720 minutes, default 25, countdown and progress.
- Timer expiry or Windows restart ends the session. "Until restart" is an optional separate choice.
- The timer runs inside the installed Windows service, not in the GUI. Ending StayLocked.exe, closing a console, hiding the window, or restarting the GUI does not stop it or reset its deadline.
- Active selection and duration remain locked. There is no stop/disable IPC command.
- Both browser variants already support the timed protocol and display the remaining time.

## Fix for the screenshot error

`module 'win32file' has no attribute 'CancelIoEx'` was a real bug in pipe timeout cleanup. The code now calls documented `CancelIo` on the same thread that initiated I/O and waits for completion before freeing the OVERLAPPED/buffer. Event handles close on errors as well as on success. Authentication errors now produce a response instead of becoming an unexplained timeout.

Regression tests deliberately expose a pywin32-shaped API with no CancelIoEx. Separate real Windows pipe tests run during builds and use random test-only pipe names, without affecting the installed service or applying restrictions.

Follow-up Windows build fix: `ImpersonateNamedPipeClient` belongs to `win32security`, not `win32pipe`. The correct wrapper is now used. Regression tests cover retrieving the owner identity and restoring the service's own identity even when token access fails. The Windows round-trip test originally exposed this error; it must pass on the build PC before installation.

## Installation

1. Restart Windows to end the old 0.6.0 session, then close StayLocked and browsers using the extension.
2. Extract this source archive into a fresh folder. Run Build-Installer.cmd.
3. Run release\StayLocked-Setup-0.6.1-x64.exe.
4. Open StayLocked from Start; verify version 0.6.1 and the Session length control. Reload the installed browser extension.
5. First test a one-minute session. See VERIFICATION-0.6.1.md for the optional automated Windows service test.

Installing the new service matters: replacing source files or launching a new GUI alone leaves the old system service unchanged. Saved lists/themes are preserved.

## Boundary

The visible LocalSystem service is separate from the GUI and is not terminated by ending the GUI's process tree. It has normal Windows administrator stop/uninstall controls. No critical/protected process flags, Task Manager blocking, service resurrection, boot auto-start or recovery interference are added. An elevated owner can still deliberately stop or terminate the service. This is friction, not a promise of an unkillable computer lock.

This archive contains complete sources and build scripts, not a Windows binary compiled on the Linux development host. Actual OS integration still needs Windows acceptance testing.
