"""Small native Tk widgets: rounded surfaces and keyboard-accessible row switches."""
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk
from .theme import palette


class Surface(tk.Frame):
    def __init__(self, master, padding=16, **kwargs):
        self.root = master._root()
        self.px = lambda n: max(1,round(n*self.root.focuslock_scale))
        super().__init__(master,borderwidth=0,highlightthickness=0,**kwargs)
        self.background = tk.Canvas(self,borderwidth=0,highlightthickness=0)
        self.background.place(x=0,y=0,relwidth=1,relheight=1)
        self.body = ttk.Frame(self,style='Card.TFrame')
        self.body.pack(fill='both',expand=True,padx=self.px(padding),pady=self.px(padding))
        self.bind('<Configure>',self.repaint)
        self.repaint()

    def repaint(self,event=None):
        c = palette(self)
        self.configure(bg=c['bg'])
        self.background.configure(bg=c['bg'])
        w,h = max(2,self.winfo_width()),max(2,self.winfo_height())
        # Only the small border/corner surface is painted; content remains native.
        image = Image.new('RGBA',(w*2,h*2),c['bg'])
        ImageDraw.Draw(image).rounded_rectangle((0,0,w*2-1,h*2-1),radius=self.px(18)*2,
                                                fill=c['card'],outline=c['border'],width=2)
        self._image = ImageTk.PhotoImage(image.resize((w,h),Image.Resampling.LANCZOS),master=self)
        self.background.delete('all')
        self.background.create_image(0,0,anchor='nw',image=self._image)


class SwitchTree(ttk.Treeview):
    """A switch image in column #0; values and selection stay accessible as text.

    Space toggles selected rows through the controller. Images never encode the
    session state; the saved enabled list remains the source of truth.
    """
    def __init__(self,master,**kwargs):
        super().__init__(master,show='tree headings',**kwargs)
        self.states = {}
        self.heading('#0',text='USE')
        scale = self._root().focuslock_scale
        self.column('#0',width=round(78*scale),minwidth=round(78*scale),stretch=False,anchor='center')
        self.repaint()

    def repaint(self):
        c,scale = palette(self),self._root().focuslock_scale
        self.images = {}
        for enabled in (True,False):
            w,h = round(70*scale),round(30*scale)
            image = Image.new('RGBA',(w*3,h*3))
            d = ImageDraw.Draw(image)
            box = [round(v*scale*3) for v in (14,3,56,27)]
            d.rounded_rectangle(box,radius=round(12*scale*3),fill=c['accent'] if enabled else c['off'])
            x = 35 if enabled else 18
            d.ellipse(tuple(round(v*scale*3) for v in (x,7,x+16,23)),
                      fill=c['accent_text'] if enabled else '#ffffff')
            self.images[enabled] = ImageTk.PhotoImage(image.resize((w,h),Image.Resampling.LANCZOS),master=self)
        self.tag_configure('muted',foreground=c['muted'])
        for iid,enabled in list(self.states.items()):
            if self.exists(iid):
                self.item(iid,image=self.images[enabled])

    def insert_switch(self,iid,values,enabled):
        self.states[str(iid)] = bool(enabled)
        self.insert('','end',iid=str(iid),image=self.images[bool(enabled)],values=values,
                    tags=() if enabled else ('muted',))

    def clear(self):
        children = self.get_children()
        if children:
            self.delete(*children)
        self.states.clear()


class AutoScrollbar(ttk.Scrollbar):
    """Take no space until the content actually overflows."""
    def set(self, first, last):
        if float(first) <= 0 and float(last) >= 1:
            self.grid_remove()
        else:
            self.grid()
        super().set(first, last)


