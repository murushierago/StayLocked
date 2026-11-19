"""Read-only, bounded discovery. Never launches a discovered application.

Sources: current processes, Windows App Paths, Start-menu/desktop .lnk files,
and a few exact user-local application locations. No whole-drive scan.
"""
from dataclasses import dataclass, replace
import base64
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import Event
from .storage import path_key
from .session import PROTECTED_NAMES


@dataclass(frozen=True)
class Candidate:
    name: str
    path: str
    source: str
    running: bool = False


def clean_exe(value):
    if not isinstance(value,str) or '\x00' in value or '\n' in value or '\r' in value:
        return None
    value = os.path.expandvars(value.strip())
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    value = ntpath.normpath(value)
    drive,tail = ntpath.splitdrive(value)
    if not re.fullmatch('[A-Za-z]:',drive) or not tail.startswith('\\'):
        return None
    if ':' in tail or ntpath.splitext(value)[1].lower()!='.exe':
        return None
    return value


def is_candidate(path,protected_roots=(),exists=None):
    value = clean_exe(path)
    if not value:
        return False
    name = ntpath.basename(value).casefold()
    if (name in PROTECTED_NAMES or name in {'update.exe','squirrel.exe','crashpad_handler.exe','crashreporter.exe'}
            or name.startswith(('unins','uninstall','setup','installer','vcredist','vc_redist'))):
        return False
    key = path_key(value)
    for root in protected_roots:
        prefix = path_key(str(root)).rstrip('\\')
        if key==prefix or key.startswith(prefix+'\\'):
            return False
    return (exists or os.path.isfile)(value)


def merge_candidates(candidates,protected_roots=(),exists=None):
    found = {}
    for app in candidates:
        path = clean_exe(app.path)
        if not path or not is_candidate(path,protected_roots,exists):
            continue
        key = path_key(path)
        old = found.get(key)
        safe_name = app.name.replace('\n',' ').replace('\r',' ').strip()[:120] or ntpath.splitext(ntpath.basename(path))[0]
        new = replace(app,path=path,name=safe_name)
        if old:
            # Prefer the friendly Start-menu title to the process filename.
            preferred = new if new.source=='Start menu' or old.name.lower().endswith('.exe') else old
            sources = ', '.join(dict.fromkeys((old.source+', '+new.source).split(', ')))
            found[key] = replace(preferred,source=sources,running=old.running or new.running)
        else:
            found[key] = new
    return sorted(found.values(),key=lambda app:(not app.running,app.name.casefold(),path_key(app.path)))


def version_key(path):
    return tuple(int(n) for n in re.findall(r'\d+',path.parent.name))


def resolve_squirrel(target,arguments):
    """Resolve Update.exe --processStart App.exe without ever running Update.exe."""
    match = re.search(r'--processStart(?:=|\s+)(?:"([^"/\\]+\.exe)"|([^\s"/\\]+\.exe))(?:\s|$)',arguments or '',re.I)
    if ntpath.basename(str(target)).casefold()!='update.exe' or not match:
        return None
    name = match.group(1) or match.group(2)
    if ':' in name or name in ('.','..'):
        return None
    root = Path(target).parent
    choices = [p/name for p in root.glob('app-*') if re.fullmatch(r'app-\d+(?:\.\d+)*',p.name) and (p/name).is_file()]
    return str(max(choices,key=version_key)) if choices else None


def running_apps(cancel):
    from .force_close import ProcessAPI
    api = ProcessAPI()
    for pid in api.pids():
        if cancel.is_set():
            return
        if pid in (0,4,os.getpid()):
            continue
        handle = api.open(pid)  # query/synchronize only; never TERMINATE access
        if not handle:
            continue
        try:
            path = api.path(handle)
            if path and not api.critical(handle):
                yield Candidate(ntpath.basename(path),path,'Running',True)
        except OSError:
            continue
        finally:
            api.close(handle)


def registry_apps(cancel):
    import winreg
    base = r'Software\Microsoft\Windows\CurrentVersion\App Paths'
    for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY,winreg.KEY_WOW64_64KEY):
            if cancel.is_set():
                return
            try:
                with winreg.OpenKey(hive,base,0,winreg.KEY_READ|view) as parent:
                    for index in range(min(winreg.QueryInfoKey(parent)[0],2000)):
                        if cancel.is_set():
                            return
                        try:
                            name = winreg.EnumKey(parent,index)
                            with winreg.OpenKey(parent,name) as key:
                                value,kind = winreg.QueryValueEx(key,'')
                            if kind in (winreg.REG_SZ,winreg.REG_EXPAND_SZ):
                                yield Candidate(ntpath.splitext(name)[0],value,'Windows registry')
                        except OSError:
                            continue
            except OSError:
                continue


