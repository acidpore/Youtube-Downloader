import os
import sys
import tempfile
import unittest

_TMP_HOME = tempfile.mkdtemp()
os.environ['HOME'] = _TMP_HOME
os.environ['APPDATA'] = _TMP_HOME
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    HAS_DISPLAY = True
except Exception:  # no tkinter or no display
    HAS_DISPLAY = False


@unittest.skipUnless(HAS_DISPLAY, "needs tkinter and a display")
class GuiTest(unittest.TestCase):
    def setUp(self):
        import core
        import gui
        self.gui = gui
        self.dm = core.DownloadManager()
        self.dm.clear_queue()
        self.config = {}
        self.root = tk.Tk()
        self.root.withdraw()

        def config_handler(action, key=None, value=None):
            if action == 'get':
                return self.config.get(key, self.dm.config.get(key, ''))
            if action == 'update':
                self.config[key] = value

        dm = self.dm

        def queue_handler(action, data=None):
            return {
                'add': lambda: dm.add_to_queue(data),
                'remove': lambda: dm.remove_from_queue(data),
                'clear': lambda: dm.clear_queue(),
                'list': lambda: dm.get_queue(),
                'items': lambda: dm.get_items(),
                'history': lambda: [],
                'validate_url': lambda: dm.validate_url(data),
                'pause': lambda: dm.pause_item(data),
                'resume': lambda: dm.resume_item(data),
                'retry': lambda: dm.retry_item(data),
                'update_item': lambda: dm.update_item(data[0], **data[1]),
                'yt_dlp_version': lambda: '2099.1.1',
            }[action]()

        self.app = gui.YouTubeDownloaderUI(self.root, config_handler, queue_handler,
                                           lambda action: None, lambda a, b: True)
        # Keep downloads from actually starting when an item is resumed.
        self.dm.start_download = lambda: None
        self.dm.on_item_status = self.app.update_queue_item_status

    def tearDown(self):
        self.root.destroy()

    def set_text(self, text):
        self.app._hide_placeholder()
        self.app.url_text.delete('1.0', tk.END)
        self.app.url_text.insert('1.0', text)

    def test_add_valid_keeps_invalid(self):
        self.set_text("https://youtu.be/abc\nnot a link\nhttps://www.youtube.com/shorts/xyz")
        self.app.process_url_input()
        self.assertEqual(len(self.app.queue_tree.get_children()), 2)
        self.assertEqual(self.app._get_url_lines(), ['not a link'])

    def test_remove_and_clear(self):
        self.set_text("https://youtu.be/a\nhttps://youtu.be/b")
        self.app.process_url_input()
        first = self.app.queue_tree.get_children()[0]
        self.app.queue_tree.selection_set(first)
        self.app.remove_selected()
        self.assertEqual(len(self.dm.get_queue()), 1)
        self.app.clear_queue()
        self.assertEqual(self.app.queue_tree.get_children(), ())
        self.assertEqual(self.dm.get_queue(), [])

    def test_progress_and_status(self):
        self.set_text("https://youtu.be/a")
        self.app.process_url_input()
        iid = self.app.queue_tree.get_children()[0]
        self.app.update_queue_item_title(iid, 'My video')
        self.app.update_queue_item_status(iid, 'Downloading')
        self.app.update_progress(iid, 42.0, '1.0MiB/s', '00:10', '1.0MB / 2.0MB', 1048576.0)
        self.assertEqual(self.app.queue_tree.set(iid, 'title'), 'My video')
        self.assertEqual(self.app.queue_tree.set(iid, 'status'), 'Downloading 42%')
        self.app.update_queue_item_status(iid, 'Complete')
        self.app.clear_completed()
        self.assertEqual(self.app.queue_tree.get_children(), ())

    def test_audio_options_and_theme(self):
        self.app.media_type.set('Audio')
        self.app.update_format_options()
        self.assertIn('320k', self.app.quality_combobox['values'])
        self.app.toggle_theme()
        self.assertEqual(self.config['theme'], 'dark')

    def test_download_state_button(self):
        self.app.update_download_state(True, False)
        self.assertEqual(self.app.download_btn['text'], 'Cancel')
        self.app.download_complete(False)
        self.assertEqual(self.app.download_btn['text'], 'Start downloads')

    def test_pause_and_resume_waiting_item(self):
        self.set_text("https://youtu.be/a")
        self.app.process_url_input()
        iid = self.app.queue_tree.get_children()[0]
        self.app.queue_tree.selection_set(iid)
        self.app.pause_selected()
        self.assertEqual(self.app.queue_tree.set(iid, 'status'), 'Paused')
        self.assertIn(iid, self.dm.paused)
        self.app.resume_selected()
        self.assertEqual(self.app.queue_tree.set(iid, 'status'), 'Queued')
        self.assertEqual([i['id'] for i in self.dm.get_queue()], [iid])

    def test_parallel_progress_summary(self):
        self.set_text("https://youtu.be/a\nhttps://youtu.be/b")
        self.app.process_url_input()
        first, second = self.app.queue_tree.get_children()
        for iid in (first, second):
            self.app.update_queue_item_status(iid, 'Downloading')
        self.app.update_progress(first, 20.0, '1MiB/s', '00:10', '1/5MB', 1048576.0)
        self.app.update_progress(second, 60.0, '1MiB/s', '00:05', '3/5MB', 1048576.0)
        self.assertEqual(self.app.progress_bar['value'], 40.0)
        self.assertIn('2 downloads', self.app.stats_label['text'])

    def test_clipboard_links(self):
        self.app._take_clipboard_links("https://youtu.be/clip1\nhttps://youtu.be/clip2")
        self.assertEqual(self.app._get_url_lines(), ['https://youtu.be/clip1', 'https://youtu.be/clip2'])
        # Non-YouTube text and duplicates are ignored.
        self.app._take_clipboard_links("some random text")
        self.app._take_clipboard_links("https://youtu.be/clip1")
        self.assertEqual(len(self.app._get_url_lines()), 2)

    def test_playlist_item_spec(self):
        fmt = self.gui.YouTubeDownloaderUI._format_playlist_items
        parse = self.gui.YouTubeDownloaderUI._parse_playlist_items
        self.assertEqual(fmt([1, 2, 3, 5, 7, 8]), '1-3,5,7-8')
        self.assertEqual(parse('Best · #1-3,5,7-8'), [1, 2, 3, 5, 7, 8])
        self.assertEqual(parse('Best'), [])

    def test_settings_dialog_opens(self):
        self.app.show_settings()
        self.root.update_idletasks()
        dialogs = [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]
        self.assertEqual(len(dialogs), 1)
        dialogs[0].destroy()


if __name__ == '__main__':
    unittest.main()
