"""Shared palettes, readable pixel-scaled fonts and native rounded controls."""
from tkinter import ttk, font

PALETTES = {
    'Midnight': dict(bg='#101116', card='#191b23', raised='#22252f', text='#f4f4f7', muted='#a8adbd',
                     accent='#c3f589', accent_text='#17220e', hover='#d2faa6', selected='#2d382b',
                     border='#303440', button='#232630', button_hover='#303540', off='#555b6b', ring='#ad8aff'),
    'Light': dict(bg='#f2f3f7', card='#ffffff', raised='#f0f1f6', text='#202435', muted='#5d657a',
                  accent='#6953d9', accent_text='#ffffff', hover='#7a64e7', selected='#eeeafb',
                  border='#dce0e9', button='#e6e8f0', button_hover='#dadee9', off='#7c8496', ring='#6953d9'),
    'Violet': dict(bg='#17131f', card='#221c2e', raised='#30263f', text='#faf4ff', muted='#bcaccb',
                   accent='#d0b4ff', accent_text='#2a1c3d', hover='#e0cfff', selected='#413153',
                   border='#40324e', button='#352943', button_hover='#49365e', off='#72607e', ring='#c7a0ff'),
    'Ocean': dict(bg='#0c181e', card='#13272f', raised='#1d3540', text='#edfaff', muted='#a1bdc8',
                  accent='#83e2da', accent_text='#0b2b30', hover='#a7f2eb', selected='#24474c',
                  border='#2b4550', button='#203944', button_hover='#2e4e59', off='#5c7b86', ring='#83e2da'),
}
ACCENTS = dict(Lime='#c3f589', Violet='#b79aff', Mint='#83e2c5', Blue='#88b9ff', Rose='#f5a2be', Amber='#f3ca7b')
BG, CARD, TEXT, MUTED, ACCENT, BORDER = (PALETTES['Midnight'][k] for k in ('bg', 'card', 'text', 'muted', 'accent', 'border'))


def blend(a, b, amount):
    channels = lambda color: tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    return '#' + ''.join(f'{round(x * (1 - amount) + y * amount):02x}' for x, y in zip(channels(a), channels(b)))


def contrasting_text(color):
    def linear(value):
        value = value / 255
        return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
    rgb = [linear(int(color[i:i + 2], 16)) for i in (1, 3, 5)]
    luminance = sum(a * b for a, b in zip(rgb, (.2126, .7152, .0722)))
    return '#12151c' if (luminance + .05) / .05 >= 1.05 / (luminance + .05) else '#ffffff'


def contrast_ratio(first, second):
    def luminance(color):
        rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        return sum(w * (v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4)
                   for w, v in zip((.2126, .7152, .0722), rgb))
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + .05) / (low + .05)


def appearance_palette(name, appearance=None):
    c = dict(PALETTES.get(name, PALETTES['Midnight']))
    accent = (appearance or {}).get('accent')
    if accent in ACCENTS:
        c['accent'] = ACCENTS[accent]
        c['accent_text'] = contrasting_text(c['accent'])
        c['hover'] = blend(c['accent'], '#ffffff', .18)
        c['selected'] = blend(c['card'], c['accent'], .16)
        c['ring'] = c['accent']
    # A light accent remains a light button, but its text/stroke variant must
    # remain readable on light cards and selected tabs as well.
    c['accent_ink'] = c['accent']
    for _ in range(20):
        if contrast_ratio(c['accent_ink'], c['selected']) >= 4.5:
            break
        c['accent_ink'] = blend(c['accent_ink'], c['text'], .15)
    if contrast_ratio(c['ring'], c['card']) < 3:
        c['ring'] = c['accent_ink']
    return c


def palette(widget):
    return getattr(widget._root(), 'staylocked_palette', PALETTES['Midnight'])


