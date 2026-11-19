"""Website input with explicit clipboard actions and Windows layout-independent keys."""
import tkinter as tk
from tkinter import simpledialog, ttk


def paste_text(entry):
    try:
        value = entry.clipboard_get()
    except tk.TclError:
        entry.bell()
        return 'break'
    # Read first: unavailable clipboard must not erase the current selection.
    if entry.selection_present():
        entry.delete('sel.first', 'sel.last')
    entry.insert('insert', value)
    return 'break'


def control_key(event, entry):
    # Windows VK codes identify physical shortcuts even on Russian/Ukrainian layouts.
    if event.keycode == 0x56:
        return paste_text(entry)
    if event.keycode == 0x41:
        entry.selection_range(0, 'end')
        entry.icursor('end')
        return 'break'
    return None


class WebsiteDialog(simpledialog.Dialog):
    def body(self, master):
        from .theme import palette
        BG = palette(self)['bg']
        self.configure(bg=BG)
        master.configure(bg=BG, padx=14, pady=10)
        ttk.Label(master, text='Domain or URL (e.g. youtube.com):').pack(anchor='w', pady=5)
        self.entry = ttk.Entry(master, width=55)
        self.entry.pack(fill='x', pady=5)
        self.entry.bind('<Control-KeyPress>', lambda event: control_key(event, self.entry))
        self.entry.bind('<<Paste>>', lambda event: paste_text(self.entry))
        self.entry.bind('<Shift-Insert>', lambda event: paste_text(self.entry))
        ttk.Button(master, text='Paste from clipboard',
                   command=lambda: paste_text(self.entry)).pack(anchor='w', pady=5)
        self.menu = tk.Menu(self.entry, tearoff=False)
        self.menu.add_command(label='Paste', command=lambda: paste_text(self.entry))
        self.menu.add_command(label='Copy', command=lambda: self.entry.event_generate('<<Copy>>'))
        self.menu.add_command(label='Cut', command=lambda: self.entry.event_generate('<<Cut>>'))
        self.entry.bind('<Button-3>', self.popup)
        return self.entry

    def buttonbox(self):
        box = ttk.Frame(self, padding=(18, 4, 18, 16))
        ttk.Button(box, text='Add website', style='Accent.TButton', command=self.ok).pack(side='left')
        ttk.Button(box, text='Cancel', command=self.cancel).pack(side='left', padx=8)
        box.pack(fill='x')
        self.bind('<Return>', self.ok)
        self.bind('<Escape>', self.cancel)

    def popup(self, event):
        self.entry.focus_set()
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
            self.grab_set()  # Restore the modal dialog's grab after the context menu.
        return 'break'

    def apply(self):
        self.result = self.entry.get()


def ask_website(parent):
    return WebsiteDialog(parent, title='Add Website').result
