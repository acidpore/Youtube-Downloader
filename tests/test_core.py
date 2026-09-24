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

    # Seconds per simulated download step; tests can slow it down.
    step = 0.02
    running = 0
    max_running = 0
    lock = __import__('threading').Lock()

    def download(self, urls):
        if 'fail' in urls[0]:
            raise Exception('boom')
        with FakeYDL.lock:
            FakeYDL.running += 1
            FakeYDL.max_running = max(FakeYDL.max_running, FakeYDL.running)
        tmp = os.path.join(self.opts['outtmpl'].split('%')[0], urls[0].rsplit('/', 1)[-1] + '.mp4')
        try:
            for i in range(1, 21):
                if i == 1:
                    open(tmp + '.part', 'w').close()
                for hook in self.opts['progress_hooks']:
                    hook({'status': 'downloading', 'downloaded_bytes': i, 'total_bytes': 20,
                          'tmpfilename': tmp + '.part', 'filename': tmp, 'speed': 1000.0})
                time.sleep(FakeYDL.step)
        finally:
            with FakeYDL.lock:
                FakeYDL.running -= 1


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
        self.dm.config['max_concurrent'] = 1
        self.dm.clear_queue()
        FakeYDL.step = 0.02
        FakeYDL.max_running = 0
        self.statuses = []
        self.completed = []
        self.dm.on_item_status = lambda item_id, status: self.statuses.append(status)
        self.dm.on_complete = self.completed.append

    def wait_idle(self, timeout=10):
        end = time.time() + timeout
        while self.dm.state.downloading and time.time() < end:
            time.sleep(0.02)
        self.assertFalse(self.dm.state.downloading, "queue did not finish")

    def wait_for(self, condition, timeout=5):
        end = time.time() + timeout
        while not condition() and time.time() < end:
            time.sleep(0.01)
        self.assertTrue(condition(), "condition not reached")

    def run_queue(self, timeout=10):
        self.dm.start_download()
        self.wait_idle(timeout)


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
        self.wait_idle(5)
        self.assertEqual(self.statuses, ['Downloading', 'Cancelled'])
        self.assertEqual(self.completed, [False])
        self.assertEqual(len(self.dm.get_queue()), 1)
        # Only the cancelled item's partial file is removed.
        self.assertFalse(os.path.exists(os.path.join(_TMP_HOME, 'a.mp4.part')))

    def test_progress_reported(self):
        progress = []
        self.dm.on_progress = lambda item_id, percent, *rest: progress.append(percent)
        self.dm.add_to_queue(make_item('https://youtu.be/ok'))
        self.run_queue()
        self.assertEqual(progress[-1], 100.0)


class ParallelAndControlTest(DownloadManagerTestBase):
    def test_parallel_downloads(self):
        self.dm.config['max_concurrent'] = 3
        for name in 'abcd':
            self.dm.add_to_queue(make_item('https://youtu.be/p' + name))
        self.run_queue()
        self.assertEqual(FakeYDL.max_running, 3)
        self.assertEqual(self.statuses.count('Complete'), 4)
        self.assertEqual(self.completed, [True])

    def test_pause_and_resume_keeps_partial_file(self):
        FakeYDL.step = 0.05
        item = make_item('https://youtu.be/pause1')
        self.dm.add_to_queue(item)
        self.dm.start_download()
        self.wait_for(lambda: item['id'] in self.dm.active)
        time.sleep(0.1)
        self.assertTrue(self.dm.pause_item(item['id']))
        self.wait_idle()
        self.assertEqual(self.statuses[-1], 'Paused')
        self.assertIn(item['id'], self.dm.paused)
        self.assertTrue(os.path.exists(os.path.join(_TMP_HOME, 'pause1.mp4.part')))
        # Paused items survive a restart.
        self.assertIn(item['id'], core.DownloadManager().paused)

        FakeYDL.step = 0.01
        self.assertTrue(self.dm.resume_item(item['id']))
        self.wait_idle()
        self.assertEqual(self.statuses[-1], 'Complete')
        self.assertNotIn(item['id'], self.dm.paused)

    def test_pause_waiting_item(self):
        item = make_item('https://youtu.be/wait')
        self.dm.add_to_queue(item)
        self.assertTrue(self.dm.pause_item(item['id']))
        self.assertEqual(self.dm.get_queue(), [])
        self.assertEqual([i['id'] for i in self.dm.get_items()], [item['id']])

    def test_retry_failed_item(self):
        item = make_item('https://youtu.be/fail-then-ok')
        self.dm.add_to_queue(item)
        self.run_queue()
        self.assertEqual(self.statuses[-1], 'Failed')
        self.assertIn(item['id'], self.dm.finished)
        item['url'] = 'https://youtu.be/now-ok'
        self.assertTrue(self.dm.retry_item(item['id']))
        self.wait_idle()
        self.assertEqual(self.statuses[-1], 'Complete')

    def test_cancel_single_item(self):
        FakeYDL.step = 0.05
        self.dm.config['max_concurrent'] = 2
        first, second = make_item('https://youtu.be/c1'), make_item('https://youtu.be/c2')
        self.dm.add_to_queue(first)
        self.dm.add_to_queue(second)
        self.dm.start_download()
        self.wait_for(lambda: len(self.dm.active) == 2)
        self.dm.cancel_item(first['id'])
        self.wait_idle()
        self.assertIn(first['id'], self.dm.finished)
        self.assertEqual(self.dm.history.history[0]['status'], 'Complete')