def _rounded_buttons(root, style, c, px):
    from PIL import Image, ImageDraw, ImageTk
    variants = (
        ('TButton', c['bg'], c['button'], c['button_hover'], c['text']),
        ('Accent.TButton', c['bg'], c['accent'], c['hover'], c['accent_text']),
        ('Tab.TButton', c['bg'], c['bg'], c['button'], c['muted']),
        ('Selected.Tab.TButton', c['bg'], c['selected'], c['selected'], c['accent_ink']),
        ('Card.TButton', c['card'], c['raised'], c['button_hover'], c['text']),
        ('Card.Accent.TButton', c['card'], c['accent'], c['hover'], c['accent_text']),
        ('Card.Chip.TButton', c['card'], c['raised'], c['button_hover'], c['muted']),
        ('Card.Selected.Chip.TButton', c['card'], c['selected'], c['selected'], c['accent_ink']),
        ('Card.Icon.TButton', c['card'], c['card'], c['raised'], c['muted']),
    )
    for name, background, normal, hover, foreground in variants:
        images = []
        for fill in (normal, hover, c['raised']):
            n = px(32)
            image = Image.new('RGBA', (n * 3, n * 3), background)
            draw = ImageDraw.Draw(image)
            outlined = 'Chip.' in name
            draw.rounded_rectangle((0, 0, n * 3 - 1, n * 3 - 1), radius=px(9) * 3,
                                   fill=fill, outline=c['accent_ink'] if 'Selected.Chip' in name else c['border'] if outlined else fill,
                                   width=3)
            images.append(ImageTk.PhotoImage(image.resize((n, n), Image.Resampling.LANCZOS), master=root))
        element = 'StayLocked.' + name
        if element not in style.element_names():
            style.element_create(element, 'image', images[0], ('disabled', images[2]), ('active', images[1]), border=px(8), sticky='nsew')
        else:
            old = root.staylocked_button_images[name]
            for before, after in zip(old, images):
                root.tk.call(str(before), 'copy', str(after), '-compositingrule', 'set')
            images = old
        root.staylocked_button_images[name] = images
        style.layout(name, [(element, {'sticky': 'nsew', 'children': [
            ('Button.focus', {'sticky': 'nsew', 'children': [
                ('Button.padding', {'sticky': 'nsew', 'children': [('Button.label', {'sticky': 'nsew'})]})]})]})])
        strong = any(value in name for value in ('Accent', 'Selected'))
        padding = (px(10), px(5)) if 'Chip' in name or 'Icon' in name else (px(17), px(10))
        style.configure(name, background=background, foreground=foreground, borderwidth=0,
                        font=root.focuslock_fonts['strong' if strong else 'body'], padding=padding,
                        focusthickness=1, focuscolor=c['accent'], width=0)
        style.map(name, foreground=[('disabled', c['muted'])], background=[('disabled', background), ('active', background)])


