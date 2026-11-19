"""Responsive application discovery dialog. Scan threads never call Tk."""
import tkinter as tk
from tkinter import ttk, messagebox
from queue import Queue, Empty
from threading import Event, Thread
from .discovery import discover
from .storage import path_key
from .session import validate_targets
from .theme import palette, size_window
from .widgets import Surface, SwitchTree


class AppPicker(tk.Toplevel):
    def __init__(self,parent,existing,on_add,scanner=discover):
        super().__init__(parent)
        self.title('StayLocked — Find applications')
        self.transient(parent)
        self.configure(bg=palette(parent)['bg'])
        self.focuslock_scale = parent.focuslock_scale
        size_window(self,860,620,(740,550))
        self.on_add,self.scanner = on_add,scanner
        self.existing = {path_key(p) for p in existing}
        self.chosen = set()
        self.candidates,self.visible = [],{}
        self.events,self.cancelled = Queue(),Event()
        self.closed,self.scanning = False,False
        self.after_id = None
        px = lambda n:max(1,round(n*self.focuslock_scale))
        self.rowconfigure(0,weight=1)
        self.columnconfigure(0,weight=1)
        outer = ttk.Frame(self,padding=px(22))
        outer.grid(row=0,column=0,sticky='nsew')
        outer.columnconfigure(0,weight=1)
        outer.rowconfigure(3,weight=1)
        ttk.Label(outer,text='Find your applications',style='Heading.TLabel').grid(row=0,column=0,sticky='w')
        ttk.Label(outer,text='Select the apps you want in your list. Nothing is closed or blocked here.',style='Muted.TLabel').grid(row=1,column=0,sticky='w',pady=(px(6),px(14)))
        search = ttk.Frame(outer)
        search.grid(row=2,column=0,sticky='ew',pady=(0,px(12)))
        search.columnconfigure(1,weight=1)
        ttk.Label(search,text='Search',style='Muted.TLabel').grid(row=0,column=0,padx=(0,px(12)))
        self.query = tk.StringVar()
        self.entry = ttk.Entry(search,textvariable=self.query)
        self.entry.grid(row=0,column=1,sticky='ew')
        from .website_dialog import control_key, paste_text
        self.entry.bind('<Control-KeyPress>',lambda event:control_key(event,self.entry))
        self.entry.bind('<<Paste>>',lambda event:paste_text(self.entry))
        self.query.trace_add('write',lambda *_:self.render())
        self.rescan = ttk.Button(search,text='Scan again',command=self.scan)
        self.rescan.grid(row=0,column=2,padx=(px(10),0))
        card = Surface(outer,padding=8)
        card.grid(row=3,column=0,sticky='nsew')
        card.body.rowconfigure(0,weight=1)
        card.body.columnconfigure(0,weight=1)
        self.tree = SwitchTree(card.body,columns=('name','status'),height=1,selectmode='extended')
        self.tree.heading('#0',text='ADD')
        self.tree.heading('name',text='APPLICATION',anchor='w')
        self.tree.heading('status',text='STATUS',anchor='w')
        self.tree.column('name',width=px(320),minwidth=px(190),stretch=True)
        self.tree.column('status',width=px(140),minwidth=px(130),stretch=False)
        self.tree.grid(row=0,column=0,sticky='nsew')
        scrollbar = ttk.Scrollbar(card.body,command=self.tree.yview)
        scrollbar.grid(row=0,column=1,sticky='ns')
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind('<Button-1>',self.clicked)
        self.tree.bind('<space>',self.toggle_selection)
        self.tree.bind('<Double-Button-1>',self.toggle_selection)
        self.tree.bind('<<TreeviewSelect>>',self.selection_changed)
        self.empty = ttk.Label(card.body,text='Looking for installed applications…',style='CardMuted.TLabel',justify='center')
        self.empty.place(relx=.5,rely=.5,anchor='center')
        self.path = tk.StringVar(value='Select a row to inspect its .exe path.')
        ttk.Entry(outer,textvariable=self.path,state='readonly').grid(row=4,column=0,sticky='ew',pady=(px(10),px(8)))
        self.message = tk.StringVar(value='Starting scan…')
        self.message_label = ttk.Label(outer,textvariable=self.message,style='Muted.TLabel',wraplength=px(740))
        self.message_label.grid(row=5,column=0,sticky='w')
        footer = ttk.Frame(outer)
        footer.grid(row=6,column=0,sticky='ew',pady=(px(16),0))
        footer.columnconfigure(0,weight=1)
        self.count = tk.StringVar(value='0 selected')
        ttk.Label(footer,textvariable=self.count,style='Muted.TLabel').grid(row=0,column=0,sticky='w')
        ttk.Button(footer,text='Cancel',command=self.close).grid(row=0,column=1,padx=px(8))
        self.add_button = ttk.Button(footer,text='Add selected',style='Accent.TButton',command=self.add,state='disabled')
        self.add_button.grid(row=0,column=2)
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.bind('<Escape>',lambda _:self.close())
        self.grab_set()
        self.entry.focus_set()
        self.scan()
        self.poll()

    def scan(self):
        if self.scanning or self.closed:
            return
        self.scanning = True
        self.rescan.configure(state='disabled')
        self.message.set('Scanning running apps, registered apps and Start-menu shortcuts…')
        def work():
            try:
                result,warnings = self.scanner(self.cancelled,
                    lambda apps,stage,notes:self.events.put(('progress',apps,stage,notes)))
                self.events.put(('done',result,'',warnings))
            except Exception as exc:
                self.events.put(('error',[],str(exc),[]))
        Thread(target=work,name='StayLocked-app-discovery',daemon=True).start()

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                kind,apps,stage,warnings = self.events.get_nowait()
                if kind in ('progress','done'):
                    self.candidates = apps
                    available = {path_key(a.path) for a in apps}
                    if kind=='done':
                        self.chosen.intersection_update(available)
                    self.render()
                if kind=='progress':
                    self.message.set(f'{len(apps)} apps found · Reading {stage.lower()}…')
                else:
                    self.scanning = False
                    self.render()
                    self.rescan.configure(state='normal')
                    if kind=='error':
                        self.message.set('Scan failed: '+stage+' Use Browse .exe in the main window.')
                    else:
                        self.message.set(f'{len(apps)} apps found. '+
                            ('Some sources were unavailable. ' if warnings else '')+
                            'Missing an app? Open it and scan again, or use Browse .exe.')
        except Empty:
            pass
        self.after_id = self.after(80,self.poll)

    def render(self):
        selected = {path_key(self.visible[i].path) for i in self.tree.selection() if i in self.visible}
        self.tree.clear()
        self.visible = {}
        query = self.query.get().strip().casefold()
        for index,app in enumerate(self.candidates):
            if query and query not in (app.name+' '+app.path).casefold():
                continue
            key,iid = path_key(app.path),str(index)
            self.visible[iid] = app
            status = 'Already added' if key in self.existing else 'Running' if app.running else 'Installed'
            enabled = key in self.chosen or key in self.existing
            self.tree.insert_switch(iid,(app.name,status),enabled)
            if key in selected:
                self.tree.selection_add(iid)
        if self.visible:
            self.empty.place_forget()
        else:
            self.empty.configure(text='No matching applications.' if query else
                                 'Looking for installed applications…' if self.scanning else 'No desktop applications found.\nUse Browse .exe to add one manually.')
            self.empty.place(relx=.5,rely=.5,anchor='center')
        self.count.set(f'{len(self.chosen)} selected')
        self.add_button.configure(state='normal' if self.chosen else 'disabled')
        self.selection_changed()

    def selection_changed(self,event=None):
        selection = self.tree.selection()
        app = self.visible.get(selection[0]) if selection else None
        self.path.set(app.path if app else 'Select a row to inspect its .exe path.')

    def clicked(self,event):
        if self.tree.identify_column(event.x)=='#0':
            iid = self.tree.identify_row(event.y)
            if iid:
                self.toggle([iid])
                return 'break'

    def toggle_selection(self,event=None):
        self.toggle(self.tree.selection())
        return 'break'

    def toggle(self,rows):
        keys = {path_key(self.visible[i].path) for i in rows if i in self.visible}-self.existing
        if keys-self.chosen:
            self.chosen.update(keys)
        else:
            self.chosen.difference_update(keys)
        self.render()

    def add(self):
        paths = [a.path for a in self.candidates if path_key(a.path) in self.chosen]
        if not paths:
            return
        try:
            # Recheck existence, resolved paths and protected targets at click time.
            validated = [str(p) for p in validate_targets(paths)]
        except (OSError,ValueError) as exc:
            messagebox.showerror('Cannot add selected application',str(exc)+'\n\nScan again or deselect that app.',parent=self)
            return
        if self.on_add(validated):
            self.close()

    def close(self):
        self.closed = True
        self.cancelled.set()
        if self.after_id:
            self.after_cancel(self.after_id)
        self.grab_release()
        self.destroy()