class TimerRing(tk.Canvas):
    """A service-driven clock. The drawing never owns or decrements a timer."""
    def __init__(self, master, variable, caption):
        self.variable, self.caption, self.value = variable, caption, 0
        self.scale = master._root().focuslock_scale
        super().__init__(master, height=round(236 * self.scale), width=1, highlightthickness=0, borderwidth=0)
        # Native text remains selectable by assistive tooling; Canvas only paints the ring.
        self.label = ttk.Label(self, style='Timer.TLabel', anchor='center')
        self.caption_label = ttk.Label(self, style='CardMuted.TLabel', anchor='center')
        self._traces = [(v, v.trace_add('write', self.repaint)) for v in (variable, caption)]
        self.bind('<Configure>', self.repaint)
        self.bind('<Destroy>', self._destroyed, add='+')
        self.repaint()

    def _destroyed(self, event):
        if event.widget is self:
            for variable, token in self._traces:
                variable.trace_remove('write', token)

    def set(self, value):
        self.value = max(0, min(100, float(value)))
        self.repaint()

    def repaint(self, *_):
        c, root = palette(self), self._root()
        self.configure(bg=c['card'])
        self.delete('all')
        w, h = max(1, self.winfo_width()), max(1, self.winfo_height())
        ring = root.staylocked_appearance.get('timer_style', 'Ring') == 'Ring'
        diameter = min(w - 16 * self.scale, h - 8 * self.scale, 264 * self.scale)
        if ring and diameter >= 110 * self.scale:
            x, y = (w - diameter) / 2, (h - diameter) / 2
            width = max(4, round(7 * self.scale))
            self.create_oval(x, y, x + diameter, y + diameter, outline=c['border'], width=width)
            sweep = max(8, self.value * 3.6)
            self.create_arc(x, y, x + diameter, y + diameter, start=90, extent=-min(359.9, sweep),
                            outline=c['ring'], width=width, style='arc')
        text = self.variable.get()
        if text.startswith('00:'):
            text = text[3:]
        if text == '--:--:--':
            text = '--:--'
        # Long (hour+) sessions still fit in the ring and at the minimum window size.
        max_width = max(80, diameter * .81 if ring else w - 20 * self.scale)
        face = root.focuslock_fonts['timer']
        requested = max(24, min(54, diameter / self.scale * .205))
        size = min(requested, requested * max_width / max(1, face.measure(text)) * 48 / requested)
        self._clock_font = (face.actual('family'), -max(20, round(size * self.scale)), 'bold')
        self.label.configure(text=text, font=self._clock_font)
        label_height = min(h, round(66 * self.scale))
        label_width = min(w - 16 * self.scale, diameter * .8) if ring else w - 16 * self.scale
        self.label.place(relx=.5, rely=.46, anchor='center', width=max(1, round(label_width)), height=label_height)
        self.caption_label.configure(text='ELAPSED' if self.caption.get() == 'TIME IN FOCUS' else 'REMAINING')
        if h >= 90 * self.scale:
            self.caption_label.place(relx=.5, rely=.46, y=round(40 * self.scale), anchor='center')
        else:
            self.caption_label.place_forget()


