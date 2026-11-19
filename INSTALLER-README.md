# Build/install StayLocked 0.6.1

Double-click `Build-Installer.cmd` on Windows 10/11 x64 with Python 3.12–3.14 x64 and Inno Setup 6.3+ or 7 installed. It installs pinned build dependencies, runs Python tests, generates both browser folders, builds four PyInstaller onedir components and compiles Inno Setup.

Output: `release\StayLocked-Setup-0.6.1-x64.exe`. Send this one file. The recipient needs no Python. Building Windows binaries on the Linux development host is not supported.

This patch changes the installed service's timer contract and pipe I/O. Installing only a new GUI EXE leaves the old service code running. Rebuild and run the full installer. Windows builds now include real named-pipe tests with disposable test-only pipes; these do not install/start/stop the StayLocked service or apply any restrictions.

The installer now requests administrator rights and uses `%ProgramFiles%\StayLocked`. Its visible LocalSystem service is demand-start, with no recovery restart actions and no boot autostart. Its executable path is quoted. Registration refuses user-writable or redirected service files. Never register a SYSTEM service pointing to a source, venv or portable directory.

The old per-user installer and new all-user installation may coexist in Windows Apps. They use the same app name/AppId but different install scope. The new installer does not reuse an old LocalAppData path. Lists remain in the same user data directory. It does not copy or remove browser profiles.

Browser registration uses the original setup user's HKCU where possible. If UAC uses a different administrator account, launch Browser setup separately in the intended browser account and use a consistent owner for sessions. Different-account elevation is not a supported everyday launch mode in this release.

Updating a running focus session is rejected. Wait for the timer or restart first (0.6.0 sessions require restart). Setup can stop an idle service before copying files. Uninstallation uses normal administrator SCM STOP + DeleteService before removing binaries; it must not leave a running service pointing to removed files. It leaves saved lists untouched. Browser unregister removes only registry values pointing to this installation, so uninstalling an older copy does not clobber a newer registration.

Firefox temporary install instructions are bundled. No Mozilla signing credentials, signed XPI, Chrome Store listing or silent extension installation is included.

Release verification is in VERIFICATION-0.6.1.md. This service migration needs native Windows acceptance testing before sending it widely.
