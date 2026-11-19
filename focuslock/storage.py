"""Versioned configuration, validation, and atomic writes. No OS restrictions."""
import json
import ntpath
import os
from pathlib import Path
import tempfile


def data_directory():
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise OSError("LOCALAPPDATA is unavailable.")
    # Stable location shared with pre-0.5 FocusLock, including live worker identity.
    # Renaming/moving it would disconnect an existing session and lose saved lists.
    return Path(local) / "FocusLock"


def path_key(path):
    return ntpath.normcase(ntpath.normpath(path))


def validate_applications(items):
    if not isinstance(items, list):
        raise ValueError("Applications must be a list.")
    seen = set()
    for item in items:
        if not isinstance(item, str) or "\x00" in item:
            raise ValueError("Invalid application path.")
        drive, tail = ntpath.splitdrive(item)
        if not drive or not tail.startswith(("/", "\\")):
            raise ValueError(f"An absolute Windows path is required: {item}")
        if ntpath.splitext(item)[1].lower() != ".exe":
            raise ValueError(f"Expected an .exe path: {item}")
        key = path_key(item)
        if key in seen:
            raise ValueError(f"Duplicate application: {item}")
        seen.add(key)
    # Missing files are retained: an unmounted drive must not erase the list.
    return list(items)


class ConfigStore:
    def __init__(self, path):
        self.path = Path(path)

    def load_config(self):
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"applications": [], "websites": [], "disabled_applications": [], "disabled_websites": []}
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or type(data.get("schema_version")) is not int:
                raise ValueError("Missing or invalid schema_version.")
            if data["schema_version"] not in (1, 2, 3):
                raise ValueError("Unsupported settings version.")
            from .websites import validate_websites
            apps = validate_applications(data.get('applications'))
            sites = validate_websites(data.get('websites', []) if data['schema_version'] >= 2 else [])
            disabled_apps = validate_applications(data.get('disabled_applications', []) if data['schema_version'] == 3 else [])
            disabled_sites = validate_websites(data.get('disabled_websites', []) if data['schema_version'] == 3 else [])
            if not {path_key(p) for p in disabled_apps} <= {path_key(p) for p in apps}:
                raise ValueError('Disabled application is missing from the list.')
            if not set(disabled_sites) <= set(sites):
                raise ValueError('Disabled website is missing from the list.')
            return {'applications': apps, 'websites': sites,
                    'disabled_applications': disabled_apps, 'disabled_websites': disabled_sites}

        except (ValueError, UnicodeError) as exc:
            raise ValueError(f"Cannot read {self.path}: {exc}") from exc

    def load(self):
        return self.load_config()['applications']

    def load_websites(self):
        return self.load_config()['websites']

    def save(self, applications):
        data = self.load_config()
        self._save(applications, data['websites'], data['disabled_applications'], data['disabled_websites'])

    def save_websites(self, websites):
        data = self.load_config()
        self._save(data['applications'], websites, data['disabled_applications'], data['disabled_websites'])

    def save_selection(self, disabled_applications, disabled_websites):
        data = self.load_config()
        self._save(data['applications'], data['websites'], disabled_applications, disabled_websites)

    def _save(self, applications, websites, disabled_applications=(), disabled_websites=()):
        from .websites import validate_websites
        apps = validate_applications(applications)
        sites = validate_websites(websites)
        app_keys = {path_key(p) for p in apps}
        disabled_apps = validate_applications(list(disabled_applications))
        disabled_sites = validate_websites(list(disabled_websites))
        data = {'schema_version': 3, 'applications': apps, 'websites': sites,
                'disabled_applications': [p for p in disabled_apps if path_key(p) in app_keys],
                'disabled_websites': [d for d in disabled_sites if d in sites]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="config-", suffix=".tmp", dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(data, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
