"""Installer bridge ownership, account-local registration, and release assembly."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from focuslock import extension_setup as setup


class Registry:
    HKEY_CURRENT_USER = 1
    KEY_WOW64_32KEY = 32
    KEY_WOW64_64KEY = 64
    KEY_WRITE = 2
    KEY_READ = 4
    REG_SZ = 1
    def __init__(self):
        self.values = {}
    def CreateKeyEx(self, hive, name, reserved, access):
        view = access & (32 | 64)
        key = (hive, name, view)
        self.values.setdefault(key, '')
        class Handle:
            def __enter__(inner): return key
            def __exit__(inner, *args): pass
        return Handle()
    def OpenKey(self, hive, name, reserved, access):
        if (hive, name, access & (32 | 64)) not in self.values:
            raise FileNotFoundError()
        return self.CreateKeyEx(hive, name, reserved, access)
    def SetValueEx(self, key, name, reserved, kind, value): self.values[key] = value
    def QueryValueEx(self, key, name): return self.values[key], self.REG_SZ
    def DeleteKeyEx(self, hive, name, view): del self.values[(hive, name, view)]


class ExtensionSetupTests(unittest.TestCase):
    def bundle(self, root):
        (root / 'extension').mkdir(parents=True)
        original = Path(__file__).resolve().parents[1] / 'extension' / 'manifest.json'
        (root / 'extension' / 'manifest.json').write_bytes(original.read_bytes())
        (root / 'bridge').mkdir()
        (root / 'bridge' / 'StayLockedBridge.exe').touch()

    def test_frozen_registration_is_direct_exe_in_both_user_registry_views(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'App space'
            self.bundle(root)
            registry = Registry()
            with patch.object(sys, 'platform', 'win32'), patch.object(sys, 'frozen', True, create=True), \
                 patch.dict(sys.modules, {'winreg': registry}), \
                 patch.object(setup, 'data_directory', return_value=Path(tmp) / 'data'):
                self.assertEqual(setup.register(root), root / 'extension')
                self.assertEqual(len(registry.values), 8)
                manifest = json.loads(setup.manifest_path(root).read_text())
                self.assertEqual(manifest['path'], str(root / 'bridge' / 'StayLockedBridge.exe'))
                self.assertEqual(manifest['allowed_origins'], [f'chrome-extension://{setup.EXTENSION_ID}/'])
                firefox = json.loads(setup.manifest_path(root, firefox=True).read_text())
                self.assertEqual(firefox['allowed_extensions'], [setup.FIREFOX_ID])
                self.assertNotIn('allowed_origins', firefox)
                self.assertIn((1, setup.FIREFOX_REGISTRY + '\\' + setup.HOST, 32), registry.values)
                setup.unregister(root)
                self.assertEqual(registry.values, {})

    def test_old_uninstaller_does_not_remove_new_install_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / 'old', Path(tmp) / 'new'
            self.bundle(a)
            self.bundle(b)
            registry = Registry()
            with patch.object(sys, 'platform', 'win32'), patch.object(sys, 'frozen', True, create=True), \
                 patch.dict(sys.modules, {'winreg': registry}), \
                 patch.object(setup, 'data_directory', return_value=Path(tmp) / 'data'):
                setup.register(a)
                setup.register(b)
                setup.unregister(a)
                self.assertEqual(set(registry.values.values()), {str(setup.manifest_path(b)), str(setup.manifest_path(b, firefox=True))})
                self.assertTrue(setup.manifest_path(b).is_file())

    def test_missing_bridge_does_not_replace_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'app'
            self.bundle(root)
            (root / 'bridge' / 'StayLockedBridge.exe').unlink()
            registry = Registry()
            with patch.object(sys, 'platform', 'win32'), patch.object(sys, 'frozen', True, create=True), \
                 patch.dict(sys.modules, {'winreg': registry}), \
                 patch.object(setup, 'data_directory', return_value=Path(tmp) / 'data'):
                with self.assertRaises(FileNotFoundError): setup.register(root)
                self.assertEqual(registry.values, {})

    def test_setup_launch_resets_pyinstaller_environment(self):
        with patch.object(sys, 'frozen', True, create=True), \
             patch.object(sys, 'executable', str(Path.cwd() / 'FocusLock.exe')), \
             patch.object(setup.subprocess, 'Popen') as spawn:
            setup.launch_setup()
        args, kwargs = spawn.call_args
        self.assertEqual(args[0], [str(Path.cwd() / 'setup' / 'ExtensionSetup.exe')])
        self.assertEqual(kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'], '1')

    def test_new_setup_retains_stable_extension_identity(self):
        path = Path(__file__).resolve().parents[1] / 'extension' / 'manifest.json'
        self.assertEqual(setup.extension_id(json.loads(path.read_text())), setup.EXTENSION_ID)


if __name__ == '__main__':
    unittest.main()
