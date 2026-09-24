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

        def queue_handler(action, data=None):
            return {
                'add': lambda: self.dm.add_to_queue(data),
                'remove': lambda: self.dm.remove_from_queue(data),
                'clear': lambda: self.dm.clear_queue(),
                'list': lambda: self.dm.get_queue(),
                'history': lambda: [],
                'validate_url': lambda: self.dm.validate_url(data),
            }[action]()

        self.app = gui.YouTubeDownloaderUI(self.root, config_handler, queue_handler,
                                           lambda action: None, lambda a, b: True)

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
        self.app.update_progress(42.0, '1.0MiB/s', '00:10', '1.0MB / 2.0MB')
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


if __name__ == '__main__':
    unittest.main()
