"""Discovery regressions: path safety, stale updaters, duplicates and partial failure."""
import os
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import Mock, patch
from focuslock import discovery as d
from focuslock.preferences import load_theme, save_theme, THEME_NAMES
from focuslock.storage import ConfigStore


class DiscoveryTests(unittest.TestCase):
    def test_only_absolute_local_executable_paths(self):
        for bad in (None, 'Discord.exe', r'\\server\share\Discord.exe', r'C:\app.exe:evil.exe',
                    r'C:\app.cmd', r'"C:\app.exe" --uninstall', r'C:app.exe', 'https://example.com/app.exe'):
            self.assertIsNone(d.clean_exe(bad),bad)
        self.assertEqual(d.clean_exe(r'"C:\Program Files\App\app.exe"'), r'C:\Program Files\App\app.exe')

    def test_system_helpers_and_own_exes_are_not_candidates(self):
        for name in ('Taskmgr.exe','StayLocked.exe','StayLockedBridge.exe','FocusLock.exe',
                     'ExtensionSetup.exe','update.exe','unins000.exe','setup.exe'):
            self.assertFalse(d.is_candidate('C:\\Apps\\'+name,exists=lambda _:True),name)
        self.assertFalse(d.is_candidate(r'C:\Windows\System32\other.exe',[r'C:\Windows'],lambda _:True))
        self.assertTrue(d.is_candidate(r'C:\WindowsGames\Game.exe',[r'C:\Windows'],lambda _:True))
        self.assertFalse(d.is_candidate(r'C:\Missing.exe',exists=lambda _:False))

    def test_duplicates_preserve_running_and_friendly_name(self):
        apps = d.merge_candidates([
            d.Candidate('discord.exe',r'C:\Apps\Discord.exe','Running',True),
            d.Candidate('Discord',r'c:\apps\DISCORD.exe','Start menu'),
            d.Candidate('Steam',r'C:\Steam\steam.exe','Windows registry')],exists=lambda _:True)
        self.assertEqual(len(apps),2)
        self.assertEqual(apps[0].name,'Discord')
        self.assertTrue(apps[0].running)
        self.assertIn('Running',apps[0].source)
        self.assertIn('Start menu',apps[0].source)

    def test_discord_update_shortcut_resolves_latest_existing_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ('app-1.0.9','app-1.0.10','app-2.0.0'):
                (root/folder).mkdir()
            for folder in ('app-1.0.9','app-1.0.10'):
                (root/folder/'Discord.exe').touch()
            self.assertEqual(d.resolve_squirrel(root/'Update.exe','--processStart Discord.exe'),str(root/'app-1.0.10'/'Discord.exe'))
            self.assertEqual(d.resolve_squirrel(root/'Update.exe','--processStart "Discord.exe" --a'),str(root/'app-1.0.10'/'Discord.exe'))
            for bad in ('--processStart ../Discord.exe','--processStart "C:\\Discord.exe"','--uninstall'):
                self.assertIsNone(d.resolve_squirrel(root/'Update.exe',bad))

    def test_one_source_failure_keeps_other_results(self):
        app=d.Candidate('Telegram',r'C:\Apps\Telegram.exe','Running',True)
        published=Mock()
        with patch.object(d.sys,'platform','win32'), patch.object(d,'running_apps',return_value=[app]), \
             patch.object(d,'common_apps',return_value=[]), patch.object(d,'registry_apps',side_effect=OSError('unavailable')), \
             patch.object(d,'shortcut_apps',return_value=[]),patch.object(d.os.path,'isfile',return_value=True):
            results,warnings=d.discover(publish=published)
        self.assertEqual([a.name for a in results],['Telegram'])
        self.assertEqual(len(warnings),1)
        self.assertEqual(published.call_count,4)

    def test_cancelled_scan_does_not_open_any_source(self):
        event=Event();event.set()
        with patch.object(d.sys,'platform','win32'),patch.object(d,'running_apps') as run:
            results,_=d.discover(event)
        run.assert_not_called()
        self.assertEqual(results,[])

    def test_metadata_reader_failure_and_cancel_close_only_its_own_process(self):
        with patch.dict(os.environ,{'SystemRoot':r'C:\Windows'}):
            child=Mock()
            child.poll.return_value=None
            child.communicate.return_value=(b'[]',b'')
            event=Event();event.set()
            with patch.object(d.subprocess,'Popen',return_value=child) as spawn:
                self.assertEqual(list(d.shortcut_apps(event)),[])
            child.kill.assert_called_once()
            args,kwargs=spawn.call_args
            self.assertNotIn('shell',kwargs)
            self.assertIn('-NoProfile',args[0])
            self.assertNotIn('-ExecutionPolicy',args[0])


class AppearanceTests(unittest.TestCase):
    def test_theme_save_keeps_blocklist_bytes_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=Path(tmp)/'config.json';store=ConfigStore(config)
            store.save([r'C:\Discord.exe']);store.save_websites(['youtube.com'])
            store.save_selection([r'C:\Discord.exe'],['youtube.com'])
            original=config.read_bytes()
            self.assertEqual(load_theme(config),'Midnight')
            for theme in THEME_NAMES:
                save_theme(theme,config)
                self.assertEqual(load_theme(config),theme)
                self.assertEqual(config.read_bytes(),original)
            with self.assertRaises(ValueError):save_theme('unknown',config)
            (Path(tmp)/'appearance.json').write_text('broken')
            self.assertEqual(load_theme(config),'Midnight')


if __name__=='__main__':
    unittest.main()