class TargetList(ttk.Frame):
    """Scrollable native rows with real labels, checkbuttons and remove buttons.

    Stable row IDs are the original list indices even while searching. Highlight
    and the saved block switch are intentionally independent. A small Treeview-
    compatible selection API keeps the controller and keyboard behavior shared.
    """
    def __init__(self, master, on_toggle, on_remove):
        super().__init__(master, style='Card.TFrame', takefocus=True)
        self.on_toggle, self.on_remove = on_toggle, on_remove
        self.rows, self._selected, self._anchor = {}, [], None
        self.locked = False
        self.px = lambda n: max(1, round(n * self._root().focuslock_scale))
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, width=1, height=1, borderwidth=0, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.content = ttk.Frame(self.canvas, style='Card.TFrame')
        self.content.columnconfigure(0, weight=1)
        self._window = self.canvas.create_window(0, 0, anchor='nw', window=self.content)
        self.scrollbar = AutoScrollbar(self, orient='vertical', command=self.canvas.yview)
        self.scrollbar.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.content.bind('<Configure>', self._resize_content)
        self.canvas.bind('<Configure>', self._resize_canvas)
        self.canvas.bind('<Button-1>', self._background_click)
        self.bind('<Button-1>', self._click)
        self.bind('<Up>', lambda e: self._navigate(-1, e))
        self.bind('<Down>', lambda e: self._navigate(1, e))
        self.bind('<Home>', lambda e: self._navigate(-len(self.rows), e))
        self.bind('<End>', lambda e: self._navigate(len(self.rows), e))
        self.bind('<Control-a>', lambda e: self._select_all())
        self.bind('<MouseWheel>', self._wheel)
        self.canvas.bind('<MouseWheel>', self._wheel)
        self.canvas.bind('<Button-4>', lambda e: self.canvas.yview_scroll(-2, 'units'))
        self.canvas.bind('<Button-5>', lambda e: self.canvas.yview_scroll(2, 'units'))
        self.repaint()

    def _resize_content(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def _resize_canvas(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)

    def _wheel(self, event):
        delta = -1 if event.delta > 0 else 1
        if self.canvas.yview() != (0.0, 1.0):
            self.canvas.yview_scroll(delta * max(1, abs(event.delta) // 120) * 2, 'units')
        return 'break'

    def _background_click(self, event=None):
        self.selection_remove(*self._selected)
        self.focus_set()
        return 'break'

    def _click(self, event):
        # Also supports synthetic/native clicks on the list's own coordinate space.
        row = self.identify_row(event.y)
        if not row:
            return self._background_click()
        column = self.identify_column(event.x)
        if not self.locked and column == '#0':
            self.on_toggle([row])
        elif not self.locked and column == '#3':
            self.on_remove([row])
        else:
            self._select(row, event)
        return 'break'

    def _select(self, iid, event=None):
        iid = str(iid)
        self.focus_set()
        state = getattr(event, 'state', 0)
        if state & 1 and self._anchor in self.rows:
            order = list(self.rows)
            first, last = sorted((order.index(self._anchor), order.index(iid)))
            self.selection_set(order[first:last + 1])
        elif state & 4:
            if iid in self._selected:
                self.selection_remove(iid)
            else:
                self.selection_add(iid)
            self._anchor = iid
        else:
            self.selection_set(iid)
            self._anchor = iid
        return 'break'

    def _navigate(self, step, event):
        if self.rows:
            order = list(self.rows)
            current = order.index(self._selected[-1]) if self._selected else (-1 if step > 0 else len(order))
            iid = order[max(0, min(len(order) - 1, current + step))]
            self._select(iid, event)
            self.see(iid)
        return 'break'

    def _select_all(self):
        self.selection_set(list(self.rows))
        return 'break'

    def insert_target(self, iid, values, title, subtitle, enabled, icon=None, removable=True):
        iid = str(iid)
        row = ttk.Frame(self.content, style='Card.TFrame', padding=(self.px(8), self.px(9)))
        row.grid(row=len(self.rows) * 2, column=0, sticky='ew')
        row.columnconfigure(1, weight=1)
        image = ttk.Label(row, image=icon, style='Card.TLabel')
        image.grid(row=0, column=0, rowspan=2, padx=(self.px(3), self.px(14)))
        title_label = ttk.Label(row, text=title, style='Card.Strong.TLabel', width=1, anchor='w')
        title_label.grid(row=0, column=1, sticky='ew')
        subtitle_label = ttk.Label(row, text=subtitle, style='CardMuted.TLabel', width=1, anchor='w')
        subtitle_label.grid(row=1, column=1, sticky='ew', pady=(self.px(3), 0))
        variable = tk.BooleanVar(value=enabled)
        switch = ttk.Checkbutton(row, text='Block ' + title, variable=variable, style='Target.TCheckbutton',
                                 image=(self.switch_images[False], 'selected', self.switch_images[True]),
                                 command=lambda key=iid: self.on_toggle([key]), takefocus=True)
        switch.grid(row=0, column=2, rowspan=2, padx=(self.px(12), self.px(8)))
        delete = ttk.Button(row, text='×', width=2, style='Card.Icon.TButton',
                            command=lambda key=iid: self.on_remove([key]), takefocus=True)
        if removable:
            delete.grid(row=0, column=3, rowspan=2)
        line = ttk.Separator(self.content)
        line.grid(row=len(self.rows) * 2 + 1, column=0, sticky='ew', padx=self.px(8))
        self.rows[iid] = dict(frame=row, values=tuple(values), title=title_label, subtitle=subtitle_label,
                              icon=image, image=icon, switch=switch, variable=variable, delete=delete, line=line)
        for widget in (row, image, title_label, subtitle_label):
            widget.bind('<Button-1>', lambda e, key=iid: self._select(key, e))
        for widget in (row, image, title_label, subtitle_label, switch, delete):
            widget.bind('<MouseWheel>', self._wheel)
            widget.bind('<Button-4>', lambda e: self.canvas.yview_scroll(-2, 'units'))
            widget.bind('<Button-5>', lambda e: self.canvas.yview_scroll(2, 'units'))
        self._style_row(iid)
        for control in (switch, delete):
            control.configure(state='disabled' if self.locked else 'normal')

    def _style_row(self, iid):
        item = self.rows[iid]
        prefix = 'Selected.' if iid in self._selected else 'Card.'
        item['frame'].configure(style=prefix + 'TFrame')
        item['icon'].configure(style=prefix + 'TLabel')
        item['title'].configure(style=prefix + 'Strong.TLabel')
        item['subtitle'].configure(style=prefix + 'Muted.TLabel')
        compact = self._root().staylocked_appearance.get('density') == 'Compact'
        item['frame'].configure(padding=(self.px(8), self.px(5 if compact else 12)))
        if compact:
            item['subtitle'].grid_remove()
        else:
            item['subtitle'].grid()

    def repaint(self):
        c = palette(self)
        self.canvas.configure(bg=c['card'])
        self.switch_images = {}
        for enabled in (True, False):
            w, h = self.px(44), self.px(26)
            image = Image.new('RGBA', (w * 3, h * 3))
            d = ImageDraw.Draw(image)
            d.rounded_rectangle((0, 3, w * 3 - 1, h * 3 - 4), radius=h * 1.5,
                                fill=c['accent'] if enabled else c['off'])
            x = w * 3 - h * 3 + 12 if enabled else 12
            d.ellipse((x, 12, x + h * 3 - 24, h * 3 - 12), fill=c['accent_text'] if enabled else '#edf0f7')
            self.switch_images[enabled] = ImageTk.PhotoImage(image.resize((w, h), Image.Resampling.LANCZOS), master=self)
        style = ttk.Style(self)
        style.layout('Target.TCheckbutton', [('Checkbutton.focus', {'sticky': 'nswe', 'children': [
            ('Checkbutton.padding', {'sticky': 'nswe', 'children': [('Checkbutton.label', {'sticky': 'nswe'})]})]})])
        style.configure('Target.TCheckbutton', background=c['card'], padding=0, focuscolor=c['accent'])
        style.map('Target.TCheckbutton', background=[('active', c['card'])])
        for iid, row in self.rows.items():
            row['switch'].configure(image=(self.switch_images[False], 'selected', self.switch_images[True]))
            self._style_row(iid)

    def set_locked(self, locked):
        if self.locked == bool(locked):
            return
        self.locked = bool(locked)
        for item in self.rows.values():
            for control in ('switch', 'delete'):
                item[control].configure(state='disabled' if locked else 'normal')

    def clear(self):
        for item in self.rows.values():
            item['frame'].destroy()
            item['line'].destroy()
        self.rows.clear()
        self._selected.clear()
        self._anchor = None

    def get_children(self):
        return tuple(self.rows)

    def selection(self):
        return tuple(self._selected)

    def _ids(self, rows):
        if len(rows) == 1 and isinstance(rows[0], (tuple, list, set)):
            rows = rows[0]
        return [str(i) for i in rows if str(i) in self.rows]

    def selection_set(self, *rows):
        self._selected = self._ids(rows)
        self._selection_changed()

    def selection_add(self, *rows):
        self._selected = list(dict.fromkeys([*self._selected, *self._ids(rows)]))
        self._selection_changed()

    def selection_remove(self, *rows):
        remove = set(self._ids(rows))
        self._selected = [i for i in self._selected if i not in remove]
        self._selection_changed()

    def _selection_changed(self):
        for iid in self.rows:
            self._style_row(iid)
        self.event_generate('<<TreeviewSelect>>')

    def item(self, iid, option=None):
        values = self.rows[str(iid)]['values']
        return values if option == 'values' else {'values': values}

    def exists(self, iid):
        return str(iid) in self.rows

    def identify_row(self, y):
        for iid, item in self.rows.items():
            top = item['frame'].winfo_rooty() - self.winfo_rooty()
            if top <= y < top + item['frame'].winfo_height():
                return iid
        return ''

    def identify_column(self, x):
        if not self.rows:
            return ''
        item = next(iter(self.rows.values()))
        for name, column in (('switch', '#0'), ('delete', '#3')):
            widget = item[name]
            start = widget.winfo_rootx() - self.winfo_rootx()
            if widget.winfo_ismapped() and start <= x < start + widget.winfo_width():
                return column
        return '#1'

    def bbox(self, iid, column=None):
        item = self.rows[str(iid)]
        widget = item['delete'] if column == 'delete' else item['switch'] if column in ('#0', 'enabled') else item['frame']
        return (widget.winfo_rootx() - self.winfo_rootx(), widget.winfo_rooty() - self.winfo_rooty(), widget.winfo_width(), widget.winfo_height())

    def see(self, iid):
        self.update_idletasks()
        item = self.rows[str(iid)]['frame']
        height = max(1, self.content.winfo_height())
        top, bottom = item.winfo_y(), item.winfo_y() + item.winfo_height()
        first, last = self.canvas.yview()
        if top < first * height:
            self.canvas.yview_moveto(top / height)
        elif bottom > last * height:
            self.canvas.yview_moveto((bottom - self.canvas.winfo_height()) / height)
