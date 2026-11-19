"""Check the installer marker is shared and always released on exit."""
import unittest
from unittest.mock import patch
from focuslock import winapi


class InstallationMarkerTests(unittest.TestCase):
    def test_shared_marker_uses_same_name_as_installer(self):
        from pathlib import Path
        recipe = (Path(__file__).resolve().parents[1] / 'installer' / 'StayLocked.iss').read_text()
        name = next(line.split('=', 1)[1] for line in recipe.splitlines() if line.startswith('AppMutex='))
        with patch.object(winapi, 'create_mutex', return_value=42, create=True) as create, \
             patch.object(winapi, 'close_handle', create=True) as close:
            with winapi.InstallationMarker():
                create.assert_called_once_with(None, False, name)
                close.assert_not_called()
            close.assert_called_once_with(42)

    def test_marker_released_when_application_fails(self):
        with patch.object(winapi, 'create_mutex', return_value=42, create=True), \
             patch.object(winapi, 'close_handle', create=True) as close:
            with self.assertRaises(RuntimeError):
                with winapi.InstallationMarker():
                    raise RuntimeError('simulated failure')
            close.assert_called_once_with(42)


if __name__ == '__main__':
    unittest.main()
