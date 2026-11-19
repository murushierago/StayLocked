# Verification: StayLocked 0.6.1

Date: 2026-10-04. Sources checked on Linux; native Windows acceptance is still required.

## Executed here

- Python unittest discovery: 99 tests collected, 97 passed, 2 Windows-only tests skipped.
- Project Python syntax compilation passed.
- Service tests: timer expires and releases locks without a GUI or status polling; a subsequent session can start; duplicate starts cannot change an active deadline; owner privacy, cancellation and failure rollback remain covered. OS locks/clock in these tests are fakes.
- IPC boundary tests: no CancelIoEx API is supplied, matching the screenshot failure. Read/write/connect timeouts use same-thread CancelIo; completion is drained before closing the event; cancellation races, stop and already-connected cases pass. These tests mock pywin32.
- Follow-up impersonation correction: ImpersonateNamedPipeClient is called from win32security. Regression tests omit it from win32pipe and verify owner/elevation retrieval and restoring the service identity after token failures. The real Windows round-trip test caught this misplaced wrapper on the user's PC; native confirmation after the fix is still pending.
- Bridge tests serialize the timed countdown and clear domains on ENDED; retained until-restart sessions use a 15-second status lease.
- Node extension policy/lifecycle tests passed for Chromium and Firefox API variants, including timed expiry, lease expiry, reconnect/idle, subdomains, internal/new-tab/search exclusions and navigation races.
- Real Tk GUI runner passed under Xvfb: requested 100/125/150% scaling (large scale is screen-clamped), all four themes, duration preview, countdown, disabled duration while active, optional until-restart display, row switches/crosses/deselection, tabs, tray callbacks, bridge framing and next-session duration preview after expiry. Browser setup and app-picker layouts/callbacks also passed. Windows enforcement/tray/discovery boundaries in this runner are mocked.
- The real Chromium runner could not run: no browser executable was installed, and browser downloads returned invalid archives. This is NOT a real-browser pass. The runner was extended with a timed-expiry check for execution when a test browser is available.

## Not verified here

Native Windows pipe/SCM behavior, LocalSystem file locks and process termination, actual WFP filtering, Windows tray/UAC, native browser messaging in Opera/Yandex/Firefox, PyInstaller, Inno install/upgrade/uninstall, and a real Windows restart. Portable tests and Linux Tk checks do not prove those integrations.

## Update on Windows

1. Restart Windows to finish any old 0.6.0 session. Close StayLocked from its tray menu and browsers using the extension.
2. Extract into a fresh folder and run Build-Installer.cmd. The build runs all Python tests, including two real Windows pipe tests with random test-only pipe names. They do not install or stop services, launch selected applications or apply restrictions. Stop if any build/test fails; do not run an old leftover EXE as the new release.
3. Run release\StayLocked-Setup-0.6.1-x64.exe. Updating only the GUI cannot replace old service code. Reopen from Start, verify v0.6.1 and the Session length control, and reload the installed browser extension.
4. Saved lists and appearance should remain. Test a one-minute session with saved work and one noncritical app or website.

## Opt-in service exercise

After installation, in administrator PowerShell from the source folder:

```powershell
.\.build-venv\Scripts\python.exe tools\check_service_windows.py
.\.build-venv\Scripts\python.exe tools\check_service_windows.py --exercise
```

The first command is read-only status. The second copies Windows where.exe to a disposable temporary path, starts a one-minute block on that copy from a child process, lets that requester exit completely, checks that the copy remains locked, waits for the service timer, and verifies unchanged executable bytes after release. Expected: two PASS lines. No configured apps/sites are used, no reboot happens, and an existing session makes the test refuse to run. Normal administrator SCM stop is used only to clean up its own test session on failure.

## Manual acceptance

- Start with 1 minute. The confirmation states duration and warns before forcibly closing selected apps. Save work first. Countdown must decrease and selected EXE must not launch.
- End StayLocked.exe in Task Manager, then reopen it from Start. The same session must remain active with less time, not a fresh minute. This is different from deliberately terminating StayLockedService.exe with elevated administrator rights.
- Leave the GUI closed for the rest of the minute. After expiry the application must launch; on reopening, the UI must allow a new duration and session.
- With the extension connected, test a blocked YouTube tab, an existing channel/video, and Google/Yandex search containing youtube.com. Only selected HTTP(S) domains should be blocked; new-tab/internal pages remain available. After timer expiry, the blocked page says Ready and the site can open again.
- Repeat the extension test in Yandex and Firefox. Firefox's temporary development add-on must be reloaded after Firefox closes; this release does not contain a Mozilla-signed permanent XPI.
- Test Windows Restart during a longer session. Previous restrictions must be gone; service is demand-start and does not resurrect an old session. A working bridge clears browser rules on reconnect. A broken/disconnected bridge can retain cached timed rules until their last known expiry.
- Check themes and Windows display scaling, row deselection, per-row deletion, upgrade while idle and ordinary administrator uninstall. No user files or lists should be removed.

Optional real GUI callback/layout check on Windows, with fake enforcement:

```powershell
.\.build-venv\Scripts\python.exe tools\check_ui.py
```

## Diagnostics and recovery

- Screenshot error corrected: `module 'win32file' has no attribute 'CancelIoEx'`. If this exact text remains after installing 0.6.1, check that the installed service was replaced, not just the GUI source.
- If a pipe timeout remains, do not assume no session started. Reopen the app/check status and send the full error. Authentication errors now have an explicit response.
- Service failures: Event Viewer > Windows Logs > Application. GUI: `%LOCALAPPDATA%\FocusLock\ui.log`. Browser setup: `%LOCALAPPDATA%\FocusLock\extension-setup-error.txt`.
- Normal exit is timer expiry or Windows Restart. The owner also retains administrator Services/Stop-Service control, Task Manager, shutdown and Safe Mode. No critical/protected process or automatic service resurrection is used.
