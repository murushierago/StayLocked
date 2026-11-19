"""StayLocked desktop — service-managed reboot sessions. Run on Windows with: py main.py"""
import os
import sys
import tkinter as tk
from tkinter import messagebox

from focuslock.storage import ConfigStore, data_directory
from focuslock.ui import FocusLockWindow


def main():
    root = tk.Tk()
    root.withdraw()
    if sys.platform != "win32":
        messagebox.showerror("StayLocked", "This build targets Windows 10/11.", parent=root)
        root.destroy()
        return 1

    # OS-owned file lock: released even if the process crashes. No stale lock files.
    import msvcrt
    lock = None
    locked = False
    app = None
    try:
        directory = data_directory()
        directory.mkdir(parents=True, exist_ok=True)
        lock = (directory / "ui.lock").open("a+b")
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            locked = True
        except OSError:
            messagebox.showinfo("StayLocked", "StayLocked is already running. Open its icon near the Windows clock (possibly under the up arrow).", parent=root)
            return 0

        store = ConfigStore(directory / "config.json")
        applications = store.load()
        app = FocusLockWindow(root, store, applications)
        root.deiconify()
        root.mainloop()
        return 0
    except ImportError as exc:
        messagebox.showerror(
            "Missing dependency",
            "Run this in the project folder, then start again:\n\n"
            ".\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt\n\n" + str(exc), parent=root)
        return 1
    except (OSError, ValueError) as exc:
        messagebox.showerror(
            "StayLocked — cannot open settings",
            f"Your settings have not been overwritten.\n\n{exc}", parent=root,
        )
        return 1
    finally:
        if app is not None:
            app.close_tray()
        if lock is not None:
            if locked:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            lock.close()
        try:
            root.destroy()
        except tk.TclError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