# Fixed script: shortcut names/targets never get interpolated into commands.
# CreateShortcut opens existing .lnk metadata; Save/Run/Invoke-Item are not used.
SHORTCUT_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$shell = New-Object -ComObject WScript.Shell
$roots = @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('CommonPrograms'),
           [Environment]::GetFolderPath('DesktopDirectory'), [Environment]::GetFolderPath('CommonDesktopDirectory'))
$result = New-Object System.Collections.Generic.List[object]
$paths = @($roots | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique)
$links = @($paths | ForEach-Object { Get-ChildItem -LiteralPath $_ -Filter '*.lnk' -Recurse -File -ErrorAction SilentlyContinue } | Select-Object -First 1200)
foreach ($file in $links) {
  try {
    $link = $shell.CreateShortcut($file.FullName)
    $result.Add([PSCustomObject]@{name=$file.BaseName; path=$link.TargetPath; arguments=$link.Arguments})
  } catch {}
}
ConvertTo-Json -InputObject @($result.ToArray()) -Compress -Depth 3
'''


def shortcut_apps(cancel):
    executable = Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'
    encoded = base64.b64encode(SHORTCUT_SCRIPT.encode('utf-16-le')).decode('ascii')
    process = subprocess.Popen([str(executable),'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                               stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    import time
    deadline = time.monotonic()+25
    try:
        while True:
            if cancel.is_set():
                return
            if time.monotonic()>deadline:
                raise TimeoutError('Start-menu scan timed out; other sources are still available.')
            try:
                output,error = process.communicate(timeout=.2)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            raise OSError('Windows could not read shortcuts. Other sources are still available.')
        if len(output)>4_000_000:
            raise ValueError('Shortcut response is too large.')
        data = json.loads(output.decode('utf-8-sig'))
        if not isinstance(data,list):
            raise ValueError('Unexpected shortcut response.')
        for item in data[:1200]:
            if cancel.is_set():
                return
            if not isinstance(item,dict):
                continue
            path = clean_exe(item.get('path'))
            if not path:
                continue
            args = item.get('arguments') or ''
            if not isinstance(args,str):
                continue
            if ntpath.basename(path).casefold()=='update.exe':
                path = resolve_squirrel(path,args)
                if not path:
                    continue
            elif args:
                # A shortcut with arguments can be a website/PWA, document or
                # uninstall action. Do not offer its host (e.g. chrome.exe) as it.
                continue
            yield Candidate(str(item.get('name','')),path,'Start menu')
    finally:
        if process.poll() is None:
            process.kill()  # Only our own metadata reader, never a user app.
        process.communicate()


def common_apps(cancel):
    local,roaming = os.environ.get('LOCALAPPDATA'),os.environ.get('APPDATA')
    if roaming:
        yield Candidate('Telegram',str(Path(roaming)/'Telegram Desktop'/'Telegram.exe'),'Common location')
    if local:
        for directory,name in (('Discord','Discord.exe'),('DiscordPTB','DiscordPTB.exe'),('DiscordCanary','DiscordCanary.exe')):
            if cancel.is_set():
                return
            path = resolve_squirrel(str(Path(local)/directory/'Update.exe'),'--processStart '+name)
            if path:
                yield Candidate(directory,path,'Current installed version')
        yield Candidate('Spotify',str(Path(roaming or local)/'Spotify'/'Spotify.exe'),'Common location')
    for key in ('ProgramFiles(x86)','ProgramFiles'):
        if os.environ.get(key):
            yield Candidate('Steam',str(Path(os.environ[key])/'Steam'/'steam.exe'),'Common location')


def discover(cancel=None,publish=None):
    """Publish results between sources. All callbacks run in the scan thread."""
    cancel = cancel or Event()
    if sys.platform!='win32':
        raise OSError('Application discovery requires Windows.')
    roots = [os.environ.get('SystemRoot',r'C:\Windows'),sys.prefix,sys.base_prefix,Path(__file__).resolve().parents[1]]
    if getattr(sys,'frozen',False):
        roots.append(Path(sys.executable).resolve().parent)
    items,warnings = [],[]
    for name,source in (('Running applications',running_apps),('Known locations',common_apps),
                        ('Windows registry',registry_apps),('Start menu',shortcut_apps)):
        if cancel.is_set():
            break
        try:
            items.extend(source(cancel))
        except (OSError,ValueError,TimeoutError) as exc:
            warnings.append(f'{name}: {exc}')
        result = merge_candidates(items,roots)
        if publish and not cancel.is_set():
            publish(result,name,list(warnings))
    return merge_candidates(items,roots),warnings
