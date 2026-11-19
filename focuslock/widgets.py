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


class ProgressLine(tk.Canvas):
    def __init__(self,master):
        self.value = 0
        self.scale = master._root().focuslock_scale
        super().__init__(master,height=max(4,round(4*self.scale)),width=1,
                         borderwidth=0,highlightthickness=0)
        self.bind('<Configure>',self.repaint)
        self.repaint()

    def set(self,value):
        self.value = max(0,min(100,float(value)))
        self.repaint()

    def repaint(self,event=None):
        c = palette(self)
        self.configure(bg=c['card'])
        self.delete('all')
        h,w = self.winfo_reqheight(),max(self.winfo_width(),4)
        self.create_line(h/2,h/2,w-h/2,h/2,fill=c['raised'],width=h,capstyle='round')
        if self.value:
            self.create_line(h/2,h/2,max(h/2,(w-h)*self.value/100+h/2),h/2,
                             fill=c['accent'],width=h,capstyle='round')