class OptionsFromConfigTest(unittest.TestCase):
    def setUp(self):
        self.dm = core.DownloadManager()

    def test_extras(self):
        self.dm.config.update(embed_subtitles=True, subtitle_langs='en, id', embed_thumbnail=True,
                              add_metadata=True, cookies_browser='firefox', rate_limit_kb=1000,
                              max_concurrent=2)
        opts = self.dm.build_ydl_opts(make_item('https://youtu.be/x', playlist_items='1,3'))
        keys = [p['key'] for p in opts['postprocessors']]
        self.assertEqual(opts['subtitleslangs'], ['en', 'id'])
        self.assertIn('FFmpegEmbedSubtitle', keys)
        self.assertIn('FFmpegMetadata', keys)
        self.assertEqual(keys[-1], 'EmbedThumbnail')
        self.assertEqual(opts['cookiesfrombrowser'], ('firefox',))
        self.assertEqual(opts['ratelimit'], 512000)
        self.assertEqual(opts['playlist_items'], '1,3')

    def test_no_thumbnail_for_wav(self):
        self.dm.config.update(embed_thumbnail=True)
        opts = self.dm.build_ydl_opts(make_item('https://youtu.be/x', media_type='Audio',
                                                quality='192k', audio_format='wav'))
        self.assertNotIn('writethumbnail', opts)

    def test_defaults_off(self):
        self.dm.config.update(embed_subtitles=False, embed_thumbnail=False, add_metadata=False,
                              cookies_browser='', rate_limit_kb=0)
        opts = self.dm.build_ydl_opts(make_item('https://youtu.be/x'))
        for key in ('writesubtitles', 'writethumbnail', 'cookiesfrombrowser', 'ratelimit', 'postprocessors'):
            self.assertNotIn(key, opts)

    def test_config_validation(self):
        cfg = self.dm.validate_config({'max_concurrent': 9, 'rate_limit_kb': 'x', 'cookies_browser': 'ie',
                                       'embed_subtitles': 'yes', 'watch_clipboard': False})
        self.assertEqual(cfg['max_concurrent'], 2)
        self.assertEqual(cfg['rate_limit_kb'], 0)
        self.assertEqual(cfg['cookies_browser'], '')
        self.assertFalse(cfg['embed_subtitles'])
        self.assertFalse(cfg['watch_clipboard'])

    def test_update_config_validates(self):
        self.dm.update_config('max_concurrent', '3')
        self.assertEqual(self.dm.config['max_concurrent'], 3)

    def test_yt_dlp_version(self):
        self.assertNotEqual(self.dm.get_yt_dlp_version(), '')


class FfmpegTest(unittest.TestCase):
    def test_invalid_paths(self):
        dm = core.DownloadManager()
        self.assertFalse(dm.validate_ffmpeg(''))
        self.assertFalse(dm.validate_ffmpeg('/nonexistent/ffmpeg'))



class FirstRunConfigTest(unittest.TestCase):
    def test_defaults_without_config_file(self):
        with mock.patch.object(core.DownloadManager, 'CONFIG_FILE',
                               os.path.join(_TMP_HOME, 'does-not-exist.json')):
            dm = core.DownloadManager()
        self.assertEqual(dm.config['download_path'], core.Config.DEFAULT_DOWNLOAD_PATH)
        self.assertEqual(dm.config['media_type'], 'Video')
        self.assertEqual(dm.config['theme'], 'light')


if __name__ == '__main__':
    unittest.main()
