# How StayLocked 0.6.1 works

The UI is an editor/client. The Windows service owns the actual OS resources. The extension asks a separate native messaging bridge for status. Keeping these lifetimes separate means closing the UI cannot run cleanup for the service.

## Following one session through the code

1. `ui.start()` snapshots switched-on entries and the chosen duration, then asks before closing selected processes. `service_client.launch_session()` starts the installed demand-start service through Windows SCM and sends paths/domains and `minutes` over its control pipe. `minutes` is 1-720, or `null` for the optional until-restart mode.
2. `service_ipc.py` authenticates the pipe client's Windows token. Only an elevated administrator can connect to the control pipe. The service obtains the owner's SID from that token, never from request JSON. No request can change an active deadline, execute a command or stop a session.
3. `SessionService.start()` validates the bounded request (including strict integer duration) and reserves the single session under a `threading.Lock`. It starts a thread *inside the service process*. The lock prevents two simultaneous clients from activating two sessions. An active session rejects another start request, so it cannot be shortened/replaced by a new duration.
4. `worker.run_session()` revalidates paths, prepares DNS, checks cancellation and optionally closes exact-path processes belonging to the owner. It retains the critical-process and Windows-directory safeguards. It acquires selected executable handles with no sharing and temporary WFP filters. `ExitStack` releases already acquired resources if a later step fails.
5. Only after acquisition succeeds is `ACTIVE` published in service memory. Timed mode records `deadline_ms = started_ms + minutes * 60000`. The loop checks GetTickCount64, which counts elapsed time including sleep; wall-clock changes do not control lifetime. No countdown is decremented by the UI. The GUI can disappear completely; it is not a heartbeat source for enforcement.
6. On timer expiry, Windows shutdown/restart (or normal elevated SCM stop), the loop ends and releases all resources before publishing ENDED. The timer loop wakes at most every 250 ms; a busy network check or a suspended system can delay cleanup until it runs again. Windows also releases handles if the service process exits abruptly. No persistent block policy needs removal next boot; the service is manual-start and the old session is not restored.

`threading.Event` lets the service wake a waiting thread during shutdown; timer expiry is checked separately. In optional `Until restart` mode there is no deadline. The legacy `session.py` detached worker helpers exist for compatibility/tests; the GUI never silently falls back to that user-owned backend. Shared duration/formatting functions are reused.

To follow the countdown: `service_core.snapshot()` computes remaining seconds from the immutable deadline; `ui.poll()` displays them and updates progress; `native_host.snapshot()` returns the same remaining seconds to the browser. Reopening the GUI does not start a new timer. The duration control is disabled while STARTING/ACTIVE, and the service independently enforces the same rule.

## Local transport

Two named byte pipes: `StayLocked.Control.v1` (elevated admin/System) and `StayLocked.Status.v1` (local authenticated users). Remote/network access is denied. Ordinary status clients get data read/write rights, without the create-pipe-instance bit. First-instance creation and client-side comparison of the pipe server PID with SCM reduce pipe impersonation risk.

Messages use a 4-byte little-endian length plus UTF-8 JSON (max 64 KiB). I/O is overlapped with deadlines and cancellation; buffers remain alive until completion. A receipt byte confirms the response was consumed before disconnecting. Slow/disconnected clients do not own session lifetime. Status returns app paths/domains only to the session owner's SID; other users see a generic busy state.

The 0.6.0 error came from a nonexistent `win32file.CancelIoEx` wrapper during timeout cleanup. Each handle has only one pending operation at a time and `_io()` starts and cancels it on the same thread, so documented `win32file.CancelIo(handle)` is appropriate. It then drains `GetOverlappedResult` before closing the event or releasing the buffer. Client identity errors are now sent back as an error response instead of being silently discarded into a client timeout. A failed start response may be ambiguous (the service may already have accepted it); the UI must read the service status rather than assume everything is unlocked.

The browser-facing host is read-only and strips executable paths. The host name `com.focuslock.bridge`, Chromium public key/ID, and `%LOCALAPPDATA%\FocusLock` remain unchanged. The Firefox ID is `staylocked@staylocked.local`; Firefox uses its own native manifest with `allowed_extensions` and Mozilla registry keys.

## Browser policy and reboot

Shared JS selects `browser` Promise APIs on Firefox, `chrome` on Chromium. Firefox uses MV3 background scripts; Chromium uses a service worker. `tools/build_extensions.py` generates the Firefox variant from the shared `extension` source to prevent drift.

Protocol 2 carries `mode: until_reboot` and a renewable 15-second **connection lease**. This is not the focus duration. Repeated status messages keep browser rules active indefinitely while the service reports ACTIVE. The UI shows “Until restart”, not the lease countdown. An idle response clears rules immediately; a failed bridge lets cached browser policy expire (normally each second, or on the next alarm/background wake). The service's Windows restrictions do not depend on this lease. This prevents stale browser cache from becoming an indefinite block after reboot or broken installation. A disabled extension is still a possible bypass of browser-level rules.

Timed sessions reuse protocol 1, already supported by both extension variants: a bounded `remainingSeconds` countdown, no executable paths. An idle response after timer/reboot clears the rules. If the bridge is unavailable, the extension retains the last known timed policy until that countdown expires; after reboot with a broken bridge it may therefore remain blocked for the remaining duration. A working bridge clears it on reconnect. Neither protocol is an unbypassable browser security boundary.

The extension redirects selected HTTP(S) domains/subdomains and blocks their subresources/initiated media. Only HTTP(S) participates. Internal/new-tab pages and searches containing the domain as text are excluded. Windows IP filters are a coarse additional layer: shared hosting, VPN/CDN and already buffered media remain limitations, not a security boundary.

## Interface and saved data

Row highlight (`Treeview.selection`) and a Use switch are separate states. Clicking blank space clears only the highlight. Clicking `×` passes that row explicitly to the remove method; it does not accidentally delete another selected row. Busy checks prevent list edits after start. Window close still hides to tray, even though the duplicate Hide to tray button is gone.

Themes remain in appearance.json; config.json keeps schema 3. The four palettes, rounded surfaces, app discovery and brand assets are unchanged. Discovery reads process paths, known app locations, App Paths and Start menu/Desktop shortcut metadata. It does not launch shortcuts. The project stays Python/Tkinter; pywin32 adds native Windows service/pipe APIs, preserving the existing enforcement code.

## Owner control

A visible, normally stoppable LocalSystem service is stronger separation than a user-owned worker. It is not an unkillable process. Elevated admins can stop/terminate/delete it; no Task Manager disabling, protected/critical process flags, automatic resurrection or Safe Mode interference is used. The installer never registers service code from a user-writable folder. Windows IP filters and shared executable locks can affect other logged-in users, which the Start confirmation discloses.

## Primary references

- https://mhammond.github.io/pywin32/ — service, named pipe, token and overlapped I/O APIs.
- https://mhammond.github.io/pywin32/win32file__CancelIo_meth.html — the available pywin32 cancellation API.
- https://learn.microsoft.com/en-us/windows/win32/api/ioapiset/nf-ioapiset-cancelio — same-thread cancellation and completion requirements.
- https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_messaging — Firefox host arguments and manifests.
- https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/ — signing requirement for permanent distribution.
- https://extensionworkshop.com/documentation/develop/firefox-builtin-data-consent/ — Firefox 140+ declaration, no external collection/transmission.
- https://jrsoftware.org/ishelp/topic_isxfunc_execasoriginaluser.htm — current-user browser registration from an elevated installer.
