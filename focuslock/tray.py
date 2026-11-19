"""Windows tray UI; callbacks communicate with Tk only through a queue."""
from queue import Queue, Empty
from threading import Event, Thread
import logging


class TrayController:
    def __init__(self):
        # Lazy imports keep worker and lifecycle tests independent of GUI deps.
        import pystray
        from .branding import make_icon

        self.events = Queue()
        self.ready = Event()
        self.stopping = Event()
        image = make_icon(64)
        self.icon = pystray.Icon(
            'StayLocked', image, 'StayLocked — Ready',
            menu=pystray.Menu(
                pystray.MenuItem('Open StayLocked', lambda icon, item: self.events.put(('open', None)), default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem('Exit interface (session continues)',
                                 lambda icon, item: self.events.put(('exit', None))),
            ),
        )
        self.thread = Thread(target=self._run, name='StayLocked-tray', daemon=True)
        self.thread.start()

    def _setup(self, icon):
        try:
            if not self.stopping.is_set():
                icon.visible = True
                self.ready.set()
        except Exception as exc:
            self.events.put(('error', str(exc)))
            icon.stop()

    def _run(self):
        try:
            self.icon.run(setup=self._setup)
        except Exception as exc:
            self.events.put(('error', str(exc)))
        finally:
            self.ready.clear()
            if not self.stopping.is_set():
                self.events.put(('error', 'The notification icon stopped. The window has been restored.'))

    def can_hide(self):
        return self.ready.is_set() and not self.stopping.is_set() and self.thread.is_alive()

    def drain(self):
        while True:
            try:
                yield self.events.get_nowait()
            except Empty:
                return

    def set_title(self, title):
        if self.can_hide():
            try:
                self.icon.title = title[:120]
            except Exception as exc:
                self.events.put(('error', str(exc)))

    def notify_hidden(self):
        if self.can_hide():
            try:
                self.icon.notify('StayLocked is here. Click the icon to reopen the window.', 'StayLocked')
            except Exception:
                logging.exception('Optional tray notification failed')

    def stop(self):
        if self.stopping.is_set():
            return
        self.stopping.set()
        self.ready.clear()
        self.icon.stop()
