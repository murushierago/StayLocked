"""StayLocked desktop editor. The Windows service owns enforcement."""
import ntpath
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .tray import TrayController
from .storage import path_key
from .websites import normalize_domain
from .website_dialog import ask_website
from .session import format_remaining, parse_minutes
from .service_client import launch_session, read_state
from .theme import apply_theme, size_window, palette
from .preferences import THEME_NAMES, load_appearance, save_appearance
from .branding import VERSION, apply_window_icon, make_icon
from .widgets import Surface, TargetList, TimerRing, AutoScrollbar
from .app_icons import AppIcons


class FocusLockWindow:
    # The internal class/module name remains stable for existing integrations.
    def __init__(self, root, store, applications):
        self.root, self.store, self.applications = root, store, applications
        self.websites = store.load_websites()
        selection = store.load_config()
        self.disabled_apps = {path_key(p) for p in selection['disabled_applications']}
        self.disabled_sites = set(selection['disabled_websites'])
        self.busy, self.pending, self.display_session = True, None, None
        self._preview_after_end = False
        self.tray, self.shutting_down, self.hidden_notice_shown = None, False, False
        self.service_missing, self.discovery_dialog, self.appearance_dialog = False, None, None
        self._active_snapshot, self._active_sites = None, None
        self.appearance = load_appearance(store.path)
        root.title(f'StayLocked — {VERSION}')
        apply_theme(root, self.appearance['theme'], self.appearance)
        apply_window_icon(root)
        size_window(root, 1180, 820, (980, 660))
        self.px = lambda n: max(1, round(n * root.focuslock_scale))
        px = self.px
        self.icons, self.surfaces = AppIcons(root), []
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        outer = ttk.Frame(root, padding=px(24))
        outer.grid(row=0, column=0, sticky='nsew')
        outer.rowconfigure(1, weight=1)
        outer.columnconfigure(0, weight=1)
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky='ew', pady=(0, px(25)))
        header.columnconfigure(1, weight=1)
        from PIL import ImageTk
        self.logo = ImageTk.PhotoImage(make_icon(px(58)), master=root)
        ttk.Label(header, image=self.logo).grid(row=0, column=0, rowspan=2, padx=(0, px(13)))
        self.title_label = ttk.Label(header, text='StayLocked', style='Title.TLabel')
        self.title_label.grid(row=0, column=1, sticky='w')
        ttk.Label(header, text='Less noise. More of what matters.', style='Muted.TLabel').grid(row=1, column=1, sticky='w', pady=(px(4), 0))
        self.theme_name = tk.StringVar(value=self.appearance['theme'])
        self.theme_box = ttk.Combobox(header, textvariable=self.theme_name, values=THEME_NAMES, state='readonly', width=11)
        self.theme_box.grid(row=0, column=2, rowspan=2, padx=(px(12), px(8)))
        self.theme_box.bind('<<ComboboxSelected>>', self.change_theme)
        ttk.Button(header, text='Customize', command=self.open_appearance).grid(row=0, column=3, rowspan=2, padx=(0, px(8)))
        self.extension_button = ttk.Button(header, text='Browser setup', command=self.open_extension_setup)
        self.extension_button.grid(row=0, column=4, rowspan=2)
        body = ttk.Frame(outer)
        body.grid(row=1, column=0, sticky='nsew')
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self._build_editor(body)
        self._build_timer(body)
        footer = ttk.Frame(outer)
        footer.grid(row=2, column=0, sticky='ew', pady=(px(17), 0))
        footer.columnconfigure(0, weight=1)
        self.connection_text = tk.StringVar(value='Checking browser connection…')
        ttk.Label(footer, textvariable=self.connection_text, style='Muted.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(footer, text=f'v{VERSION}', style='Muted.TLabel').grid(row=0, column=1)
        self.duration.trace_add('write', self.preview_duration)
        self.apps_query.trace_add('write', lambda *_: self.refresh(self._active_snapshot))
        self.sites_query.trace_add('write', lambda *_: self.refresh_sites(self._active_sites))
        self.switch_tab('apps')
        self.refresh()
        self.refresh_sites()
        self.tray = TrayController()
        root.protocol('WM_DELETE_WINDOW', self.hide_to_tray)
        root.bind('<Button-1>', self.clear_background_selection, add='+')
        root.bind('<Control-f>', self.focus_search)
        self.poll()
        self.pump_tray()

    def _build_editor(self, body):
        px = self.px
        editor = ttk.Frame(body)
        editor.grid(row=0, column=0, sticky='nsew', padx=(0, px(22)))
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(3, weight=1)
        ttk.Label(editor, text='Distractions', style='Heading.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(editor, text='Choose what to pause during your session.', style='Muted.TLabel').grid(row=1, column=0, sticky='w', pady=(px(5), px(18)))
        tabs = ttk.Frame(editor)
        tabs.grid(row=2, column=0, sticky='ew', pady=(0, px(15)))
        self.apps_tab = ttk.Button(tabs, text='Applications', style='Selected.Tab.TButton', command=lambda: self.switch_tab('apps'))
        self.apps_tab.pack(side='left')
        self.sites_tab = ttk.Button(tabs, text='Websites', style='Tab.TButton', command=lambda: self.switch_tab('sites'))
        self.sites_tab.pack(side='left', padx=(px(7), 0))
        self.pages, self.search_entries = {}, {}
        self.apps_query, self.sites_query = tk.StringVar(), tk.StringVar()
        self.selection_summary, self.site_summary = tk.StringVar(), tk.StringVar()
        self.selected_path = tk.StringVar(value='Only enabled apps will be blocked.')
        for name in ('apps', 'sites'):
            page = ttk.Frame(editor)
            page.grid(row=3, column=0, sticky='nsew')
            page.rowconfigure(0, weight=1)
            page.columnconfigure(0, weight=1)
            self.pages[name] = page
            card = Surface(page, padding=14)
            card.grid(row=0, column=0, sticky='nsew')
            self.surfaces.append(card)
            table = card.body
            table.columnconfigure(0, weight=1)
            table.rowconfigure(2, weight=1)
            search = ttk.Frame(table, style='Card.TFrame')
            search.grid(row=0, column=0, sticky='ew', pady=(0, px(12)))
            search.columnconfigure(1, weight=1)
            ttk.Label(search, text='Search', style='CardMuted.TLabel').grid(row=0, column=0, padx=(0, px(9)))
            query = self.apps_query if name == 'apps' else self.sites_query
            entry = ttk.Entry(search, textvariable=query, width=1)
            entry.grid(row=0, column=1, sticky='ew')
            from .website_dialog import control_key, paste_text
            entry.bind('<Control-KeyPress>', lambda event, widget=entry: control_key(event, widget))
            entry.bind('<<Paste>>', lambda event, widget=entry: paste_text(widget))
            entry.bind('<Escape>', lambda event, variable=query: variable.set(''))
            self.search_entries[name] = entry
            ttk.Label(search, textvariable=self.selection_summary if name == 'apps' else self.site_summary,
                      style='CardMuted.TLabel').grid(row=0, column=2, padx=(px(12), 0))
            ttk.Separator(table).grid(row=1, column=0, sticky='ew')
            targets = TargetList(table, self.toggle_apps if name == 'apps' else self.toggle_sites,
                                 self.remove if name == 'apps' else self.remove_website)
            targets.grid(row=2, column=0, sticky='nsew')
            targets.bind('<space>', self.space_apps if name == 'apps' else self.space_sites)
            targets.bind('<Delete>', lambda event, kind=name: self.remove() if kind == 'apps' else self.remove_website())
            targets.bind('<<TreeviewSelect>>', self.selection_changed)
            empty = ttk.Label(targets.canvas, style='CardMuted.TLabel', justify='center', wraplength=px(310))
            ttk.Separator(table).grid(row=3, column=0, sticky='ew', pady=(px(4), px(10)))
            if name == 'apps':
                self.tree, self.apps_empty = targets, empty
                self.path_details = ttk.Label(table, textvariable=self.selected_path, style='CardMuted.TLabel', width=1, anchor='w')
                self.path_details.grid(row=4, column=0, sticky='ew')
            else:
                self.site_list, self.sites_empty = targets, empty
                ttk.Label(table, text='Domains and their subdomains are included.', style='CardMuted.TLabel').grid(row=4, column=0, sticky='w')
            actions = ttk.Frame(page)
            actions.grid(row=1, column=0, sticky='ew', pady=(px(13), 0))
            if name == 'apps':
                self.find_button = ttk.Button(actions, text='+  Find apps', command=self.find_apps)
                self.find_button.pack(side='left')
                self.add_button = ttk.Button(actions, text='Browse .exe', command=self.add)
                self.add_button.pack(side='left', padx=(px(8), 0))
            else:
                self.site_add = ttk.Button(actions, text='+  Add website', command=self.add_website)
                self.site_add.pack(side='left')
        note = Surface(editor, padding=15)
        note.grid(row=4, column=0, sticky='ew', pady=(px(16), 0))
        self.surfaces.append(note)
        note.body.columnconfigure(0, weight=1)
        ttk.Label(note.body, text='Your focus, protected', style='Card.Strong.TLabel').grid(row=0, column=0, sticky='w')
        hint = ttk.Label(note.body, text='Your selection stays blocked until the session ends.', style='CardMuted.TLabel')
        hint.grid(row=1, column=0, sticky='w', pady=(px(5), 0))
        note.body.bind('<Configure>', lambda e: hint.configure(wraplength=max(px(150), e.width - px(5))))

    def _build_timer(self, body):
        px, c, fonts = self.px, palette(self.root), self.root.focuslock_fonts
        card = Surface(body, padding=20)
        card.grid(row=0, column=1, sticky='nsew')
        self.surfaces.append(card)
        panel = card.body
        panel.columnconfigure(0, weight=1, minsize=px(290))
        panel.rowconfigure(1, weight=1, minsize=px(52))
        self.banner = tk.StringVar(value='Checking session…')
        self.banner_label = ttk.Label(panel, textvariable=self.banner, style='Status.TLabel', wraplength=px(290))
        self.banner_label.grid(row=0, column=0, sticky='w')
        self.clock_caption = tk.StringVar(value='TIME REMAINING')
        self.timer = tk.StringVar(value='--:--:--')
        self.progress = TimerRing(panel, self.timer, self.clock_caption)
        self.progress.grid(row=1, column=0, sticky='nsew', pady=(px(7), px(9)))
        self.timer_label = self.progress.label
        ttk.Label(panel, text='Session duration', style='Card.Strong.TLabel').grid(row=2, column=0, sticky='w', pady=(0, px(9)))
        presets = ttk.Frame(panel, style='Card.TFrame')
        presets.grid(row=3, column=0, sticky='ew')
        self.preset_buttons = {}
        for index, minutes in enumerate((25, 45, 60)):
            presets.columnconfigure(index, weight=1, uniform='presets')
            button = ttk.Button(presets, text=f'{minutes} min', style='Card.Chip.TButton',
                                command=lambda value=minutes: self.choose_duration(value))
            button.grid(row=0, column=index, sticky='ew', padx=(0 if index == 0 else px(6), 0))
            self.preset_buttons[minutes] = button
        custom = ttk.Frame(panel, style='Card.TFrame')
        custom.grid(row=4, column=0, sticky='ew', pady=(px(10), px(3)))
        custom.columnconfigure(0, weight=1)
        ttk.Label(custom, text='Minutes · 1–720', style='CardMuted.TLabel').grid(row=0, column=0, sticky='w')
        self.duration = tk.StringVar(value='25')
        self.duration_box = ttk.Combobox(custom, textvariable=self.duration, font=fonts['body'],
                                       values=('15', '25', '45', '60', '90', 'Until restart'), width=13)
        self.duration_box.grid(row=0, column=1, sticky='e', padx=(px(8), 0))
        self.start_button = ttk.Button(panel, text='Start focus session', style='Card.Accent.TButton', command=self.start)
        self.start_button.grid(row=5, column=0, sticky='ew', pady=(px(16), px(12)))
        self.status = tk.StringVar()
        area = ttk.Frame(panel, style='Card.TFrame')
        area.grid(row=6, column=0, sticky='ew')
        area.columnconfigure(0, weight=1)
        area.rowconfigure(0, weight=1)
        self.status_text = tk.Text(area, height=3, width=1, wrap='word', bg=c['card'], fg=c['muted'], relief='flat', borderwidth=0,
                                   highlightthickness=0, state='disabled', font=fonts['small'], cursor='arrow', padx=0, pady=0)
        self.status_text.grid(row=0, column=0, sticky='nsew')
        scroll = AutoScrollbar(area, orient='vertical', command=self.status_text.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.status_text.configure(yscrollcommand=scroll.set)
        self._last_status = None
        self.status.trace_add('write', self.render_status)
        ttk.Separator(panel).grid(row=7, column=0, sticky='ew', pady=px(12))
        self.exit_hint = tk.StringVar(value='Apps unlock when your timer ends.\nRestart your PC for an early exit.')
        hint = ttk.Label(panel, textvariable=self.exit_hint, style='CardMuted.TLabel', wraplength=px(290))
        hint.grid(row=8, column=0, sticky='w')
        panel.bind('<Configure>', lambda e: hint.configure(wraplength=max(px(150), e.width)))

    def focus_search(self, event=None):
        self.search_entries[self.current_tab].focus_set()
        return 'break'

    def choose_duration(self, minutes):
        if not self.busy:
            self.duration.set(str(minutes))

    def update_counts(self):
        apps = self._active_snapshot if self._active_snapshot is not None else self.applications
        sites = self._active_sites if self._active_sites is not None else self.websites
        self.apps_tab.configure(text=f'Applications  {len(apps)}')
        self.sites_tab.configure(text=f'Websites  {len(sites)}')
        self.selection_summary.set(f'{len(apps) if self.busy else len(self.enabled_apps())} selected')
        self.site_summary.set(f'{len(sites) if self.busy else len(self.enabled_sites())} selected')

    def _apply_appearance(self, values):
        apply_theme(self.root, values['theme'], values)
        self.theme_name.set(values['theme'])
        c = palette(self.root)
        self.status_text.configure(bg=c['card'], fg=c['muted'])
        self.tree.repaint()
        self.site_list.repaint()
        self.progress.repaint()
        for surface in self.surfaces:
            surface.repaint()
        # Executable icons have the current card background baked into their bitmap.
        for widget, website in ((self.tree, False), (self.site_list, True)):
            for item in widget.rows.values():
                values = item['values']
                key = values[0] if website else values[2]
                title = values[0] if website else values[1]
                icon = self.icons.get(key, title, website=website)
                item['image'] = icon
                item['icon'].configure(image=icon)

    def save_appearance(self, values):
        self.appearance = save_appearance(values, self.store.path)
        self._apply_appearance(self.appearance)

    def change_theme(self, event=None):
        try:
            self.save_appearance({'theme': self.theme_name.get()})
        except (OSError, ValueError) as exc:
            self.theme_name.set(self.appearance['theme'])
            messagebox.showerror('Could not save appearance', str(exc), parent=self.root)

    def open_appearance(self):
        from .appearance_dialog import AppearanceDialog
        if self.appearance_dialog and self.appearance_dialog.winfo_exists():
            self.appearance_dialog.lift()
            return
        self.appearance_dialog = AppearanceDialog(self.root, self.appearance, self._apply_appearance, self.save_appearance)

    def find_apps(self):
        if self.busy:
            return
        from .app_picker import AppPicker
        if self.discovery_dialog and self.discovery_dialog.winfo_exists():
            self.discovery_dialog.lift()
            return
        self.discovery_dialog = AppPicker(self.root,self.applications,self.add_discovered)

    def add_discovered(self,paths):
        if self.busy:
            return False
        existing = {path_key(p) for p in self.applications}
        new = []
        for path in paths:
            if path_key(path) not in existing:
                new.append(path)
                existing.add(path_key(path))
        return self.commit([*self.applications,*new]) if new else True

    def clear_background_selection(self, event):
        widget = event.widget
        while widget is not None:
            if widget in (self.tree, self.site_list):
                return
            widget = widget.master
        if event.widget.winfo_class() in {'TFrame', 'Frame', 'Canvas', 'TLabel'}:
            for tree in (self.tree, self.site_list):
                tree.selection_remove(*tree.selection())

    def switch_tab(self, name):
        self.current_tab = name
        for key, page in self.pages.items():
            if key == name:
                page.grid()
            else:
                page.grid_remove()
        self.apps_tab.configure(style='Selected.Tab.TButton' if name == 'apps' else 'Tab.TButton')
        self.sites_tab.configure(style='Selected.Tab.TButton' if name == 'sites' else 'Tab.TButton')

    def render_status(self, *_):
        value = self.status.get()
        if value != self._last_status:
            self.status_text.configure(state='normal')
            self.status_text.delete('1.0', 'end')
            self.status_text.insert('1.0', value)
            self.status_text.configure(state='disabled')
            self._last_status = value

    def space_apps(self, event=None):
        self.toggle_apps()
        return 'break'

    def space_sites(self, event=None):
        self.toggle_sites()
        return 'break'

    def refresh_sites(self,items=None):
        self._active_sites = items
        selected = {self.site_list.item(i, 'values')[0] for i in self.site_list.selection()}
        view = self.site_list.canvas.yview()[0]
        self.site_list.clear()
        query = self.sites_query.get().strip().casefold()
        for index,domain in enumerate(self.websites if items is None else items):
            if query and query not in domain.casefold():
                continue
            enabled = items is not None or domain not in self.disabled_sites
            self.site_list.insert_target(index,(domain,'Included' if enabled else 'Skipped', '' if items is not None else '×'),
                                         domain, 'Includes subdomains' if enabled else 'Not in this session', enabled,
                                         self.icons.get(domain, domain, website=True), removable=items is None)
        self.site_list.selection_set([i for i in self.site_list.get_children() if self.site_list.item(i, 'values')[0] in selected])
        self.site_list.canvas.yview_moveto(view)
        if self.site_list.get_children():
            self.sites_empty.place_forget()
        else:
            self.sites_empty.configure(text='No matching websites.\nTry another search.' if query else
                                       'No websites in this session.' if items is not None else
                                       'A quieter browser starts here.\n\nAdd a website to build your list.')
            self.sites_empty.place(relx=.5,rely=.5,anchor='center')
        self.update_counts()

    def open_extension_setup(self):
        try:
            from .extension_setup import launch_setup
            launch_setup()
        except Exception as exc:
            messagebox.showerror('Cannot open browser setup', str(exc), parent=self.root)

    def selection_changed(self, event=None):
        chosen = bool(self.tree.selection())
        if chosen:
            values = self.tree.item(self.tree.selection()[0], 'values')
            self.selected_path.set(values[2])
        else:
            self.selected_path.set('Only enabled apps will be blocked.')

    def controls(self, busy):
        self.busy = busy
        self.add_button.configure(state='disabled' if busy else 'normal')
        self.find_button.configure(state='disabled' if busy else 'normal')
        try:
            self.session_minutes()
            valid_duration = True
        except ValueError:
            valid_duration = False
        self.start_button.configure(state='disabled' if busy or self.service_missing or not valid_duration or not (self.enabled_apps() or self.enabled_sites()) else 'normal',
                                    text=('Session active' if self.display_session else 'Please wait…') if busy else 'Start focus session')
        self.site_add.configure(state='disabled' if busy else 'normal')
        self.duration_box.configure(state='disabled' if busy else 'normal')
        for minutes, button in self.preset_buttons.items():
            button.configure(state='disabled' if busy else 'normal',
                             style='Card.Selected.Chip.TButton' if self.duration.get() == str(minutes) else 'Card.Chip.TButton')
        self.tree.set_locked(busy)
        self.site_list.set_locked(busy)
        self.update_counts()
        self.selection_changed()

    def session_minutes(self):
        value = self.duration.get().strip()
        return None if value == 'Until restart' else parse_minutes(value)

    def preview_duration(self, *_):
        if self.busy:
            return
        self._preview_after_end = True
        try:
            minutes = self.session_minutes()
        except ValueError:
            self.clock_caption.set('TIME REMAINING')
            self.timer.set('--:--:--')
            if hasattr(self, 'start_button'):
                self.controls(False)
            return
        self.clock_caption.set('TIME IN FOCUS' if minutes is None else 'TIME REMAINING')
        self.timer.set('00:00:00' if minutes is None else format_remaining(minutes * 60))
        self.exit_hint.set('Restart Windows to end this session.\nClosing the app keeps it running.' if minutes is None else
                           'Unlocks when your timer ends.\nRestart your PC for an early exit.')
        if hasattr(self, 'start_button'):
            self.controls(False)

    def save_websites(self, candidate):
        try:
            self.store.save_websites(candidate)
        except (ValueError, OSError) as exc:
            messagebox.showerror('Could not save websites', str(exc), parent=self.root)
            return
        self.websites = candidate
        self.disabled_sites.intersection_update(candidate)
        self.refresh_sites()
        self.controls(False)

    def add_website(self):
        if self.busy:
            return
        value = ask_website(self.root)
        if value is None:
            return
        try:
            domain = normalize_domain(value)
            if domain in self.websites:
                raise ValueError('This website is already in your list.')
            self.save_websites([*self.websites, domain])
        except ValueError as exc:
            messagebox.showerror('Invalid website', str(exc), parent=self.root)

    def remove_website(self, indices=None):
        if not self.busy:
            selected = {int(i) for i in (self.site_list.selection() if indices is None else indices)}
            self.save_websites([d for i, d in enumerate(self.websites) if i not in selected])

    def refresh(self,items=None):
        self._active_snapshot = items
        selected = {path_key(self.tree.item(i, 'values')[2]) for i in self.tree.selection()}
        view = self.tree.canvas.yview()[0]
        self.tree.clear()
        query = self.apps_query.get().strip().casefold()
        for index,path in enumerate(self.applications if items is None else items):
            enabled = items is not None or path_key(path) not in self.disabled_apps
            name = ntpath.splitext(ntpath.basename(path))[0]
            if query and query not in (name + ' ' + path).casefold():
                continue
            exists = Path(path).is_file()
            subtitle = 'Ready to block' if exists and enabled else 'Not in this session' if exists else 'File not found'
            if items is not None:
                subtitle = 'Blocked for this session'
            self.tree.insert_target(index,('On' if enabled else 'Off',name,path,
                'Ready' if exists else 'Missing file', '' if items is not None else '×'),
                name, subtitle, enabled, self.icons.get(path, name), removable=items is None)
        self.tree.selection_set([i for i in self.tree.get_children() if path_key(self.tree.item(i, 'values')[2]) in selected])
        self.tree.canvas.yview_moveto(view)
        if self.tree.get_children():
            self.apps_empty.place_forget()
        else:
            self.apps_empty.configure(text='No matching applications.\nTry another search.' if query else
                                      'No apps in this session.\n\nWebsite blocking is still active.' if items is not None else
                                      'Find your distractions.\n\nUse Find apps to build your list.')
            self.apps_empty.place(relx=.5,rely=.5,anchor='center')
        self.selection_changed()
        self.update_counts()

    def commit(self, candidate):
        if self.busy:
            return False
        try:
            self.store.save(candidate)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Could not save', f'The list was not changed.\n\n{exc}', parent=self.root)
            return False
        self.applications = candidate
        self.disabled_apps.intersection_update(path_key(p) for p in candidate)
        self.refresh()
        self.controls(False)
        return True

    def add(self):
        if self.busy:
            return
        selected = filedialog.askopenfilename(
            parent=self.root, title='Select an application executable',
            filetypes=[('Windows applications', '*.exe')])
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != '.exe' or not path.is_file():
            messagebox.showerror('Invalid application', 'Select an existing .exe file.', parent=self.root)
            return
        selected = ntpath.normpath(str(path.resolve()))
        if path_key(selected) in {path_key(p) for p in self.applications}:
            messagebox.showinfo('Already added', 'This application is already in your list.', parent=self.root)
            return
        self.commit([*self.applications, selected])

    def remove(self, indices=None):
        if self.busy:
            return
        selected = {int(i) for i in (self.tree.selection() if indices is None else indices)}
        if selected:
            self.commit([p for i, p in enumerate(self.applications) if i not in selected])

    def enabled_apps(self):
        return [p for p in self.applications if path_key(p) not in self.disabled_apps]

    def enabled_sites(self):
        return [d for d in self.websites if d not in self.disabled_sites]

    def save_toggles(self, disabled_apps, disabled_sites):
        if self.busy:
            return
        try:
            self.store.save_selection([p for p in self.applications if path_key(p) in disabled_apps],
                                      [d for d in self.websites if d in disabled_sites])
        except (ValueError, OSError) as exc:
            messagebox.showerror('Could not save selection', str(exc), parent=self.root)
            return
        self.disabled_apps, self.disabled_sites = disabled_apps, disabled_sites
        self.refresh()
        self.refresh_sites()
        self.controls(False)

    def toggle_apps(self, indices=None):
        if self.busy:
            return
        indices = self.tree.selection() if indices is None else indices
        keys = {path_key(self.applications[int(i)]) for i in indices}
        if not keys:
            return
        disabled = set(self.disabled_apps)
        if keys - disabled:
            disabled.update(keys)
        else:
            disabled.difference_update(keys)
        self.save_toggles(disabled, set(self.disabled_sites))

    def toggle_sites(self, indices=None):
        if self.busy:
            return
        chosen = {self.websites[int(i)] for i in (self.site_list.selection() if indices is None else indices)}
        disabled = set(self.disabled_sites)
        if chosen - disabled:
            disabled.update(chosen)
        else:
            disabled.difference_update(chosen)
        self.save_toggles(set(self.disabled_apps), disabled)

    def start(self):
        if self.busy:
            return
        try:
            minutes = self.session_minutes()
            applications, websites = self.enabled_apps(), self.enabled_sites()
            if websites:
                from .network import require_admin
                require_admin()
            details = ('This session lasts until Windows restarts.\n' if minutes is None else
                       f'This session ends after {minutes} minute(s), or when Windows restarts.\n')
            details += 'Closing StayLocked does not unlock your selection.\n\n'
            if applications:
                details += ('Force end selected app processes (including tray processes):\n'
                            + '\n'.join(ntpath.basename(p) for p in applications)
                            + '\nSave your work: unsaved data may be lost.\n\n')
            if websites:
                details += ('Experimental Windows IP filtering for:\n' + '\n'.join(websites)
                            + '\nThe extension blocks these domains and subdomains when connected.\n'
                            'Windows IP fallback affects all users on this PC; shared IPs can affect other sites.\n\n')
            if not messagebox.askokcancel('Start Focus Mode', details + 'Start this session?', parent=self.root):
                return
            self.controls(True)
            self.pending = launch_session(applications, force_running=True, websites=websites, minutes=minutes)
            self.banner.set('Starting focus session…')
            self.status.set('Checking running applications and acquiring files…')
        except Exception as exc:
            self.controls(False)
            messagebox.showerror('Cannot start Focus Mode', str(exc), parent=self.root)

    def poll(self):
        try:
            state = read_state()
            kind = state.get('state', 'IDLE')
            self.service_missing = kind == 'SERVICE_MISSING'
            if self.pending:
                if state.get('session_id') == self.pending and kind in {'ACTIVE', 'ERROR', 'ENDED'}:
                    self.pending = None
                    if kind == 'ERROR':
                        messagebox.showerror('Focus Mode was not started', state.get('message', 'Service error.'), parent=self.root)
                elif kind in {'IDLE', 'SERVICE_MISSING'}:
                    self.pending = None
                else:
                    kind = 'STARTING'
            busy = kind in {'STARTING', 'ACTIVE'} or self.pending is not None
            self.controls(busy)
            if kind == 'ACTIVE':
                self._preview_after_end = False
                if self.display_session != state['session_id']:
                    self.display_session = state['session_id']
                    self.duration.set(str((state['deadline_ms'] - state['started_ms']) // 60000)
                                      if state.get('mode') == 'timed' else 'Until restart')
                    self.refresh(state['applications'])
                    self.refresh_sites(state.get('websites', []))
                    self.update_counts()
                    if not state['applications'] and state.get('websites'):
                        self.switch_tab('sites')
                self.banner.set('Focus session active')
                self.start_button.configure(text='Session active')
                timed = state.get('mode') == 'timed'
                self.clock_caption.set('TIME REMAINING' if timed else 'TIME IN FOCUS')
                self.timer.set(format_remaining(state.get('remaining_seconds', 0) if timed else state.get('elapsed_seconds', 0)))
                if timed:
                    total = max(1, (state['deadline_ms'] - state['started_ms']) // 1000)
                    self.progress.set(100 * (1 - state['remaining_seconds'] / total))
                else:
                    self.progress.set(100)
                self.exit_hint.set('Unlocks when your timer ends.\nRestart your PC for an early exit.' if timed else
                                   'Restart Windows to end this session.\nClosing the app keeps it running.')
                text = f"{len(state['applications'])} application(s) blocked. "
                if state.get('websites'):
                    text += (f"{len(state['websites'])} website(s) selected. ")
                text += '\nClosing this window keeps the session running.'
                if state.get('website_warning'):
                    text += '\n' + state['website_warning']
                self.status.set(text)
            elif kind == 'STARTING':
                self.banner.set('Preparing your session…')
                self.timer.set('--:--:--')
                self.status.set(state.get('message', 'Please wait. Applications are being checked.'))
            else:
                if self.display_session is not None:
                    self.display_session = None
                    self.refresh()
                    self.refresh_sites()
                self.banner.set('Session complete' if kind == 'ENDED' else 'Ready to focus')
                if kind == 'ENDED' and not self._preview_after_end:
                    self.timer.set('00:00:00')
                    self.progress.set(100)
                else:
                    self.preview_duration()
                    self.progress.set(0)
                messages = {
                    'ENDED': 'Session complete. App and network restrictions are removed.',
                    'INTERRUPTED': 'Previous worker is no longer running. Its temporary restrictions have been released.',
                    'ERROR': state.get('message', 'Session stopped after a service error.'),
                    'SERVICE_MISSING': state.get('message', 'Install the Windows service using the installer.'),
                }
                if kind == 'SERVICE_MISSING':
                    self.banner.set('Install service to start')
                    self.start_button.configure(state='disabled')
                self.status.set(messages.get(kind, 'Choose what to pause and a session length. Only switched-on items will be blocked.'))
        except Exception as exc:
            self.controls(True)
            self.banner.set('Session status unavailable')
            self.status.set(str(exc))
        finally:
            if not self.shutting_down:
                from .extension_setup import recent_connection
                self.connection_text.set('Browser connected' if recent_connection() else 'Browser offline · Connect in Browser setup')
                if self.tray:
                    self.tray.set_title('StayLocked — ' + self.banner.get() + ' ' + self.timer.get())
                self.root.after(500, self.poll)

    def hide_to_tray(self):
        if not self.tray or not self.tray.can_hide():
            messagebox.showinfo('Tray is not ready',
                                'The tray icon is not available yet. The window will remain visible.',
                                parent=self.root)
            return
        self.root.withdraw()
        if not self.hidden_notice_shown:
            self.hidden_notice_shown = True
            self.tray.notify_hidden()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def pump_tray(self):
        if self.shutting_down:
            return
        if self.tray:
            for action, message in self.tray.drain():
                if action == 'open':
                    self.show_window()
                elif action == 'exit':
                    self.exit_interface()
                    return
                elif action == 'error':
                    self.show_window()
                    self.close_tray()
                    self.root.protocol('WM_DELETE_WINDOW', self.exit_interface)
                    messagebox.showwarning('Tray unavailable',
                                           str(message) + '\nThe service is unaffected. '
                                           'Restart the interface to restore the tray.', parent=self.root)
                    break
        if not self.shutting_down:
            self.root.after(150, self.pump_tray)

    def close_tray(self):
        if self.tray:
            tray, self.tray = self.tray, None
            tray.stop()

    def exit_interface(self):
        # The Windows service is deliberately not stopped or signalled here.
        self.shutting_down = True
        self.close_tray()
        self.root.destroy()
