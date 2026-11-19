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
from .preferences import THEME_NAMES, load_theme, save_theme
from .branding import VERSION, apply_window_icon, make_icon
from .widgets import Surface, SwitchTree, ProgressLine


class FocusLockWindow:
    # The internal class/module name remains stable for existing integrations.
    def __init__(self,root,store,applications):
        self.root,self.store = root,store
        self.applications = applications
        self.websites = store.load_websites()
        selection = store.load_config()
        self.disabled_apps = {path_key(p) for p in selection['disabled_applications']}
        self.disabled_sites = set(selection['disabled_websites'])
        self.busy,self.pending,self.display_session = True,None,None
        self._preview_after_end = False
        self.tray,self.shutting_down,self.hidden_notice_shown = None,False,False
        self._active_snapshot = None
        self.service_missing = False
        self.discovery_dialog = None
        root.title(f'StayLocked — {VERSION}')
        apply_theme(root,load_theme(store.path))
        apply_window_icon(root)
        size_window(root,1120,730,(980,660))
        px = lambda n:max(1,round(n*root.focuslock_scale))
        fonts,c = root.focuslock_fonts,palette(root)
        root.rowconfigure(0,weight=1)
        root.columnconfigure(0,weight=1)
        outer = ttk.Frame(root,padding=px(24))
        outer.grid(row=0,column=0,sticky='nsew')
        outer.rowconfigure(1,weight=1)
        outer.columnconfigure(0,weight=1)
        header = ttk.Frame(outer)
        header.grid(row=0,column=0,sticky='ew',pady=(0,px(24)))
        header.columnconfigure(1,weight=1)
        from PIL import ImageTk
        self.logo = ImageTk.PhotoImage(make_icon(px(56)),master=root)
        ttk.Label(header,image=self.logo).grid(row=0,column=0,rowspan=2,sticky='w',padx=(0,px(12)))
        self.title_label = ttk.Label(header,text='StayLocked',style='Title.TLabel')
        self.title_label.grid(row=0,column=1,sticky='w')
        ttk.Label(header,text='Less noise. More of what matters.',style='Muted.TLabel').grid(row=1,column=1,sticky='w')
        appearance = ttk.Frame(header)
        appearance.grid(row=0,column=2,rowspan=2,padx=px(12))
        ttk.Label(appearance,text='APPEARANCE',style='Muted.TLabel').pack(anchor='w',pady=(0,px(3)))
        self.theme_name = tk.StringVar(value=root.staylocked_theme)
        self.theme_box = ttk.Combobox(appearance,textvariable=self.theme_name,values=THEME_NAMES,state='readonly',width=11)
        self.theme_box.pack()
        self.theme_box.bind('<<ComboboxSelected>>',self.change_theme)
        self.extension_button = ttk.Button(header,text='Browser setup',command=self.open_extension_setup)
        self.extension_button.grid(row=0,column=3,rowspan=2,sticky='e')
        body = ttk.Frame(outer)
        body.grid(row=1,column=0,sticky='nsew')
        body.rowconfigure(0,weight=1)
        body.columnconfigure(0,weight=1)
        editor = ttk.Frame(body)
        editor.grid(row=0,column=0,sticky='nsew',padx=(0,px(20)))
        editor.rowconfigure(1,weight=1)
        editor.columnconfigure(0,weight=1)
        tabs = ttk.Frame(editor)
        tabs.grid(row=0,column=0,sticky='ew',pady=(0,px(14)))
        self.apps_tab = ttk.Button(tabs,text='Applications',style='Selected.Tab.TButton',command=lambda:self.switch_tab('apps'))
        self.apps_tab.pack(side='left')
        self.sites_tab = ttk.Button(tabs,text='Websites',style='Tab.TButton',command=lambda:self.switch_tab('sites'))
        self.sites_tab.pack(side='left',padx=(px(8),0))
        self.pages = {}
        for name in ('apps','sites'):
            page = ttk.Frame(editor)
            page.grid(row=1,column=0,sticky='nsew')
            page.columnconfigure(0,weight=1)
            page.rowconfigure(1,weight=1)
            self.pages[name] = page
        apps,sites = self.pages['apps'],self.pages['sites']
        self.selection_summary = tk.StringVar(value='Choose what belongs in this session.')
        ttk.Label(apps,textvariable=self.selection_summary,style='Muted.TLabel').grid(row=0,column=0,sticky='w',pady=(0,px(10)))
        table_card = Surface(apps,padding=8)
        table_card.grid(row=1,column=0,sticky='nsew')
        table = table_card.body
        table.rowconfigure(0,weight=1)
        table.columnconfigure(0,weight=1)
        self.tree = SwitchTree(table,columns=('enabled','name','path','status','delete'),displaycolumns=('name','status','delete'),selectmode='extended',height=1)
        for column,title,width in (('name','APPLICATION',250),('status','STATUS',100)):
            self.tree.heading(column,text=title,anchor='w')
            self.tree.column(column,width=px(width),minwidth=px(70),stretch=column=='name')
        self.tree.heading('delete', text='')
        self.tree.column('delete', width=px(36), minwidth=px(36), stretch=False, anchor='center')
        self.tree.grid(row=0,column=0,sticky='nsew')
        scroll = ttk.Scrollbar(table,orient='vertical',command=self.tree.yview)
        scroll.grid(row=0,column=1,sticky='ns')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>',self.selection_changed)
        self.tree.bind('<Delete>',lambda event:self.remove())
        self.tree.bind('<Button-1>',self.toggle_clicked)
        self.tree.bind('<space>',self.space_apps)
        self.tree.bind('<Control-a>',self.select_all_apps)
        self.apps_empty = ttk.Label(table,text='Find your distractions.\n\nUse Find apps to build your list.',style='CardMuted.TLabel',justify='center')
        self.selected_path = tk.StringVar(value='Select an app to see its executable path.')
        ttk.Entry(apps,textvariable=self.selected_path,state='readonly').grid(row=2,column=0,sticky='ew',pady=(px(10),px(12)))
        actions = ttk.Frame(apps)
        actions.grid(row=3,column=0,sticky='ew')
        self.find_button = ttk.Button(actions,text='Find apps',style='Accent.TButton',command=self.find_apps)
        self.find_button.pack(side='left')
        self.add_button = ttk.Button(actions,text='Browse .exe',command=self.add)
        self.add_button.pack(side='left',padx=px(6))
        ttk.Label(sites,text='Choose domains. Subdomains are included.',style='Muted.TLabel').grid(row=0,column=0,sticky='w',pady=(0,px(10)))
        site_card = Surface(sites,padding=8)
        site_card.grid(row=1,column=0,sticky='nsew')
        site_table = site_card.body
        site_table.rowconfigure(0,weight=1)
        site_table.columnconfigure(0,weight=1)
        self.site_list = SwitchTree(site_table,columns=('domain','status','delete'),selectmode='extended',height=1)
        self.site_list.heading('domain',text='WEBSITE',anchor='w')
        self.site_list.heading('status',text='SESSION',anchor='w')
        self.site_list.column('domain',width=px(240),minwidth=px(150),stretch=True)
        self.site_list.column('status',width=px(110),minwidth=px(95),stretch=False)
        self.site_list.heading('delete', text='')
        self.site_list.column('delete', width=px(36), minwidth=px(36), stretch=False, anchor='center')
        self.site_list.grid(row=0,column=0,sticky='nsew')
        site_scroll = ttk.Scrollbar(site_table,orient='vertical',command=self.site_list.yview)
        site_scroll.grid(row=0,column=1,sticky='ns')
        self.site_list.configure(yscrollcommand=site_scroll.set)
        self.sites_empty = ttk.Label(site_table,text='A quieter browser starts here.\n\nAdd a domain, such as youtube.com.',style='CardMuted.TLabel',justify='center')
        ttk.Label(sites,text='Click a switch or select rows and press Space.',style='Muted.TLabel').grid(row=2,column=0,sticky='w',pady=(px(18),px(20)))
        actions = ttk.Frame(sites)
        actions.grid(row=3,column=0,sticky='ew')
        self.site_add = ttk.Button(actions,text='Add website',style='Accent.TButton',command=self.add_website)
        self.site_add.pack(side='left')
        self.site_list.bind('<Button-1>',self.site_toggle_clicked)
        self.site_list.bind('<space>',self.space_sites)
        self.site_list.bind('<Delete>',lambda event:self.remove_website())
        self.site_list.bind('<<TreeviewSelect>>',self.selection_changed)
        panel_card = Surface(body,padding=20)
        panel_card.grid(row=0,column=1,sticky='nsew')
        panel = panel_card.body
        panel.columnconfigure(0,weight=1,minsize=px(265))
        panel.rowconfigure(7,weight=1,minsize=px(62))
        self.banner = tk.StringVar(value='CHECKING SESSION')
        self.banner_label = ttk.Label(panel,textvariable=self.banner,style='Status.TLabel',wraplength=px(265))
        self.banner_label.grid(row=0,column=0,sticky='w')
        self.clock_caption = tk.StringVar(value='TIME REMAINING')
        ttk.Label(panel,textvariable=self.clock_caption,style='CardMuted.TLabel').grid(row=1,column=0,sticky='w',pady=(px(12),px(4)))
        self.timer = tk.StringVar(value='--:--:--')
        self.timer_label = ttk.Label(panel,textvariable=self.timer,style='Timer.TLabel')
        self.timer_label.grid(row=2,column=0,sticky='w',pady=(0,px(8)))
        self.progress = ProgressLine(panel)
        self.progress.grid(row=3,column=0,sticky='ew',pady=(0,px(16)))
        ttk.Label(panel,text='Session length / minutes',style='CardMuted.TLabel').grid(row=4,column=0,sticky='w')
        self.duration = tk.StringVar(value='25')
        self.duration_box = ttk.Combobox(panel,textvariable=self.duration,font=fonts['body'],
                                       values=('1','15','25','50','90','Until restart'),width=12)
        self.duration_box.grid(row=5,column=0,sticky='ew',pady=(px(7),px(8)))
        self.start_button = ttk.Button(panel,text='START FOCUS MODE',style='Card.Accent.TButton',command=self.start)
        self.start_button.grid(row=6,column=0,sticky='ew',pady=(px(8),px(14)))
        self.status = tk.StringVar()
        area = ttk.Frame(panel,style='Card.TFrame')
        area.grid(row=7,column=0,sticky='nsew')
        self.status_text = tk.Text(area,height=3,width=26,wrap='word',bg=c['card'],fg=c['muted'],relief='flat',borderwidth=0,
                                   highlightthickness=0,state='disabled',font=fonts['body'])
        status_scroll = ttk.Scrollbar(area,orient='vertical',command=self.status_text.yview)
        status_scroll.pack(side='right',fill='y')
        self.status_text.configure(yscrollcommand=status_scroll.set)
        self.status_text.pack(side='left',fill='both',expand=True)
        self._last_status = None
        self.status.trace_add('write',self.render_status)
        ttk.Separator(panel).grid(row=8,column=0,sticky='ew',pady=px(9))
        self.exit_hint = tk.StringVar(value='Unlocks when your timer ends.\nRestart your PC for an early exit.')
        ttk.Label(panel,textvariable=self.exit_hint,style='CardMuted.TLabel').grid(row=9,column=0,sticky='w')
        footer = ttk.Frame(outer)
        footer.grid(row=2,column=0,sticky='ew',pady=(px(18),0))
        footer.columnconfigure(0,weight=1)
        self.connection_text = tk.StringVar(value='Browser connection: checking…')
        ttk.Label(footer,textvariable=self.connection_text,style='Muted.TLabel').grid(row=0,column=0,sticky='w')
        ttk.Label(footer,text=f'v{VERSION}',style='Muted.TLabel').grid(row=0,column=1,padx=px(16))
        self.surfaces = [table_card,site_card,panel_card]
        self.duration.trace_add('write',self.preview_duration)
        self.switch_tab('apps')
        self.refresh()
        self.refresh_sites()
        self.tray = TrayController()
        self.root.protocol('WM_DELETE_WINDOW',self.hide_to_tray)
        self.root.bind('<Button-1>', self.clear_background_selection, add='+')
        for tree in (self.tree, self.site_list):
            tree.bind('<Motion>', self.row_cursor)
            tree.bind('<Leave>', lambda event: event.widget.configure(cursor=''))
        self.poll()
        self.pump_tray()

    def change_theme(self,event=None):
        name = self.theme_name.get()
        try:
            save_theme(name,self.store.path)
        except (OSError,ValueError) as exc:
            self.theme_name.set(self.root.staylocked_theme)
            messagebox.showerror('Could not save appearance',str(exc),parent=self.root)
            return
        apply_theme(self.root,name)
        c = palette(self.root)
        self.status_text.configure(bg=c['card'],fg=c['muted'])
        self.tree.repaint()
        self.site_list.repaint()
        self.progress.repaint()
        for surface in self.surfaces:
            surface.repaint()

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
        if event.widget.winfo_class() in {'TFrame', 'Frame', 'Canvas', 'TLabel'}:
            for tree in (self.tree, self.site_list):
                tree.selection_remove(*tree.selection())

    def row_cursor(self, event):
        tree = event.widget
        actionable = (not self.busy and tree.identify_row(event.y)
                      and tree.identify_column(event.x) in {'#0', '#3'})
        tree.configure(cursor='hand2' if actionable else '')

    def list_clicked(self, tree, event, toggle, remove):
        row = tree.identify_row(event.y)
        if not row:
            tree.selection_remove(*tree.selection())
            return 'break'
        if self.busy:
            return None
        column = tree.identify_column(event.x)
        if column == '#0':
            toggle([row])
            return 'break'
        if column == '#3':
            remove([row])
            return 'break'

    def site_toggle_clicked(self, event):
        return self.list_clicked(self.site_list, event, self.toggle_sites, self.remove_website)

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

    def select_all_apps(self, event=None):
        self.tree.selection_set(self.tree.get_children())
        return 'break'

    def refresh_sites(self,items=None):
        self.site_list.clear()
        for index,domain in enumerate(self.websites if items is None else items):
            enabled = items is not None or domain not in self.disabled_sites
            self.site_list.insert_switch(index,(domain,'Included' if enabled else 'Skipped', '' if items is not None else '×'),enabled)
        if self.site_list.get_children():
            self.sites_empty.place_forget()
        else:
            self.sites_empty.configure(text='No websites in this session.' if items is not None else
                                       'A quieter browser starts here.\n\nAdd a domain, such as youtube.com.')
            self.sites_empty.place(relx=.5,rely=.5,anchor='center')

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
            self.selected_path.set('Select an app to see its executable path.')

    def controls(self, busy):
        self.busy = busy
        self.add_button.configure(state='disabled' if busy else 'normal')
        self.find_button.configure(state='disabled' if busy else 'normal')
        self.start_button.configure(state='disabled' if busy or self.service_missing or not (self.enabled_apps() or self.enabled_sites()) else 'normal',
                                    text=('SESSION ACTIVE' if self.display_session else 'PLEASE WAIT…') if busy else 'START FOCUS MODE')
        self.site_add.configure(state='disabled' if busy else 'normal')
        self.duration_box.configure(state='disabled' if busy else 'normal')
        if not busy:
            self.selection_summary.set(f'Apps enabled: {len(self.enabled_apps())}   ·   Websites enabled: {len(self.enabled_sites())}')
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
            return
        self.clock_caption.set('TIME IN FOCUS' if minutes is None else 'TIME REMAINING')
        self.timer.set('00:00:00' if minutes is None else format_remaining(minutes * 60))
        self.exit_hint.set('Restart Windows to end this session.\nClosing the app keeps it running.' if minutes is None else
                           'Unlocks when your timer ends.\nRestart your PC for an early exit.')

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
        self.tree.clear()
        for index,path in enumerate(self.applications if items is None else items):
            enabled = items is not None or path_key(path) not in self.disabled_apps
            name = ntpath.splitext(ntpath.basename(path))[0]
            self.tree.insert_switch(index,('On' if enabled else 'Off',name,path,
                'Ready' if Path(path).is_file() else 'Missing file', '' if items is not None else '×'),enabled)
        if self.tree.get_children():
            self.apps_empty.place_forget()
        else:
            self.apps_empty.configure(text='No apps in this session.\n\nWebsite blocking is still active.' if items is not None else
                                      'Find your distractions.\n\nUse Find apps to build your list.')
            self.apps_empty.place(relx=.5,rely=.5,anchor='center')
        self.selection_changed()

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

    def toggle_clicked(self, event):
        return self.list_clicked(self.tree, event, self.toggle_apps, self.remove)

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
            self.banner.set('STARTING FOCUS MODE…')
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
                    self.selection_summary.set('Session active · Your selection is locked.')
                    if not state['applications'] and state.get('websites'):
                        self.switch_tab('sites')
                self.banner.set('FOCUS MODE ACTIVE')
                self.start_button.configure(text='SESSION ACTIVE')
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
                self.banner.set('PREPARING / FINISHING SESSION…')
                self.timer.set('--:--:--')
                self.status.set(state.get('message', 'Please wait. Applications are being checked.'))
            else:
                if self.display_session is not None:
                    self.display_session = None
                    self.refresh()
                    self.refresh_sites()
                self.banner.set('SESSION COMPLETE' if kind == 'ENDED' else 'READY TO FOCUS')
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
                    self.banner.set('INSTALL SERVICE TO START')
                    self.start_button.configure(state='disabled')
                self.status.set(messages.get(kind, 'Choose what to pause and a session length. Only switched-on items will be blocked.'))
        except Exception as exc:
            self.controls(True)
            self.banner.set('CANNOT READ SESSION STATUS')
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