def apply_theme(root, name='Midnight', appearance=None):
    name = name if name in PALETTES else 'Midnight'
    appearance = dict(appearance or getattr(root, 'staylocked_appearance', {}))
    appearance['theme'] = name
    c = appearance_palette(name, appearance)
    root.staylocked_palette, root.staylocked_theme, root.staylocked_appearance = c, name, appearance
    root.configure(bg=c['bg'])
    if not hasattr(root, 'focuslock_scale'):
        requested = float(root.tk.call('tk', 'scaling')) / (96 / 72)
        root.focuslock_scale = max(.75, min(requested, 1.75, root.winfo_screenwidth() / 1160,
                                           (root.winfo_screenheight() - 80) / 730))
    px = lambda value: max(1, round(value * root.focuslock_scale))
    if not hasattr(root, 'focuslock_fonts'):
        available = {n.lower(): n for n in font.families(root)}
        family = next((available[n] for n in ('segoe ui', 'inter', 'dejavu sans', 'helvetica') if n in available), 'TkDefaultFont')
        mono = next((available[n] for n in ('consolas', 'dejavu sans mono', 'courier') if n in available), family)
        for n in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
            font.nametofont(n, root).configure(family=family, size=-px(14))
        root.focuslock_fonts = {
            n: font.Font(root=root, family=face, size=-px(size), weight=weight)
            for n, size, weight, face in (
                ('body', 14, 'normal', family), ('small', 12, 'normal', family), ('strong', 14, 'bold', family),
                ('heading', 23, 'bold', family), ('title', 29, 'bold', family), ('timer', 48, 'bold', mono))}
        root.staylocked_button_images = {}
    f = root.focuslock_fonts
    for key, value in (('background', c['card']), ('foreground', c['text']), ('selectBackground', c['selected']), ('selectForeground', c['text'])):
        root.option_add('*TCombobox*Listbox.' + key, value)
    s = ttk.Style(root)
    if s.theme_use() != 'clam':
        s.theme_use('clam')
    s.configure('.', background=c['bg'], foreground=c['text'], font=f['body'])
    for prefix, bg in (('', c['bg']), ('Card.', c['card']), ('Raised.', c['raised']), ('Selected.', c['selected'])):
        s.configure(prefix + 'TFrame', background=bg)
        s.configure(prefix + 'TLabel', background=bg, foreground=c['text'], font=f['body'])
        s.configure(prefix + 'Muted.TLabel', background=bg, foreground=c['muted'], font=f['small'])
        s.configure(prefix + 'Strong.TLabel', background=bg, foreground=c['text'], font=f['strong'])
    for label, fg, bg, face in (
        ('Title', c['text'], c['bg'], 'title'), ('Heading', c['text'], c['bg'], 'heading'),
        ('Muted', c['muted'], c['bg'], 'small'), ('CardMuted', c['muted'], c['card'], 'small'),
        ('CardHeading', c['text'], c['card'], 'heading'), ('Status', c['text'], c['card'], 'strong'),
        ('Timer', c['text'], c['card'], 'timer'), ('Chip', c['accent'], c['bg'], 'small')):
        s.configure(label + '.TLabel', foreground=fg, background=bg, font=f[face])
    _rounded_buttons(root, s, c, px)
    s.configure('Treeview', background=c['card'], fieldbackground=c['card'], foreground=c['text'], borderwidth=0,
                rowheight=px(44 if appearance.get('density') == 'Compact' else 58), font=f['body'], bordercolor=c['card'],
                lightcolor=c['card'], darkcolor=c['card'], relief='flat', indent=0)
    s.map('Treeview', background=[('selected', c['selected'])], foreground=[('selected', c['text'])])
    s.layout('Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
    s.layout('Treeview.Item', [('Treeitem.padding', {'sticky': 'nswe', 'children': [
        ('Treeitem.image', {'side': 'left', 'sticky': 'w'}), ('Treeitem.text', {'sticky': 'nswe'})]})])
    s.configure('Treeview.Heading', background=c['card'], foreground=c['muted'], font=f['small'], relief='flat', borderwidth=0, padding=(px(12), px(12)))
    s.map('Treeview.Heading', background=[('active', c['card'])])
    s.configure('TEntry', fieldbackground=c['raised'], foreground=c['text'], insertcolor=c['text'],
                bordercolor=c['border'], lightcolor=c['border'], darkcolor=c['border'], padding=px(10))
    s.map('TEntry', fieldbackground=[('readonly', c['card'])], foreground=[('readonly', c['muted'])], bordercolor=[('focus', c['accent'])])
    s.configure('TCombobox', fieldbackground=c['raised'], background=c['raised'], foreground=c['text'], arrowcolor=c['muted'],
                bordercolor=c['border'], lightcolor=c['border'], darkcolor=c['border'], padding=px(8))
    s.map('TCombobox', fieldbackground=[('readonly', c['raised']), ('disabled', c['card'])], foreground=[('readonly', c['text']), ('disabled', c['muted'])])
    s.configure('TCheckbutton', background=c['card'], foreground=c['text'], indicatorbackground=c['raised'], indicatorforeground=c['accent'])
    s.map('TCheckbutton', background=[('active', c['card'])], foreground=[('disabled', c['muted'])])
    for orientation in ('Vertical', 'Horizontal'):
        s.configure(orientation + '.TScrollbar', background=c['border'], troughcolor=c['card'], borderwidth=0,
                    arrowcolor=c['muted'], arrowsize=px(9), bordercolor=c['card'], lightcolor=c['card'], darkcolor=c['card'])
        s.map(orientation + '.TScrollbar', background=[('active', c['off'])])
    s.configure('TSeparator', background=c['border'])
    return s


def size_window(root, width, height, minimum=(940, 660)):
    scale = getattr(root, 'focuslock_scale', 1)
    max_width, max_height = root.winfo_screenwidth() - 40, root.winfo_screenheight() - 80
    root.minsize(min(round(minimum[0] * scale), max_width), min(round(minimum[1] * scale), max_height))
    root.geometry(f'{min(round(width * scale), max_width)}x{min(round(height * scale), max_height)}')
