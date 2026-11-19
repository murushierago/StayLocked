"""Shared, high-contrast palettes with pixel-scaled fonts and rounded ttk buttons."""
from tkinter import ttk, font
from .preferences import THEME_NAMES

PALETTES = {
    'Midnight': dict(bg='#101218', card='#1b1e28', raised='#272b39', text='#f3f4fa', muted='#a8afc2',
                     accent='#c2f28b', accent_text='#1b2b0e', hover='#d6ffa7', selected='#333e31',
                     border='#323746', button='#2b3040', button_hover='#3b4359', off='#50596e'),
    'Light': dict(bg='#f3f4f8', card='#ffffff', raised='#eef0f6', text='#202637', muted='#58627a',
                  accent='#6550d8', accent_text='#ffffff', hover='#7561eb', selected='#e5e0fb',
                  border='#dce0eb', button='#e5e8f1', button_hover='#d6dbea', off='#7c879c'),
    'Violet': dict(bg='#171321', card='#231c32', raised='#302641', text='#faf4ff', muted='#c0accf',
                   accent='#ceb2ff', accent_text='#302044', hover='#e0cfff', selected='#443457',
                   border='#443352', button='#3b2e4e', button_hover='#503e68', off='#746183'),
    'Ocean': dict(bg='#0b1920', card='#122831', raised='#1b3742', text='#ebfbff', muted='#9fbdc8',
                  accent='#78dedb', accent_text='#0a3033', hover='#abf3ee', selected='#24484f',
                  border='#2c4652', button='#233f4b', button_hover='#305464', off='#587985'),
}
# Defaults only. Live widgets use palette(widget).
BG, CARD, TEXT, MUTED, ACCENT, BORDER = (PALETTES['Midnight'][k] for k in ('bg','card','text','muted','accent','border'))


def palette(widget):
    return getattr(widget._root(), 'staylocked_palette', PALETTES['Midnight'])


def _rounded_buttons(root, style, c, px):
    import tkinter as tk
    from PIL import Image, ImageDraw, ImageTk
    for name, normal, hover, foreground in (
        ('TButton',c['button'],c['button_hover'],c['text']),
        ('Accent.TButton',c['accent'],c['hover'],c['accent_text']),
        ('Card.Accent.TButton',c['accent'],c['hover'],c['accent_text']),
        ('Tab.TButton',c['bg'],c['button'],c['muted']),
        ('Selected.Tab.TButton',c['selected'],c['selected'],c['accent']),
    ):
        background = c['card'] if name.startswith('Card.') else c['bg']
        images = []
        for fill in (normal,hover,c['raised']):
            n = px(32)
            image = Image.new('RGBA',(n*3,n*3),background)
            ImageDraw.Draw(image).rounded_rectangle((0,0,n*3-1,n*3-1),radius=px(9)*3,fill=fill)
            images.append(ImageTk.PhotoImage(image.resize((n,n),Image.Resampling.LANCZOS),master=root))
        element = 'StayLocked.'+name
        if element not in style.element_names():
            style.element_create(element,'image',images[0],('disabled',images[2]),('active',images[1]),
                                 border=px(8),sticky='nsew')
        else:
            # Retain Tcl image names referenced by the style element.
            old = root.staylocked_button_images[name]
            for before, after in zip(old,images):
                root.tk.call(str(before),'copy',str(after),'-compositingrule','set')
            images = old
        root.staylocked_button_images[name] = images
        style.layout(name,[(element,{'sticky':'nsew','children':[
            ('Button.focus',{'sticky':'nsew','children':[
                ('Button.padding',{'sticky':'nsew','children':[('Button.label',{'sticky':'nsew'})]})]})]})])
        style.configure(name,background=background,foreground=foreground,borderwidth=0,
                        font=root.focuslock_fonts['strong' if name!='TButton' else 'body'],
                        padding=(px(12),px(4)),focusthickness=1,focuscolor=c['accent'])
        style.map(name,foreground=[('disabled',c['muted'])],background=[('disabled',background),('active',background)])


