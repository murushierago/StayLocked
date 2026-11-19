# StayLocked 0.7.0 verification

The UI update retains the 0.6.1 service, IPC and browser enforcement behavior. No service lifecycle, authentication, deadline, executable validation or filtering code was changed.

## Automated checks

Run from the project root:

```text
python -m unittest discover -s tests -v
python tools/check_ui.py --screenshots ui-checks
```

The unit suite covers existing service/session/selection/bridge behavior plus appearance migration, atomic save failures, invalid preferences and readable accent combinations. The Windows-only icon test reads Python's own executable resources and checks that repeated rendering does not leak GDI objects.

The native Tk checks run without a real tray, service session or registry write. They exercise:

- Minimum window size, font metrics and clipping at requested scales 100%, 125% and 150%.
- Applications/websites, row-specific remove, multiselection, enabled state and persisted configuration.
- Search with original row IDs, empty results, scrolling, deletion under a filter and selected-path identity after removing an earlier row.
- Preset and custom durations, invalid input, active-session controls, progress, website-only sessions and returning to idle.
- Four themes, custom accent/density/timer style, live preview, Apply, Cancel, Restore defaults and reopening with saved preferences.
- Cosmetic edits during an active simulated session without modifying its clock, session ID or config bytes.
- Browser wizard clipboard actions and application discovery dialog behavior.

Development checks passed on Linux using real Tk 8.6 / Python 3.13 and Tk 9 / Python 3.12, with Windows/service boundaries replaced by test doubles. The desktop screenshots are real Tk renders with demonstration applications and monogram icons, not generated concepts. Native executable icon rendering and the Windows installer are verified separately by the Windows workflow when it succeeds.

## Windows smoke check after installing

1. Download the installer from a successful **Windows build and checks** workflow artifact, or build it with `Build-Installer.cmd`. The old `release/StayLocked-Setup-0.6.1-x64.exe` does not contain the new interface.
2. Finish the current session/restart Windows, exit the old UI from the tray and close browsers using the extension before upgrading, following the existing installer instructions.
3. Launch StayLocked, verify the existing lists and switches, and search for an app that is not the first row. Toggle and remove it; confirm no other app changes.
4. Try Customize in idle and during a short session. Apply persists after relaunch, Cancel restores the saved appearance, and duration stays fixed during a session.
5. Start a one-minute session with a disposable app after saving its work. Confirm blocking, close/reopen the UI, let the timer expire and check unlock. Repeat a website-only session with the browser extension connected.
6. Check 125% / 150% Windows display scaling and the smallest supported window, plus app icons from several installed EXEs and a missing file.
7. Confirm tray restore and Exit interface leave the active service session running. Restart Windows and check that temporary restrictions clear.

The automated build and simulated GUI checks do not replace a real installation and blocking smoke check. Existing platform limitations remain documented in README.md and VERIFICATION-0.6.1.md.
