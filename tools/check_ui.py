"""Real Tk layout/callback regression checks; uses fake OS/service/tray boundaries.
Run: python tools/check_ui.py [--screenshots DIRECTORY]
Never starts a real focus session or modifies the user's settings/registry.
"""
import argparse
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock, patch
import tkinter as tk
from tkinter import font

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from focuslock.ui import FocusLockWindow
from focuslock.storage import ConfigStore
from focuslock.native_host import send, receive, serve
from focuslock.extension_setup import build_wizard


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def check_layout(root):
    root.update()
    failures = []
    for widget in descendants(root):
        if not widget.winfo_viewable() or widget.winfo_class() not in ('TButton', 'TLabel', 'TCombobox', 'TCheckbutton'):
            continue
        name = str(widget.cget('text')) if 'text' in widget.keys() else widget.winfo_class()
        if widget.winfo_height() + 1 < widget.winfo_reqheight():
            failures.append(f'{name}: height {widget.winfo_height()} < {widget.winfo_reqheight()}')
        if widget.winfo_class() != 'TCombobox' and widget.winfo_width() + 1 < widget.winfo_reqwidth():
            failures.append(f'{name}: width {widget.winfo_width()} < {widget.winfo_reqwidth()}')
        parent = widget.master
        while parent:
            x, y = widget.winfo_rootx() - parent.winfo_rootx(), widget.winfo_rooty() - parent.winfo_rooty()
            # Row labels legitimately leave the vertical viewport when scrolling.
            # Still check their native row geometry and horizontal clipping.
            scrolling = parent.winfo_class() == 'Canvas' and bool(parent.cget('scrollregion'))
            if (x < -1 or x + widget.winfo_width() > parent.winfo_width() + 1 or
                    (not scrolling and (y < -1 or y + widget.winfo_height() > parent.winfo_height() + 1))):
                failures.append(f'{name}: clipped by {parent.winfo_class()}')
                break
            if scrolling:
                break
            if parent is root:
                break
            parent = parent.master
    assert not failures, '\n'.join(failures)


def capture(root, output, name):
    if not output:
        return
    from PIL import ImageGrab
    root.update()
    box = (root.winfo_rootx(), root.winfo_rooty(), root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height())
    ImageGrab.grab(bbox=box, xdisplay=os.environ.get('DISPLAY')).save(output / name)


def close_root(root, app=None):
    if app:
        app.shutting_down = True
    # All scheduled callbacks belong to this disposable test root.
    for callback in root.tk.splitlist(root.tk.call('after', 'info')):
        root.after_cancel(callback)
    root.destroy()


