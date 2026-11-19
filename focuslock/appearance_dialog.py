"""Live cosmetic preview, with explicit apply, cancel and restore defaults."""
import tkinter as tk
from tkinter import ttk, messagebox

from .preferences import CHOICES, DEFAULT_APPEARANCE
from .theme import palette, size_window
from .widgets import Surface


class AppearanceDialog(tk.Toplevel):
    def __init__(self, parent, current, preview, save):
        super().__init__(parent)
        self.title('StayLocked — Appearance')
        self.transient(parent)
        self.original = dict(current)
        self.preview, self.save, self.closed = preview, save, False
        self.focuslock_scale = parent.focuslock_scale
        self.configure(bg=palette(parent)['bg'])
        size_window(self, 610, 570, (550, 540))
        self.resizable(False, False)
        px = lambda n: max(1, round(n * self.focuslock_scale))
        outer = ttk.Frame(self, padding=px(24))
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(0, weight=1)
        ttk.Label(outer, text='Make room for your style', style='Heading.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(outer, text='Preview changes instantly. Your focus session keeps running.', style='Muted.TLabel').grid(row=1, column=0, sticky='w', pady=(px(6), px(20)))
        card = Surface(outer, padding=18)
        card.grid(row=2, column=0, sticky='ew')
        card.body.columnconfigure(0, weight=1)
        self.variables, self.selectors, self.card = {}, {}, card
        fields = (
            ('theme', 'Theme', 'Choose the background and surface colors.'),
            ('accent', 'Accent color', 'Highlight switches and your main action.'),
            ('density', 'List spacing', 'More breathing room or more rows at once.'),
            ('timer_style', 'Timer style', 'A progress ring or a simple, quiet clock.'),
        )
        for index, (key, title, detail) in enumerate(fields):
            row = ttk.Frame(card.body, style='Card.TFrame')
            row.grid(row=index, column=0, sticky='ew', pady=(0 if index == 0 else px(17), 0))
            row.columnconfigure(0, weight=1)
            ttk.Label(row, text=title, style='Card.Strong.TLabel').grid(row=0, column=0, sticky='w')
            ttk.Label(row, text=detail, style='CardMuted.TLabel').grid(row=1, column=0, sticky='w', pady=(px(4), 0))
            variable = tk.StringVar(value=current[key])
            selector = ttk.Combobox(row, textvariable=variable, values=CHOICES[key], state='readonly', width=15)
            selector.grid(row=0, column=1, rowspan=2, padx=(px(15), 0))
            selector.bind('<<ComboboxSelected>>', self.changed)
            self.variables[key], self.selectors[key] = variable, selector
        ttk.Label(outer, text='Appearance is saved on this computer.', style='Muted.TLabel').grid(row=3, column=0, sticky='w', pady=px(16))
        footer = ttk.Frame(outer)
        footer.grid(row=4, column=0, sticky='ew', pady=(px(4), 0))
        footer.columnconfigure(0, weight=1)
        ttk.Button(footer, text='Restore defaults', command=self.reset).grid(row=0, column=0, sticky='w')
        ttk.Button(footer, text='Cancel', command=self.cancel).grid(row=0, column=1, padx=px(8))
        ttk.Button(footer, text='Apply', style='Accent.TButton', command=self.apply).grid(row=0, column=2)
        self.protocol('WM_DELETE_WINDOW', self.cancel)
        self.bind('<Escape>', lambda _: self.cancel())
        self.bind('<Return>', lambda _: self.apply())
        self.grab_set()
        self.selectors['theme'].focus_set()

    def values(self):
        return {key: value.get() for key, value in self.variables.items()}

    def changed(self, event=None):
        self.preview(self.values())
        self.configure(bg=palette(self)['bg'])
        self.card.repaint()

    def reset(self):
        for key, value in DEFAULT_APPEARANCE.items():
            self.variables[key].set(value)
        self.changed()

    def apply(self):
        try:
            self.save(self.values())
        except (OSError, ValueError) as exc:
            messagebox.showerror('Could not save appearance', str(exc), parent=self)
            return
        self.close()

    def cancel(self):
        self.preview(self.original)
        self.close()

    def close(self):
        self.closed = True
        self.grab_release()
        self.destroy()
