#define AppVersion "0.7.0"
[Setup]
AppId={{5168D3D9-DA9E-4A70-A8DD-AFAD92F0743E}
AppName=StayLocked
AppVersion={#AppVersion}
AppPublisher=StayLocked
DefaultDirName={autopf}\StayLocked
DisableDirPage=yes
DefaultGroupName=StayLocked
DisableProgramGroupPage=yes
PrivilegesRequired=admin
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=StayLocked-Setup-{#AppVersion}-x64
SetupIconFile=..\assets\staylocked.ico
UninstallDisplayIcon={app}\StayLocked.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AppMutex=Local\FocusLock.InstalledRunning
CloseApplications=no
RestartApplications=no
UsePreviousAppDir=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
SetupAppRunningError=StayLocked or its browser bridge is running. Restart Windows, exit StayLocked from the tray, close Browser extension setup and close browsers using the extension, then retry.
UninstallAppRunningError=Restart Windows, exit StayLocked from the tray, close Browser extension setup and close browsers using the extension, then retry.

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\StayLocked\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{app}\FocusLock.exe"
Type: files; Name: "{app}\bridge\FocusLockBridge.exe"
Type: files; Name: "{autoprograms}\FocusLock.lnk"
Type: files; Name: "{autodesktop}\FocusLock.lnk"

[Icons]
Name: "{autoprograms}\StayLocked"; Filename: "{app}\StayLocked.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\StayLocked"; Filename: "{app}\StayLocked.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[UninstallRun]
Filename: "{app}\setup\ExtensionSetup.exe"; Parameters: "--remove"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveFocusLockBridge"

[Run]
Filename: "{app}\setup\ExtensionSetup.exe"; Description: "Connect the browser extension"; Flags: postinstall skipifsilent runasoriginaluser
Filename: "{app}\StayLocked.exe"; Description: "Launch StayLocked"; Flags: shellexec nowait postinstall skipifsilent

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  ServiceExe: String;
begin
  Result := '';
  ServiceExe := ExpandConstant('{app}\service\StayLockedService.exe');
  if FileExists(ServiceExe) then
  begin
    if not Exec(ServiceExe, '--prepare-upgrade', ExpandConstant('{app}'),
      SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      Result := 'Could not check the existing service. Restart Windows and retry.'
    else if ResultCode <> 0 then
      Result := 'The service cannot be updated now. Restart Windows and retry.';
  end;
end;

function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
  ServiceExe: String;
begin
  Result := True;
  ServiceExe := ExpandConstant('{app}\service\StayLockedService.exe');
  if FileExists(ServiceExe) then
    Result := Exec(ServiceExe, '--remove', ExpandConstant('{app}'),
      SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
  if not Result then
    MsgBox('Could not stop/remove the Windows service. Restart Windows and retry.', mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    if not Exec(ExpandConstant('{app}\service\StayLockedService.exe'), '--install',
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      RaiseException('Could not install the StayLocked Windows service.')
    else if ResultCode <> 0 then
      RaiseException('Windows service registration failed. Installation is incomplete.');
    if not ExecAsOriginalUser(ExpandConstant('{app}\setup\ExtensionSetup.exe'), '--register',
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      MsgBox('Browser connection setup could not start. Open Browser extension in StayLocked to repair it.', mbError, MB_OK)
    else if ResultCode <> 0 then
      MsgBox('Browser connection setup failed. Open Browser extension in StayLocked to repair it. Details: %LOCALAPPDATA%\FocusLock\extension-setup-error.txt', mbError, MB_OK);
  end;
end;
