import os
import sys
import tempfile
import time
import unittest
from unittest import mock

# Isolate app data (config, queue, history, log) in a temp home before import.
_TMP_HOME = tempfile.mkdtemp()
os.environ['HOME'] = _TMP_HOME
os.environ['APPDATA'] = _TMP_HOME
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core  # noqa: E402


class FakeYDL:
    """Stand-in for yt_dlp.YoutubeDL that simulates progress without network."""

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=False, process=True):
        return {'title': 'Title of ' + url}

    def download(self, urls):
        if 'fail' in urls[0]:
            raise Exception('boom')
        for i in range(1, 21):
            for hook in self.opts['progress_hooks']:
                hook({'status': 'downloading', 'downloaded_bytes': i, 'total_bytes': 20})
            time.sleep(0.02)


def make_item(url, **overrides):
    item = {
        'url': url,
        'media_type': 'Video',
        'quality': '720p',
        'audio_format': 'mp3',
        'path': _TMP_HOME,
        'ffmpeg_path': 'ffmpeg',
    }
    item.update(overrides)
    return item


class DownloadManagerTestBase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(core, 'YoutubeDL', FakeYDL)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dm = core.DownloadManager()
        self.dm.RETRY_DELAY = 0
        self.dm.clear_queue()
        self.statuses = []
        self.completed = []
        self.dm.on_item_status = lambda item_id, status: self.statuses.append(status)
        self.dm.on_complete = self.completed.append

    def run_queue(self, timeout=10):
        self.dm.start_download()
        end = time.time() + timeout
        while self.dm.state.downloading and time.time() < end:
            time.sleep(0.02)
        self.assertFalse(self.dm.state.downloading, "queue did not finish")


class UrlValidationTest(unittest.TestCase):
    def setUp(self):
        self.dm = core.DownloadManager()

    def test_valid_urls(self):
        for url in (
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'youtu.be/dQw4w9WgXcQ',
            'https://m.youtube.com/watch?v=abc',
            'https://music.youtube.com/watch?v=abc&list=RD',
            'https://www.youtube.com/shorts/abc123',
            'https://youtube.com/live/abc',
            'https://www.youtube.com/embed/abc',
            'https://www.youtube.com/playlist?list=PLx',
            'https://www.youtube.com/watch?feature=share&v=abc',
        ):
            self.assertTrue(self.dm.validate_url(url), url)

    def test_invalid_urls(self):
        for url in (
            'https://vimeo.com/1',
            'https://www.youtube.com/',
            'https://www.youtube.com/watch?v=',
            'hello',
            'https://evil.com/youtube.com/watch?v=a',
        ):
            self.assertFalse(self.dm.validate_url(url), url)


class BuildOptionsTest(unittest.TestCase):
    def setUp(self):
        self.dm = core.DownloadManager()

    def test_single_video(self):
        opts = self.dm.build_ydl_opts(make_item('https://youtu.be/x'))
        self.assertTrue(opts['noplaylist'])
        self.assertIn('[%(id)s]', opts['outtmpl'])
        self.assertEqual(opts['format'], 'bestvideo[height<=720]+bestaudio/best[height<=720]/best')
        self.assertEqual(opts['merge_output_format'], 'mp4')

    def test_playlist(self):
        opts = self.dm.build_ydl_opts(make_item('https://www.youtube.com/playlist?list=P'))
        self.assertFalse(opts['noplaylist'])
        self.assertIn('%(playlist_title)s', opts['outtmpl'])
        self.assertIn('%(playlist_index)03d', opts['outtmpl'])

    def test_best_video_not_restricted_to_mp4(self):
        opts = self.dm.build_ydl_opts(make_item('https://youtu.be/x', quality='Best'))
        self.assertEqual(opts['format'], 'bestvideo+bestaudio/best')

    def test_audio(self):
        opts = self.dm.build_ydl_opts(
            make_item('https://youtu.be/x', media_type='Audio', quality='192k', audio_format='m4a'))
        self.assertEqual(opts['postprocessors'][0]['preferredcodec'], 'm4a')
        self.assertEqual(opts['postprocessors'][0]['preferredquality'], '192')


class QueueTest(DownloadManagerTestBase):
    def test_add_assigns_id_and_remove_by_id(self):
        first, second = make_item('https://youtu.be/a'), make_item('https://youtu.be/b')
        self.dm.add_to_queue(first)
        self.dm.add_to_queue(second)
        self.assertTrue(first['id'])
        self.dm.remove_from_queue(first['id'])
        self.assertEqual([i['url'] for i in self.dm.get_queue()], ['https://youtu.be/b'])

    def test_remove_unknown_id_is_noop(self):
        self.dm.add_to_queue(make_item('https://youtu.be/a'))
        self.dm.remove_from_queue('missing')
        self.assertEqual(len(self.dm.get_queue()), 1)

    def test_queue_persists_across_instances(self):
        item = make_item('https://youtu.be/persist')
        self.dm.add_to_queue(item)
        restored = core.DownloadManager().get_queue()
        self.assertEqual([i['id'] for i in restored], [item['id']])


class DownloadFlowTest(DownloadManagerTestBase):
    def test_success_and_failure_statuses(self):
        for url in ('https://youtu.be/ok1', 'https://youtu.be/fail', 'https://youtu.be/ok2'):
            self.dm.add_to_queue(make_item(url))
        self.run_queue()
        self.assertEqual(self.statuses, ['Downloading', 'Complete', 'Downloading', 'Failed',
                                         'Downloading', 'Complete'])
        # One item failed, so the queue as a whole is not reported as successful.
        self.assertEqual(self.completed, [False])
        self.assertEqual(self.dm.history.history[0]['status'], 'Complete')
        self.assertEqual(self.dm.history.history[0]['title'], 'Title of https://youtu.be/ok2')

    def test_all_success(self):
        self.dm.add_to_queue(make_item('https://youtu.be/ok'))
        self.run_queue()
        self.assertEqual(self.completed, [True])

    def test_cancel_stops_current_and_keeps_rest(self):
        self.dm.add_to_queue(make_item('https://youtu.be/a'))
        self.dm.add_to_queue(make_item('https://youtu.be/b'))
        self.dm.start_download()
        time.sleep(0.1)
        self.dm.cancel_download()
        end = time.time() + 5
        while self.dm.state.downloading and time.time() < end:
            time.sleep(0.02)
        self.assertEqual(self.statuses, ['Downloading', 'Cancelled'])
        self.assertEqual(self.completed, [False])
        self.assertEqual(len(self.dm.get_queue()), 1)

    def test_progress_reported(self):
        progress = []
        self.dm.on_progress = lambda percent, *rest: progress.append(percent)
        self.dm.add_to_queue(make_item('https://youtu.be/ok'))
        self.run_queue()
        self.assertEqual(progress[-1], 100.0)


class FfmpegTest(unittest.TestCase):
    def test_invalid_paths(self):
        dm = core.DownloadManager()
        self.assertFalse(dm.validate_ffmpeg(''))
        self.assertFalse(dm.validate_ffmpeg('/nonexistent/ffmpeg'))


if __name__ == '__main__':
    unittest.main()
