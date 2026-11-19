"""Real Windows icon rendering and GDI lifetime; never starts an executable."""
import ctypes
import sys
import unittest

from focuslock.app_icons import _executable_icon


@unittest.skipUnless(sys.platform == 'win32', 'Real Windows GDI APIs required')
class ExecutableIconTests(unittest.TestCase):
    def test_icon_rendering_releases_native_resources(self):
        from ctypes import wintypes
        counter = ctypes.WinDLL('user32').GetGuiResources
        counter.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        counter.restype = wintypes.DWORD
        image = _executable_icon(sys.executable, 36, '#191b23')
        self.assertIsNotNone(image)
        self.assertEqual(image.size, (36, 36))
        before = counter(wintypes.HANDLE(-1), 0)
        for _ in range(20):
            self.assertIsNotNone(_executable_icon(sys.executable, 36, '#ffffff'))
        self.assertLessEqual(counter(wintypes.HANDLE(-1), 0), before + 1)


if __name__ == '__main__':
    unittest.main()