def check_desktop(output):
    apps = [r'C:\Apps\Steam\steam.exe', r'C:\Apps\Discord\Discord.exe']
    results = []
    for factor in (1.0, 1.25, 1.5):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as patches:
            store = ConfigStore(Path(directory) / 'config.json')
            store.save(apps)
            store.save_websites(['youtube.com', 'reddit.com'])
            store.save_selection([apps[1]], ['reddit.com'])
            state = {'state': 'IDLE'}
            tray = Mock()
            tray.drain.return_value = []
            tray.can_hide.return_value = True
            patches.enter_context(patch('focuslock.ui.TrayController', return_value=tray))
            patches.enter_context(patch('focuslock.ui.read_state', side_effect=lambda: dict(state)))
            patches.enter_context(patch('focuslock.extension_setup.recent_connection', return_value=True))
            patches.enter_context(patch('focuslock.network.require_admin'))
            patches.enter_context(patch('focuslock.ui.messagebox.askokcancel', return_value=True))
            errors = patches.enter_context(patch('focuslock.ui.messagebox.showerror'))
            launch = patches.enter_context(patch('focuslock.ui.launch_session', return_value='test-session'))
            root = tk.Tk()
            root.tk.call('tk', 'scaling', factor * 96 / 72)
            callbacks = []
            root.report_callback_exception = lambda t, v, tb: callbacks.append(str(v))
            app = FocusLockWindow(root, store, store.load())
            scale = root.focuslock_scale
            root.geometry(f'{round(980 * scale)}x{round(660 * scale)}')
            check_layout(root)
            assert app.timer.get() == '00:25:00'
            assert app.status_text.winfo_height() >= root.focuslock_fonts['small'].metrics('linespace') * 3
            # Independent metric checks catch the old *Font override / tiny timer.
            assert root.focuslock_fonts['title'].metrics('linespace') >= 24 * scale
            assert app.title_label.winfo_reqheight() >= 24 * scale
            assert app.timer_label.winfo_reqheight() >= 20 * scale
            app.tree.selection_set('0')
            root.update()
            app.space_apps()
            assert apps[0] in store.load_config()['disabled_applications']
            app.tree.selection_set('0')
            root.update()
            app.space_apps()
            assert apps[0] not in store.load_config()['disabled_applications']
            assert apps[1] in store.load_config()['disabled_applications']
            app.tree.selection_set('0')
            root.update()
            app.tree.canvas.event_generate('<Button-1>', x=30, y=app.tree.canvas.winfo_height()-1)
            root.update()
            assert not app.tree.selection()
            assert apps[0] in app.enabled_apps()
            assert not any(str(w.cget('text')) in {'Toggle','Remove','Hide to tray'}
                           for w in descendants(root) if w.winfo_class() == 'TButton')
            # Delete a row using its own cross, even when another row is highlighted.
            original_apps = list(app.applications)
            app.tree.selection_set('0')
            app.tree.see('1')
            root.update()
            x,y,w,h = app.tree.bbox('1', 'delete')
            app.tree.event_generate('<Button-1>', x=x+w//2, y=y+h//2)
            root.update()
            assert app.applications == [apps[0]]
            app.commit(original_apps)
            app.toggle_apps(['1'])
            app.sites_tab.invoke()
            check_layout(root)
            with patch('focuslock.ui.ask_website', return_value='https://example.com/path'):
                app.site_add.invoke()
            assert 'example.com' in store.load_websites()
            app.site_list.selection_set('0')
            root.update()
            app.site_list.canvas.event_generate('<Button-1>', x=30, y=app.site_list.canvas.winfo_height()-1)
            root.update()
            assert not app.site_list.selection()
            app.site_list.see('2')
            root.update()
            x,y,w,h = app.site_list.bbox('2', 'delete')
            app.site_list.event_generate('<Button-1>', x=x+w//2, y=y+h//2)
            root.update()
            assert 'example.com' not in app.websites
            app.save_websites([*app.websites,'example.com'])
            app.site_list.selection_set(2)
            app.site_list.event_generate('<<TreeviewSelect>>')
            root.update()
            app.space_sites()
            assert 'example.com' in store.load_config()['disabled_websites']
            app.duration.set('1')
            assert app.timer.get() == '00:01:00'
            app.start_button.invoke()
            launch.assert_called_once_with([apps[0]], force_running=True, websites=['youtube.com'], minutes=1)
            assert app.busy
            state.update(state='ACTIVE', session_id='test-session', applications=[apps[0]],
                         websites=['youtube.com'], elapsed_seconds=29, remaining_seconds=31,
                         mode='timed', started_ms=1000, deadline_ms=61000)
            app.poll()
            app.apps_tab.invoke()
            check_layout(root)
            assert app.timer.get() == '00:00:31'
            assert app.duration_box.instate(['disabled'])
            assert app.clock_caption.get() == 'TIME REMAINING'
            assert app.start_button.cget('text') == 'Session active'
            frozen_config = store.path.read_bytes()
            app.theme_name.set('Light')
            app.change_theme()
            assert app.busy and app.display_session == 'test-session'
            assert app.timer.get() == '00:00:31'
            check_layout(root)
            app.theme_name.set('Midnight')
            app.change_theme()
            app.toggle_apps(['0'])
            app.toggle_sites()
            app.site_add.invoke()
            assert store.path.read_bytes() == frozen_config
            # Exercise actual frame codec + bridge serialization for this state.
            source, destination = io.BytesIO(), io.BytesIO()
            send(source, {'type': 'get_state'})
            source.seek(0)
            serve(source, destination, lambda: dict(state))
            destination.seek(0)
            assert receive(destination)['domains'] == ['youtube.com']
            app.hide_to_tray()
            root.update()
            assert root.state() == 'withdrawn' and state['state'] == 'ACTIVE'
            app.show_window()
            root.update()
            if factor == 1:
                capture(root, output, 'active.png')
            # Website-only sessions should open the relevant page automatically.
            state.update(session_id='website-only', applications=[])
            app.poll()
            assert app.current_tab == 'sites'
            app.apps_tab.invoke()
            root.update()
            assert app.apps_empty.winfo_ismapped()
            assert 'No apps in this session' in app.apps_empty.cget('text')
            check_layout(root)
            state.clear()
            state.update(state='ENDED')
            app.poll()
            assert not app.busy and app.timer.get() == '00:00:00'
            assert not app.duration_box.instate(['disabled'])
            app.duration.set('50')
            app.poll()
            assert app.timer.get() == '00:50:00'
            assert len(app.tree.get_children()) == 2
            assert len(app.site_list.get_children()) == 3
            assert apps[1] in store.load_config()['disabled_applications']
            check_layout(root)
            errors.assert_not_called()
            assert not callbacks, callbacks
            state.clear()
            state.update(state='IDLE')
            app.poll()
            app.duration.set('Until restart')
            assert app.timer.get() == '00:00:00'
            assert app.clock_caption.get() == 'TIME IN FOCUS'
            app.start_button.invoke()
            assert launch.call_args.kwargs['minutes'] is None
            state.update(state='ACTIVE', session_id='test-session', mode='until_reboot',
                         applications=[apps[0]], websites=[], started_ms=1000, elapsed_seconds=90)
            app.poll()
            assert app.timer.get() == '00:01:30'
            assert app.clock_caption.get() == 'TIME IN FOCUS'
            check_layout(root)
            state.clear()
            state.update(state='IDLE')
            app.poll()
            app.duration.set('25')
            if factor == 1:
                state.update(state='IDLE')
                app.poll()
                from focuslock.preferences import THEME_NAMES, load_theme
                before = store.path.read_bytes()
                for theme in THEME_NAMES:
                    app.theme_name.set(theme)
                    app.change_theme()
                    check_layout(root)
                    assert load_theme(store.path) == theme
                    assert store.path.read_bytes() == before
                    capture(root,output,'ready-'+theme.lower()+'.png')
            results.append({'scale': factor, 'size': root.geometry(), 'checks': 'layout, fonts, tabs, selections, start, active, bridge, tray, idle restoration'})
            close_root(root, app)
    return results


def check_wizard(output):
    for factor in (1.0, 1.5):
        with patch('focuslock.extension_setup.register') as register, \
             patch('focuslock.extension_setup.recent_connection', return_value=True):
            root = tk.Tk()
            root.tk.call('tk', 'scaling', factor * 96 / 72)
            refs = build_wizard(root)
            check_layout(root)
            register.assert_called_once()
            refs['copy_address'].invoke()
            assert root.clipboard_get() == 'opera://extensions'
            refs['browser'].set('Edge')
            refs['selector'].event_generate('<<ComboboxSelected>>')
            root.update()
            refs['copy_address'].invoke()
            assert root.clipboard_get() == 'edge://extensions'
            refs['copy_path'].invoke()
            assert root.clipboard_get().endswith('extension')
            assert refs['path_entry'].get() == root.clipboard_get()
            for browser, address, suffix in (
                ('Yandex','browser://extensions','extension'),
                ('Firefox','about:debugging#/runtime/this-firefox','manifest.json')):
                refs['browser'].set(browser)
                refs['selector'].event_generate('<<ComboboxSelected>>')
                root.update()
                refs['copy_address'].invoke()
                assert root.clipboard_get() == address
                refs['copy_path'].invoke()
                assert root.clipboard_get().endswith(suffix)
                assert refs['path_entry'].get() == root.clipboard_get()
                check_layout(root)
            assert refs['connection'].get() == 'Connected to browser'
            check_layout(root)
            if factor == 1:
                capture(root, output, 'browser-setup.png')
            close_root(root)


def check_picker(output):
    from focuslock.app_picker import AppPicker
    from focuslock.discovery import Candidate
    from focuslock.theme import apply_theme
    from focuslock.storage import path_key
    import time
    candidates = [Candidate('Discord',r'C:\Apps\Discord.exe','Running',True),
                  Candidate('Steam',r'C:\Steam\steam.exe','Start menu'),
                  Candidate('Spotify',r'C:\Apps\Spotify.exe','Start menu')]
    for factor in (1.0,1.5):
        root = tk.Tk()
        root.tk.call('tk','scaling',factor*96/72)
        apply_theme(root,'Violet')
        root.geometry('1x1+0+0')
        callbacks = []
        root.report_callback_exception = lambda t,v,tb:callbacks.append(str(v))
        added = Mock(return_value=True)
        def scan(cancel,publish):
            publish(candidates[:1],'Running applications',[])
            return candidates,[]
        dialog = AppPicker(root,[candidates[0].path],added,scanner=scan)
        until=time.monotonic()+3
        while dialog.scanning and time.monotonic()<until:
            root.update()
            time.sleep(.01)
        assert not dialog.scanning
        check_layout(dialog)
        dialog.toggle(['0'])
        assert not dialog.chosen  # Already-added rows cannot be duplicated.
        dialog.toggle(['1'])
        dialog.query.set('Spotify')
        assert len(dialog.visible)==1
        assert path_key(candidates[1].path) in dialog.chosen
        dialog.toggle(['2'])
        dialog.query.set('')
        assert len(dialog.chosen)==2
        dialog.tree.selection_set('2')
        root.update()
        assert dialog.path.get()==candidates[2].path
        check_layout(dialog)
        if factor==1:
            capture(dialog,output,'find-apps.png')
        with patch('focuslock.app_picker.validate_targets',side_effect=lambda items:items) as validate:
            dialog.add_button.invoke()
            validate.assert_called_once_with([a.path for a in candidates[1:]])
        added.assert_called_once_with([a.path for a in candidates[1:]])
        assert dialog.closed and dialog.cancelled.is_set()
        assert not callbacks,callbacks
        close_root(root)


def check_customization(output):
    from focuslock.preferences import load_appearance, preference_path
    from focuslock.theme import ACCENTS
    apps = [r'C:\Apps\Telegram\Telegram.exe', r'C:\Apps\Discord\Discord.exe', r'C:\Apps\Steam\Steam.exe']
    for factor in (1.0, 1.5):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as patches:
            store = ConfigStore(Path(directory) / 'config.json')
            store.save(apps)
            store.save_websites(['youtube.com', 'reddit.com', 'twitch.tv'])
            store.save_selection([apps[1]], ['reddit.com'])
            state = {'state': 'IDLE'}
            tray = Mock()
            tray.drain.return_value = []
            patches.enter_context(patch('focuslock.ui.TrayController', return_value=tray))
            patches.enter_context(patch('focuslock.ui.read_state', side_effect=lambda: dict(state)))
            patches.enter_context(patch('focuslock.extension_setup.recent_connection', return_value=True))
            # Simulate installed Windows applications; never touch real executables.
            original_is_file = Path.is_file
            patches.enter_context(patch.object(Path, 'is_file', autospec=True,
                side_effect=lambda p: str(p).lower().endswith('.exe') or original_is_file(p)))
            root = tk.Tk()
            root.tk.call('tk', 'scaling', factor * 96 / 72)
            callbacks = []
            root.report_callback_exception = lambda t, v, tb: callbacks.append(str(v))
            app = FocusLockWindow(root, store, store.load())
            check_layout(root)
            if factor == 1:
                capture(root, output, 'desktop-midnight.png')
                app.sites_tab.invoke()
                check_layout(root)
                capture(root, output, 'websites.png')
                app.apps_tab.invoke()
            # Filtering must keep original IDs, not renumber the visible rows.
            app.apps_query.set('sTeAm')
            root.update()
            assert app.tree.get_children() == ('2',)
            app.tree.rows['2']['switch'].invoke()
            assert apps[2] in store.load_config()['disabled_applications']
            assert apps[1] in store.load_config()['disabled_applications']
            app.tree.rows['2']['switch'].invoke()
            assert apps[2] not in store.load_config()['disabled_applications']
            app.apps_query.set('no such application')
            root.update()
            assert app.apps_empty.winfo_viewable() and not app.tree.get_children()
            app.apps_query.set('')
            extra = [fr'C:\Apps\Example{i}.exe' for i in range(15)]
            app.commit([*apps, *extra])
            app.apps_query.set('Example12')
            root.update()
            assert app.tree.get_children() == ('15',)
            app.tree.rows['15']['delete'].invoke()
            assert extra[12] not in store.load() and len(app.applications) == 17
            app.apps_query.set('')
            root.update()
            assert app.tree.scrollbar.winfo_viewable()
            # Deleting an earlier row must not silently highlight another app.
            app.tree.selection_set('4')
            selected = app.tree.item('4', 'values')[2]
            app.remove(['0'])
            root.update()
            assert app.tree.item(app.tree.selection()[0], 'values')[2] == selected
            app.tree.see(app.tree.get_children()[-1])
            root.update()
            assert app.tree.canvas.yview()[0] > 0
            app.sites_query.set('TWITCH')
            app.site_list.rows['2']['switch'].invoke()
            assert 'twitch.tv' in store.load_config()['disabled_websites']
            app.sites_query.set('')
            app.preset_buttons[45].invoke()
            assert app.timer.get() == '00:45:00'
            app.duration.set('0')
            assert app.start_button.instate(['disabled'])
            app.duration.set('25')
            assert not app.start_button.instate(['disabled'])
            # A live appearance preview cannot change an active session or lists.
            state.update(state='ACTIVE', session_id='appearance-test', mode='timed',
                         applications=[apps[0]], websites=['youtube.com'], elapsed_seconds=60,
                         remaining_seconds=1440, started_ms=1000, deadline_ms=1501000)
            app.poll()
            frozen = store.path.read_bytes()
            timer = app.timer.get()
            app.open_appearance()
            dialog = app.appearance_dialog
            root.update()
            check_layout(dialog)
            for key, value in dict(theme='Light', accent='Rose', density='Compact', timer_style='Minimal').items():
                dialog.variables[key].set(value)
            dialog.changed()
            root.update()
            assert root.staylocked_palette['accent'] == ACCENTS['Rose']
            assert root.staylocked_appearance['timer_style'] == 'Minimal'
            assert not preference_path(store.path).exists()
            assert app.busy and app.timer.get() == timer
            assert store.path.read_bytes() == frozen
            check_layout(dialog)
            if factor == 1:
                capture(dialog, output, 'appearance-settings.png')
            dialog.apply()
            saved = load_appearance(store.path)
            assert saved == dict(theme='Light', accent='Rose', density='Compact', timer_style='Minimal')
            assert app.tree.locked and all(b.instate(['disabled']) for b in app.preset_buttons.values())
            check_layout(root)
            app.open_appearance()
            dialog = app.appearance_dialog
            dialog.variables['theme'].set('Ocean')
            dialog.changed()
            dialog.cancel()
            assert root.staylocked_theme == saved['theme']
            assert load_appearance(store.path) == saved
            assert app.busy and app.timer.get() == timer
            assert store.path.read_bytes() == frozen
            app.open_appearance()
            dialog = app.appearance_dialog
            dialog.reset()
            assert root.staylocked_theme == 'Midnight'
            dialog.cancel()
            assert root.staylocked_theme == 'Light'
            state.clear()
            state.update(state='IDLE')
            app.poll()
            check_layout(root)
            assert not callbacks, callbacks
            close_root(root, app)
            root = tk.Tk()
            restored = FocusLockWindow(root, store, store.load())
            assert restored.appearance == saved
            assert root.staylocked_appearance['density'] == 'Compact'
            check_layout(root)
            close_root(root, restored)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshots', type=Path)
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    results = check_desktop(args.screenshots)
    check_wizard(args.screenshots)
    check_picker(args.screenshots)
    check_customization(args.screenshots)
    print(json.dumps({'result': 'PASS', 'customization': 'search IDs, scrolling, presets, live preview, cancel, reset, persistence and active-session isolation at 100% and 150%', 'desktop': results, 'wizard': 'layout + clipboard at 100% and 150%', 'picker': 'scan queue, search, multi-select, path, add and close at 100% and 150%'}, indent=2))


if __name__ == '__main__':
    main()