def apply_theme(root, name='Midnight'):
    name = name if name in PALETTES else 'Midnight'
    c = PALETTES[name]
    root.staylocked_palette, root.staylocked_theme = c, name
    root.configure(bg=c['bg'])
    if not hasattr(root,'focuslock_scale'):
        requested = float(root.tk.call('tk','scaling'))/(96/72)
        root.focuslock_scale = max(.8,min(requested,1.75,root.winfo_screenwidth()/1120,
                                         (root.winfo_screenheight()-80)/700))
    px = lambda value: max(1,round(value*root.focuslock_scale))
    if not hasattr(root,'focuslock_fonts'):
        available = {n.lower():n for n in font.families(root)}
        family = next((available[n] for n in ('segoe ui','dejavu sans','helvetica') if n in available),'TkDefaultFont')
        mono = next((available[n] for n in ('consolas','dejavu sans mono','courier') if n in available),family)
        for n in ('TkDefaultFont','TkTextFont','TkMenuFont','TkHeadingFont'):
            font.nametofont(n,root).configure(family=family,size=-px(14))
        root.focuslock_fonts = {
            n:font.Font(root=root,family=face,size=-px(size),weight=weight)
            for n,size,weight,face in (
                ('body',14,'normal',family),('small',12,'normal',family),('strong',14,'bold',family),
                ('heading',19,'bold',family),('title',30,'bold',family),('timer',43,'bold',mono))}
        root.staylocked_button_images = {}
    f = root.focuslock_fonts
    for key,value in (('background',c['card']),('foreground',c['text']),
                      ('selectBackground',c['selected']),('selectForeground',c['text'])):
        root.option_add('*TCombobox*Listbox.'+key,value)
    s = ttk.Style(root)
    if s.theme_use()!='clam':
        s.theme_use('clam')
    s.configure('.',background=c['bg'],foreground=c['text'],font=f['body'])
    for prefix,bg in (('',c['bg']),('Card.',c['card']),('Raised.',c['raised'])):
        s.configure(prefix+'TFrame',background=bg)
        s.configure(prefix+'TLabel',background=bg,foreground=c['text'],font=f['body'])
    for name,fg,bg,face in (
        ('Title',c['text'],c['bg'],'title'),('Heading',c['text'],c['bg'],'heading'),
        ('Muted',c['muted'],c['bg'],'small'),('CardMuted',c['muted'],c['card'],'small'),
        ('CardHeading',c['text'],c['card'],'heading'),('Status',c['accent'],c['card'],'strong'),
        ('Timer',c['text'],c['card'],'timer'),('Chip',c['accent'],c['bg'],'small')):
        s.configure(name+'.TLabel',foreground=fg,background=bg,font=f[face])
    _rounded_buttons(root,s,c,px)
    s.configure('Card.Accent.TButton',background=c['card'])
    s.map('Card.Accent.TButton',background=[('disabled',c['card']),('active',c['card'])])
    s.configure('Treeview',background=c['card'],fieldbackground=c['card'],foreground=c['text'],
                borderwidth=0,rowheight=px(58),font=f['body'],bordercolor=c['card'],
                lightcolor=c['card'],darkcolor=c['card'],relief='flat',indent=0)
    s.map('Treeview',background=[('selected',c['selected'])],foreground=[('selected',c['text'])])
    s.layout('Treeview',[('Treeview.treearea',{'sticky':'nswe'})])
    s.layout('Treeview.Item',[('Treeitem.padding',{'sticky':'nswe','children':[
        ('Treeitem.image',{'side':'left','sticky':'w'}),('Treeitem.text',{'sticky':'nswe'})]})])
    s.configure('Treeview.Heading',background=c['card'],foreground=c['muted'],font=f['small'],
                relief='flat',borderwidth=0,padding=(px(12),px(13)))
    s.map('Treeview.Heading',background=[('active',c['card'])])
    s.configure('TEntry',fieldbackground=c['raised'],foreground=c['text'],insertcolor=c['text'],
                bordercolor=c['border'],lightcolor=c['border'],darkcolor=c['border'],padding=px(9))
    s.map('TEntry',fieldbackground=[('readonly',c['card'])],foreground=[('readonly',c['muted'])])
    s.configure('TCombobox',fieldbackground=c['raised'],background=c['raised'],foreground=c['text'],
                arrowcolor=c['muted'],bordercolor=c['border'],lightcolor=c['border'],darkcolor=c['border'],padding=px(8))
    s.map('TCombobox',fieldbackground=[('readonly',c['raised']),('disabled',c['card'])],
          foreground=[('readonly',c['text']),('disabled',c['muted'])])
    for orientation in ('Vertical','Horizontal'):
        s.configure(orientation+'.TScrollbar',background=c['border'],troughcolor=c['card'],
                    borderwidth=0,arrowcolor=c['muted'],arrowsize=px(10),bordercolor=c['card'],
                    lightcolor=c['card'],darkcolor=c['card'])
        s.map(orientation+'.TScrollbar',background=[('active',c['off'])])
    s.configure('Focus.Horizontal.TProgressbar',background=c['accent'],troughcolor=c['raised'],
                borderwidth=0,lightcolor=c['accent'],darkcolor=c['accent'],thickness=px(4))
    s.configure('TSeparator',background=c['border'])
    return s


def size_window(root,width,height,minimum=(940,660)):
    scale = getattr(root,'focuslock_scale',1)
    max_width,max_height = root.winfo_screenwidth()-40,root.winfo_screenheight()-80
    root.minsize(min(round(minimum[0]*scale),max_width),min(round(minimum[1]*scale),max_height))
    root.geometry(f'{min(round(width*scale),max_width)}x{min(round(height*scale),max_height)}')
