"""UI ownership checks without creating a real tray or Tk window."""
import unittest
from unittest.mock import Mock, patch
from focuslock.ui import FocusLockWindow


class TrayUiTests(unittest.TestCase):
    def window(self):
        app = FocusLockWindow.__new__(FocusLockWindow)
        app.root = Mock()
        app.tray = Mock()
        app.hidden_notice_shown = False
        app.shutting_down = False
        return app

    def test_close_hides_only_after_icon_ready(self):
        app = self.window()
        app.tray.can_hide.return_value = True
        app.hide_to_tray()
        app.root.withdraw.assert_called_once()
        app.root.destroy.assert_not_called()
        app.tray.stop.assert_not_called()
        app.hide_to_tray()
        app.tray.notify_hidden.assert_called_once()

    def test_failed_tray_cannot_strand_hidden_window(self):
        app = self.window()
        app.tray.can_hide.return_value = False
        with patch('focuslock.ui.messagebox.showinfo'):
            app.hide_to_tray()
        app.root.withdraw.assert_not_called()
        app.root.destroy.assert_not_called()

    def test_restore_via_queue_runs_in_ui_pump(self):
        app = self.window()
        app.tray.drain.return_value = iter([('open', None)])
        app.pump_tray()
        app.root.deiconify.assert_called_once()
        app.root.after.assert_called_once_with(150, app.pump_tray)

    def test_exit_cleans_tray_and_window_only(self):
        app = self.window()
        tray = app.tray
        app.exit_interface()
        self.assertTrue(app.shutting_down)
        self.assertIsNone(app.tray)
        tray.stop.assert_called_once()
        app.root.destroy.assert_called_once()
        app.close_tray()  # Idempotent main.py finally cleanup.
        tray.stop.assert_called_once()


if __name__ == '__main__':
    unittest.main()
