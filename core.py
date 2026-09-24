import glob
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import OrderedDict, deque
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

# Regular expression to strip ANSI escape codes from progress strings.
ANSI_REGEX = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')

LOGGER = logging.getLogger(__name__)

# yt-dlp takes most of the startup time and memory, so it is imported lazily
# (see _ensure_yt_dlp) instead of at module import.
YoutubeDL = None
DownloadError = None

# Minimum seconds between progress callbacks sent to the UI, per item.
PROGRESS_INTERVAL = 0.1

# Supported YouTube URLs: watch, shorts, live, embed, playlist, youtu.be,
# on www/m/music subdomains.
YOUTUBE_URL_REGEX = re.compile(
    r'^(https?://)?'
    r'(?:(?:www|m|music)\.)?'
    r'(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/|embed/|playlist\?(?:.*&)?list=)'
    r'|youtu\.be/)'
    r'[\w-]+',
    re.IGNORECASE
)


def _ensure_yt_dlp() -> None:
    """Import yt-dlp on first use."""
    global YoutubeDL, DownloadError
    if YoutubeDL is None or DownloadError is None:
        import yt_dlp
        if YoutubeDL is None:
            YoutubeDL = yt_dlp.YoutubeDL
        if DownloadError is None:
            DownloadError = yt_dlp.utils.DownloadError


def is_frozen() -> bool:
    """True when running from a PyInstaller build."""
    return bool(getattr(sys, 'frozen', False))


def _bundle_dir() -> str:
    """Folder holding bundled files (FFmpeg) in a packaged build."""
    if is_frozen():
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _app_data_dir() -> str:
    """Per-user folder for config, queue, history and log files."""
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        path = os.path.join(base, 'YouTubeDownloader')
    else:
        path = os.path.join(os.path.expanduser('~'), '.yt-downloader')
    os.makedirs(path, exist_ok=True)
    return path


class DownloadCancelled(Exception):
    """Raised from the progress hook to abort the running yt-dlp download."""


class DownloadPaused(DownloadCancelled):
    """Like DownloadCancelled, but partial files are kept for resuming."""


class Config:
    """Application configuration constants."""
    APP_DIR = _app_data_dir()
    CONFIG_FILE = os.path.join(APP_DIR, 'yt_downloader_config.json')
    QUEUE_FILE = os.path.join(APP_DIR, 'queue_state.json')
    HISTORY_FILE = os.path.join(APP_DIR, 'download_history.json')
    LOG_FILE = os.path.join(APP_DIR, 'yt_downloader.log')
    DEFAULT_DOWNLOAD_PATH = os.path.join(os.path.expanduser("~"), "Downloads", "YouTube")
    FFMPEG_CANDIDATES = (
        os.path.join(_bundle_dir(), 'ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg'),
        os.path.join(_bundle_dir(), 'ffmpeg', 'ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg'),
        '/usr/bin/ffmpeg',
        '/usr/local/bin/ffmpeg',
        '/opt/homebrew/bin/ffmpeg',
        r'C:\ffmpeg\bin\ffmpeg.exe',
    )

    MEDIA_TYPES = ('Video', 'Audio')
    VIDEO_QUALITIES = ('Best', '1080p', '720p', '480p', '360p')
    AUDIO_QUALITIES = ('128k', '192k', '256k', '320k')
    AUDIO_FORMATS = ('mp3', 'aac', 'wav', 'm4a')
    COOKIE_BROWSERS = ('', 'chrome', 'firefox', 'edge', 'brave', 'opera', 'vivaldi', 'chromium', 'safari')
    MAX_CONCURRENT = 3


class DownloadState:
    """Manage download state and transitions."""
    def __init__(self):
        self.downloading = False
        self.cancelled = False
        self.observers: List[Callable] = []

    def update_state(self, downloading: bool, cancelled: bool = False):
        self.downloading = downloading
        self.cancelled = cancelled
        self._notify_observers()

    def add_observer(self, observer: Callable):
        self.observers.append(observer)

    def _notify_observers(self):
        for observer in self.observers:
            observer(self.downloading, self.cancelled)


class DownloadHistory:
    """Persists a bounded list of finished downloads."""
    def __init__(self, history_file: str = Config.HISTORY_FILE, max_entries: int = 100):
        self.history_file = history_file
        self.max_entries = max_entries
        self.lock = threading.Lock()
        self.history: List[Dict[str, Any]] = self.load_history()

    def add_entry(self, url: str, title: str, format: str, status: str) -> None:
        entry = {
            'url': url,
            'title': title,
            'format': format,
            'status': status,
            'timestamp': datetime.now().isoformat()
        }
        with self.lock:
            self.history.insert(0, entry)
            self.history = self.history[:self.max_entries]
            self.save_history()

    def load_history(self) -> List[Dict[str, Any]]:
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            LOGGER.error(f"Error loading download history: {e}")
            return []

    def save_history(self) -> None:
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, indent=2)
        except OSError as e:
            LOGGER.error(f"Error saving download history: {e}")


class DownloadManager:
    """
    Manages the download queue and runs YouTube downloads with yt-dlp,
    several at a time (config 'max_concurrent').
    """
    CONFIG_FILE: str = Config.CONFIG_FILE
    QUEUE_FILE: str = Config.QUEUE_FILE
    MAX_RETRIES: int = 3
    RETRY_DELAY: int = 5
    MEDIA_TYPES = Config.MEDIA_TYPES
    VIDEO_QUALITIES = Config.VIDEO_QUALITIES
    AUDIO_QUALITIES = Config.AUDIO_QUALITIES
    AUDIO_FORMATS = Config.AUDIO_FORMATS

    def __init__(self) -> None:
        self._migrate_legacy_files()
        self.config: OrderedDict = self.load_config()
        self.state = DownloadState()
        self.history = DownloadHistory()
        self.queue_lock = threading.RLock()

        # Item bookkeeping (all guarded by queue_lock).
        self.download_queue: deque = deque()          # waiting to start
        self.active: Dict[str, Dict[str, Any]] = {}   # downloading now
        self.paused: Dict[str, Dict[str, Any]] = {}   # paused, .part files kept
        self.finished: Dict[str, Dict[str, Any]] = {}  # failed/cancelled, for retry
        self._stop_requests: Dict[str, str] = {}      # item id -> 'pause' | 'cancel'
        self._workers = 0
        self._failed_in_run = 0
        self._last_progress: Dict[str, float] = {}

        # Callbacks for UI feedback. They are called from worker threads.
        self.on_progress: Optional[Callable[[str, float, str, str, str, float], None]] = None
        self.on_status: Optional[Callable[[str, str], None]] = None
        self.on_complete: Optional[Callable[[bool], None]] = None
        self.on_item_status: Optional[Callable[[str, str], None]] = None
        self.on_item_title: Optional[Callable[[str, str], None]] = None

        self.setup_logging()
        self._load_queue_state()

    @staticmethod
    def _migrate_legacy_files() -> None:
        """Move data files that older versions wrote to the working directory."""
        for target in (Config.CONFIG_FILE, Config.QUEUE_FILE, Config.HISTORY_FILE):
            legacy = os.path.abspath(os.path.basename(target))
            if legacy != target and os.path.isfile(legacy) and not os.path.exists(target):
                try:
                    shutil.move(legacy, target)
                except OSError as e:
                    LOGGER.error(f"Could not migrate {legacy}: {e}")

    def setup_logging(self) -> None:
        """Log to Config.LOG_FILE (attached once, even with several managers)."""
        root_logger = logging.getLogger()
        log_path = os.path.abspath(Config.LOG_FILE)
        already_attached = any(
            isinstance(h, logging.FileHandler) and h.baseFilename == log_path
            for h in root_logger.handlers
        )
        if not already_attached:
            handler = logging.FileHandler(log_path, mode='a', encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            root_logger.addHandler(handler)
        if root_logger.level == logging.NOTSET or root_logger.level > logging.INFO:
            root_logger.setLevel(logging.INFO)
        logging.info("DownloadManager initialized.")

    # ==============================
    # Configuration Management
    # ==============================

    def load_config(self) -> OrderedDict:
        """Load the config file (if any) and fill in validated defaults."""
        config: dict = {}
        try:
            if os.path.exists(self.CONFIG_FILE):
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f, object_pairs_hook=OrderedDict)
                if isinstance(loaded, dict):
                    config = loaded
        except (OSError, ValueError) as e:
            logging.error(f"Config load error: {str(e)}")
        # Always validate so a first run (no config file) still gets defaults.
        return self.validate_config(config)

    def validate_config(self, config: dict) -> OrderedDict:
        """Return a config with every key present and every value valid."""
        validated = OrderedDict()

        default_download_path = Config.DEFAULT_DOWNLOAD_PATH
        download_path = config.get('download_path') or default_download_path
        try:
            os.makedirs(download_path, exist_ok=True)
            validated['download_path'] = download_path
        except OSError as e:
            logging.error(f"Error creating download directory: {e}")
            validated['download_path'] = default_download_path

        # Cheap existence check only; the full `ffmpeg -version` check runs
        # when a download is started (validate_paths).
        ffmpeg_path = config.get('ffmpeg_path', '')
        if not self._ffmpeg_exists(ffmpeg_path):
            ffmpeg_path = self.find_ffmpeg(verify=False) or ffmpeg_path
        validated['ffmpeg_path'] = ffmpeg_path

        v = self._validate_value
        validated['theme'] = v(config.get('theme'), ('light', 'dark'), 'light')
        validated['media_type'] = v(config.get('media_type'), self.MEDIA_TYPES, 'Video')
        validated['video_resolution'] = v(config.get('video_resolution'), self.VIDEO_QUALITIES, 'Best')
        validated['audio_quality'] = v(config.get('audio_quality'), self.AUDIO_QUALITIES, '192k')
        validated['audio_format'] = v(config.get('audio_format'), self.AUDIO_FORMATS, 'mp3')

        validated['max_concurrent'] = self._validate_int(config.get('max_concurrent'), 1, Config.MAX_CONCURRENT, 2)
        validated['rate_limit_kb'] = self._validate_int(config.get('rate_limit_kb'), 0, 1_000_000, 0)
        validated['embed_subtitles'] = self._validate_bool(config.get('embed_subtitles'), False)
        langs = config.get('subtitle_langs')
        validated['subtitle_langs'] = langs.strip() if isinstance(langs, str) and langs.strip() else 'en,id'
        validated['embed_thumbnail'] = self._validate_bool(config.get('embed_thumbnail'), True)
        validated['add_metadata'] = self._validate_bool(config.get('add_metadata'), True)
        validated['cookies_browser'] = v(config.get('cookies_browser'), Config.COOKIE_BROWSERS, '')
        validated['watch_clipboard'] = self._validate_bool(config.get('watch_clipboard'), True)
        return validated

    @staticmethod
    def _validate_value(value: Any, valid_values: tuple, default: Any) -> Any:
        return value if value in valid_values else default

    @staticmethod
    def _validate_int(value: Any, low: int, high: int, default: int) -> int:
        if isinstance(value, bool):
            return default
        try:
            number = int(value)
        except (TypeError, ValueError):
            return default
        return number if low <= number <= high else default

    @staticmethod
    def _validate_bool(value: Any, default: bool) -> bool:
        return value if isinstance(value, bool) else default

    def update_config(self, key: str, value: Any) -> None:
        """Set one config value (validated) and save."""
        candidate = dict(self.config)
        candidate[key] = value
        self.config[key] = self.validate_config(candidate).get(key, value)
        self.save_config()

    def save_config(self) -> None:
        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
            logging.info("Configuration saved successfully.")
        except OSError as e:
            logging.error(f"Config save failed: {str(e)}")

    # ==============================
    # Queue Management
    # ==============================

    @staticmethod
    def _public(item: Dict[str, Any]) -> Dict[str, Any]:
        """Copy of an item without runtime-only keys (those start with '_')."""
        return {k: v for k, v in item.items() if not k.startswith('_')}

    def _load_queue_state(self) -> None:
        try:
            if not os.path.exists(self.QUEUE_FILE):
                return
            with open(self.QUEUE_FILE, 'r', encoding='utf-8') as f:
                queue_items = json.load(f)
            for item in queue_items:
                if not isinstance(item, dict) or 'url' not in item:
                    continue
                item.setdefault('id', uuid.uuid4().hex)
                if item.get('state') == 'paused':
                    self.paused[item['id']] = item
                else:
                    item['state'] = 'queued'
                    self.download_queue.append(item)
        except (OSError, ValueError) as e:
            LOGGER.error(f"Error loading queue state: {e}")

    def _save_queue_state(self) -> None:
        """Persist waiting, active and paused items so they survive a restart."""
        with self.queue_lock:
            items = [dict(self._public(i), state='queued') for i in self.active.values()]
            items += [dict(self._public(i), state='queued') for i in self.download_queue]
            items += [dict(self._public(i), state='paused') for i in self.paused.values()]
        try:
            with open(self.QUEUE_FILE, 'w', encoding='utf-8') as f:
                json.dump(items, f)
        except OSError as e:
            LOGGER.error(f"Error saving queue state: {e}")

    def add_to_queue(self, item: Dict[str, Any]) -> bool:
        with self.queue_lock:
            item.setdefault('id', uuid.uuid4().hex)
            item['state'] = 'queued'
            self.download_queue.append(item)
        self._save_queue_state()
        return True

    def get_queue(self) -> List[Dict[str, Any]]:
        """Waiting items (not yet started), in order."""
        with self.queue_lock:
            return list(self.download_queue)

    def get_items(self) -> List[Dict[str, Any]]:
        """Every item the UI should show on startup: waiting and paused."""
        with self.queue_lock:
            return list(self.download_queue) + list(self.paused.values())

    def update_item(self, item_id: str, **fields: Any) -> bool:
        """Change fields (e.g. playlist_items) of a waiting, paused or finished item."""
        with self.queue_lock:
            item = next((i for i in self.download_queue if i['id'] == item_id), None) \
                or self.paused.get(item_id) or self.finished.get(item_id)
            if item is None:
                return False
            item.update(fields)
        self._save_queue_state()
        return True

    def remove_from_queue(self, item_id: str) -> None:
        """Remove a waiting, paused or finished item. Active items must be cancelled first."""
        with self.queue_lock:
            for item in list(self.download_queue):
                if item.get('id') == item_id:
                    self.download_queue.remove(item)
            self.paused.pop(item_id, None)
            self.finished.pop(item_id, None)
        self._save_queue_state()

    def clear_queue(self) -> None:
        """Remove every waiting and paused item (active downloads keep running)."""
        with self.queue_lock:
            self.download_queue.clear()
            self.paused.clear()
            self.finished.clear()
        self._save_queue_state()

    # ==============================
    # Download Control
    # ==============================

    def preload(self) -> None:
        """Import yt-dlp in the background so the first download starts quickly."""
        threading.Thread(target=_ensure_yt_dlp, daemon=True).start()

    def start_download(self) -> None:
        """Start (or top up) worker threads for the waiting items."""
        with self.queue_lock:
            if not self.download_queue:
                logging.info("Download queue is empty. Nothing to start.")
                return
            starting = not self.state.downloading
            if starting:
                self._failed_in_run = 0
                self.state.update_state(True)
            wanted = min(self.config.get('max_concurrent', 1), len(self.download_queue) + len(self.active))
            new_workers = max(wanted - self._workers, 0)
            self._workers += new_workers
        for _ in range(new_workers):
            threading.Thread(target=self._worker, daemon=True).start()
        logging.info(f"Download process started ({new_workers} new worker(s)).")

    def cancel_download(self) -> None:
        """Cancel everything that is downloading; waiting items stay queued."""
        with self.queue_lock:
            if not self.state.downloading:
                return
            for item_id in self.active:
                self._stop_requests[item_id] = 'cancel'
            self.state.update_state(True, True)
        logging.info("Cancellation requested.")
        if self.on_status:
            self.on_status("Cancelling…", "orange")

    def cancel_item(self, item_id: str) -> None:
        """Cancel one active download."""
        with self.queue_lock:
            if item_id in self.active:
                self._stop_requests[item_id] = 'cancel'

    def pause_item(self, item_id: str) -> bool:
        """Pause an active or waiting item. Returns True if something was paused."""
        with self.queue_lock:
            if item_id in self.active:
                self._stop_requests[item_id] = 'pause'
                return True
            for item in list(self.download_queue):
                if item['id'] == item_id:
                    self.download_queue.remove(item)
                    item['state'] = 'paused'
                    self.paused[item_id] = item
                    break
            else:
                return False
        self._set_item_status(item_id, 'Paused')
        self._save_queue_state()
        return True

    def resume_item(self, item_id: str) -> bool:
        """Put a paused item back at the front of the queue and start downloading."""
        with self.queue_lock:
            item = self.paused.pop(item_id, None)
            if item is None:
                return False
            item['state'] = 'queued'
            self.download_queue.appendleft(item)
        self._set_item_status(item_id, 'Queued')
        self._save_queue_state()
        self.start_download()
        return True

    def retry_item(self, item_id: str) -> bool:
        """Queue a failed or cancelled item again and start downloading."""
        with self.queue_lock:
            item = self.finished.pop(item_id, None)
            if item is None:
                return False
            item['state'] = 'queued'
            self.download_queue.append(item)
        self._set_item_status(item_id, 'Queued')
        self._save_queue_state()
        self.start_download()
        return True

    def _set_item_status(self, item_id: str, status: str) -> None:
        if self.on_item_status:
            self.on_item_status(item_id, status)

    def _worker(self) -> None:
        """Take items from the queue until it is empty or everything is cancelled."""
        while True:
            with self.queue_lock:
                if self.state.cancelled or not self.download_queue or \
                        len(self.active) >= self.config.get('max_concurrent', 1):
                    break
                item = self.download_queue.popleft()
                item['state'] = 'active'
                item['_files'] = set()
                self.active[item['id']] = item
            self._save_queue_state()
            self._run_item(item)

        with self.queue_lock:
            self._workers -= 1
            last = self._workers == 0
            if last:
                cancelled = self.state.cancelled
                failed = self._failed_in_run
                self.state.update_state(False, cancelled)
        if last:
            if self.on_status and cancelled:
                self.on_status("Downloads cancelled", "orange")
            if self.on_complete:
                # Success only when nothing failed and the user did not cancel.
                self.on_complete(failed == 0 and not cancelled)
            logging.info("Download processing completed.")

    def _run_item(self, item: Dict[str, Any]) -> None:
        item_id = item['id']
        self._set_item_status(item_id, 'Downloading')
        result = 'Failed'
        try:
            result = 'Complete' if self.run_download(item) else 'Failed'
        except DownloadPaused:
            result = 'Paused'
        except DownloadCancelled:
            result = 'Cancelled'
        except Exception as e:
            logging.error(f"Download error for {item.get('url')}: {str(e)}")
            if self.on_status:
                self.on_status(f"Download failed: {self.parse_error(e)}", "red")

        with self.queue_lock:
            self.active.pop(item_id, None)
            self._stop_requests.pop(item_id, None)
            self._last_progress.pop(item_id, None)
            files = item.pop('_files', set())
            if result == 'Paused':
                item['state'] = 'paused'
                self.paused[item_id] = item
            elif result in ('Failed', 'Cancelled'):
                item['state'] = result.lower()
                self.finished[item_id] = item
            if result == 'Failed':
                self._failed_in_run += 1
        self._save_queue_state()

        if result == 'Cancelled':
            self._remove_partial_files(files)
        if result != 'Paused':
            fmt = item.get('quality', '') if item.get('media_type') == 'Video' \
                else f"{item.get('audio_format', '')} {item.get('quality', '')}"
            self.history.add_entry(item.get('url'), item.get('title') or item.get('url'), fmt, result)
        logging.info(f"{result}: {item.get('url')}")
        self._set_item_status(item_id, result)

    @staticmethod
    def _remove_partial_files(files: set) -> None:
        """Delete the partial files of one cancelled download (not other downloads')."""
        for name in files:
            for path in {name, name + '.part', name + '.ytdl'} | set(glob.glob(glob.escape(name) + '.part-Frag*')):
                if path.endswith(('.part', '.ytdl')) or '.part-Frag' in path:
                    try:
                        os.remove(path)
                    except OSError:
                        pass

    def _check_stop(self, item: Dict[str, Any]) -> None:
        """Raise if this item (or everything) should stop."""
        request = self._stop_requests.get(item['id'])
        if request == 'pause':
            raise DownloadPaused()
        if request == 'cancel' or self.state.cancelled:
            raise DownloadCancelled()

    def run_download(self, item: Dict[str, Any]) -> bool:
        """
        Downloads a single item, retrying up to MAX_RETRIES times.

        :return: True on success, False on permanent failure.
        :raises DownloadCancelled / DownloadPaused: if the user stopped it.
        """
        for attempt in range(1, self.MAX_RETRIES + 1):
            self._check_stop(item)
            try:
                _ensure_yt_dlp()
                with YoutubeDL(self.build_ydl_opts(item)) as ydl:
                    try:
                        # process=False only resolves metadata (cheap for playlists).
                        info = ydl.extract_info(item['url'], download=False, process=False)
                    except DownloadError as e:
                        if 'Video unavailable' in str(e):
                            if self.on_status:
                                self.on_status(f"Video unavailable: {item['url']}", "red")
                            return False
                        raise

                    item['title'] = info.get('title') or item['url']
                    if self.on_item_title:
                        self.on_item_title(item['id'], item['title'])
                    self._check_stop(item)
                    ydl.download([item['url']])

                if self.on_status:
                    self.on_status(f"Downloaded: {item['title']}", "green")
                return True

            except DownloadCancelled:
                raise
            except Exception as e:
                self._check_stop(item)
                error_msg = str(e)

                if 'HTTP Error 429' in error_msg:
                    delay = min(60 * attempt, 300)
                    if self.on_status:
                        self.on_status(f"Rate limited by YouTube. Waiting {delay} seconds…", "orange")
                    self._interruptible_sleep(item, delay)
                    continue

                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAY * attempt
                    if self.on_status:
                        self.on_status(f"Download failed. Retrying in {delay} seconds… "
                                       f"({attempt}/{self.MAX_RETRIES})", "orange")
                    self._interruptible_sleep(item, delay)
                else:
                    logging.error(f"All attempts failed for {item.get('url')}: {error_msg}")
                    if self.on_status:
                        self.on_status(f"Download failed: {self.parse_error(e)}", "red")
                    return False
        return False

    def _interruptible_sleep(self, item: Dict[str, Any], seconds: float) -> None:
        """Sleep, but wake up (and raise) as soon as the item is paused or cancelled."""
        end = time.time() + seconds
        while time.time() < end:
            self._check_stop(item)
            time.sleep(0.2)

    def build_ydl_opts(self, item: Dict[str, Any]) -> dict:
        """Build the yt-dlp options for one queue item from it and the global config."""
        playlist = self.is_playlist_url(item['url'])
        if playlist:
            # Keep each playlist in its own folder, in playlist order.
            name = os.path.join('%(playlist_title)s', '%(playlist_index)03d - %(title)s [%(id)s].%(ext)s')
        else:
            name = '%(title)s [%(id)s].%(ext)s'
        cfg = self.config
        opts: dict = {
            'outtmpl': os.path.join(item['path'], name),
            'noplaylist': not playlist,
            'ignoreerrors': 'only_download' if playlist else False,
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
            'ffmpeg_location': item.get('ffmpeg_path') or cfg.get('ffmpeg_path') or None,
            'progress_hooks': [lambda d, item=item: self.progress_hook(item, d)],
            'retries': 10,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True,
            'continuedl': True,
        }
        if item.get('playlist_items'):
            opts['playlist_items'] = item['playlist_items']

        # A total speed limit is shared between the parallel downloads.
        if cfg.get('rate_limit_kb'):
            opts['ratelimit'] = cfg['rate_limit_kb'] * 1024 // max(cfg.get('max_concurrent', 1), 1)
        if cfg.get('cookies_browser'):
            opts['cookiesfrombrowser'] = (cfg['cookies_browser'],)

        postprocessors: List[dict] = []
        if item['media_type'] == 'Video':
            # Any codec is allowed so 1440p/4K (VP9/AV1) is not skipped;
            # the result is merged into an MP4 container.
            if item['quality'] == 'Best':
                opts['format'] = 'bestvideo+bestaudio/best'
            else:
                res = item['quality'].rstrip('p')
                opts['format'] = f'bestvideo[height<={res}]+bestaudio/best[height<={res}]/best'
            opts['merge_output_format'] = 'mp4'
            if cfg.get('embed_subtitles'):
                opts['writesubtitles'] = True
                opts['writeautomaticsub'] = True
                opts['subtitleslangs'] = [lang.strip() for lang in cfg.get('subtitle_langs', 'en').split(',')
                                          if lang.strip()]
                postprocessors.append({'key': 'FFmpegEmbedSubtitle', 'already_have_subtitle': False})
        else:
            opts['format'] = 'bestaudio/best'
            postprocessors.append({
                'key': 'FFmpegExtractAudio',
                'preferredcodec': item['audio_format'],
                'preferredquality': item['quality'].rstrip('k'),
            })

        if cfg.get('add_metadata'):
            postprocessors.append({'key': 'FFmpegMetadata', 'add_metadata': True})
        # WAV has no cover-art support.
        if cfg.get('embed_thumbnail') and not (item['media_type'] == 'Audio' and item['audio_format'] == 'wav'):
            opts['writethumbnail'] = True
            postprocessors.append({'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg', 'when': 'before_dl'})
            postprocessors.append({'key': 'EmbedThumbnail', 'already_have_thumbnail': False})
        if postprocessors:
            opts['postprocessors'] = postprocessors
        return opts

    # ==============================
    # Video information (preview)
    # ==============================

    def fetch_info(self, url: str) -> Dict[str, Any]:
        """
        Fetch metadata for the preview dialog without downloading.
        Playlists are listed flat (titles only) so this stays fast.
        """
        _ensure_yt_dlp()
        opts = {'quiet': True, 'no_warnings': True, 'skip_download': True,
                'noplaylist': not self.is_playlist_url(url), 'extract_flat': 'in_playlist'}
        if self.config.get('cookies_browser'):
            opts['cookiesfrombrowser'] = (self.config['cookies_browser'],)
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        summary = {
            'title': info.get('title') or url,
            'uploader': info.get('uploader') or info.get('channel') or '',
            'duration': info.get('duration'),
            'thumbnail': info.get('thumbnail') or '',
            'view_count': info.get('view_count'),
            'filesize': info.get('filesize') or info.get('filesize_approx'),
            'entries': [],
        }
        if info.get('_type') == 'playlist':
            for index, entry in enumerate(info.get('entries') or [], start=1):
                if entry:
                    summary['entries'].append({'index': index, 'title': entry.get('title') or entry.get('url', ''),
                                               'duration': entry.get('duration')})
        else:
            # Size of the best video+audio, as a rough estimate.
            sizes = [f.get('filesize') or f.get('filesize_approx') or 0 for f in info.get('formats') or []
                     if f.get('vcodec') != 'none' or f.get('acodec') != 'none']
            if sizes and not summary['filesize']:
                summary['filesize'] = max(sizes)
        return summary

    # ==============================
    # Progress and Error Handling
    # ==============================

    def progress_hook(self, item: Dict[str, Any], d: dict) -> None:
        """yt-dlp progress hook for one item; also where pause/cancel take effect."""
        # yt-dlp has no cancel API; raising here aborts the download.
        self._check_stop(item)
        for key in ('tmpfilename', 'filename'):
            if d.get(key) and '_files' in item:
                item['_files'].add(d[key])
        if d.get('status') != 'downloading':
            return
        try:
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded_bytes = d.get('downloaded_bytes') or 0
            percent = (downloaded_bytes / total_bytes) * 100 if total_bytes else 0.0

            # yt-dlp calls this for every chunk; limit UI updates per item.
            now = time.monotonic()
            if percent < 100 and now - self._last_progress.get(item['id'], 0) < PROGRESS_INTERVAL:
                return
            self._last_progress[item['id']] = now

            speed = ANSI_REGEX.sub('', d.get('_speed_str') or 'N/A').strip()
            eta = ANSI_REGEX.sub('', d.get('_eta_str') or 'N/A').strip()
            size_str = f"{downloaded_bytes / 1048576:.1f}MB / {total_bytes / 1048576:.1f}MB"
            if self.on_progress:
                self.on_progress(item['id'], percent, speed, eta, size_str, float(d.get('speed') or 0))
        except Exception as e:
            logging.error(f"Error in progress hook: {str(e)}")

    def parse_error(self, error: Exception) -> str:
        """Short, user-friendly description of a download error."""
        error_str = str(error).lower()
        if 'sign in to confirm your age' in error_str or 'age restricted' in error_str or 'age-restricted' in error_str:
            return "Age-restricted — set 'Cookies from browser' in Settings"
        if 'members-only' in error_str or 'join this channel' in error_str:
            return "Members-only — set 'Cookies from browser' in Settings"
        if 'private video' in error_str:
            return "Private video"
        if 'unavailable' in error_str:
            return "Content unavailable"
        if 'requested format' in error_str:
            return "Format not available"
        if 'ffmpeg' in error_str:
            return "FFmpeg problem — check the FFmpeg path in Settings"
        if 'http error 403' in error_str or 'unable to extract' in error_str:
            return "YouTube changed something — try updating yt-dlp in Settings"
        return str(error).replace('ERROR: ', '')[:200]

    # ==============================
    # yt-dlp version / update
    # ==============================

    @staticmethod
    def get_yt_dlp_version() -> str:
        """Installed yt-dlp version, read without importing yt-dlp."""
        if YoutubeDL is not None and 'yt_dlp' in sys.modules:
            try:
                return sys.modules['yt_dlp'].version.__version__
            except AttributeError:
                pass
        try:
            from importlib.metadata import version
            return version('yt-dlp')
        except Exception:
            return 'unknown'

    @staticmethod
    def update_yt_dlp() -> Tuple[bool, str]:
        """Upgrade yt-dlp with pip. Takes effect after restarting the app."""
        if is_frozen():
            return False, ("This build bundles yt-dlp. Download the latest release of the app "
                           "to get a newer yt-dlp.")
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', '--upgrade', 'yt-dlp'],
                capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as e:
            return False, f"Update failed: {e}"
        if result.returncode != 0:
            tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
            return False, "Update failed:\n" + "\n".join(tail)
        if 'Requirement already satisfied: yt-dlp' in result.stdout and 'Successfully installed' not in result.stdout:
            return True, "yt-dlp is already up to date."
        return True, "yt-dlp was updated. Restart the app to use the new version."

    # ==============================
    # Validation Methods
    # ==============================

    def validate_paths(self, download_path: str, ffmpeg_path: str) -> bool:
        """True if the download folder exists (or can be created) and FFmpeg works."""
        try:
            os.makedirs(download_path, exist_ok=True)
            valid_dl = True
        except OSError as e:
            logging.error(f"Download path validation error: {str(e)}")
            valid_dl = False
        return valid_dl and self.validate_ffmpeg(ffmpeg_path)

    @staticmethod
    def _ffmpeg_exists(path: str) -> bool:
        return bool(path) and (os.path.isfile(path) or shutil.which(path) is not None)

    def find_ffmpeg(self, verify: bool = True) -> str:
        """Return the first FFmpeg found next to the app, on PATH or in common folders."""
        candidates = [p for p in Config.FFMPEG_CANDIDATES[:2] if os.path.isfile(p)]
        candidates.append(shutil.which('ffmpeg'))
        candidates += [p for p in Config.FFMPEG_CANDIDATES[2:] if os.path.isfile(p)]
        for candidate in candidates:
            if candidate and (not verify or self.validate_ffmpeg(candidate)):
                return candidate
        return ''

    def validate_ffmpeg(self, path: str) -> bool:
        """True if `path -version` runs and identifies itself as FFmpeg."""
        if not path:
            return False
        try:
            kwargs = {}
            if sys.platform == 'win32':
                kwargs['creationflags'] = 0x08000000  # CREATE_NO_WINDOW: no console flash
            result = subprocess.run([path, '-version'], capture_output=True, text=True,
                                    check=True, timeout=10, **kwargs)
            return 'ffmpeg version' in result.stdout.lower()
        except (subprocess.SubprocessError, OSError) as e:
            logging.error(f"FFmpeg validation error: {str(e)}")
            return False

    def validate_url(self, url: str) -> bool:
        """True if the URL looks like a supported YouTube link."""
        return bool(YOUTUBE_URL_REGEX.match(url.strip()))

    @staticmethod
    def is_playlist_url(url: str) -> bool:
        """True for playlist pages (not a single video that carries a list= param)."""
        return bool(re.search(r'youtube\.com/playlist\?', url))

    def get_history(self) -> List[Dict[str, Any]]:
        with self.history.lock:
            return list(self.history.history)

    def cleanup(self) -> None:
        """Stop downloads (keeping partial files so they resume next time) and save."""
        with self.queue_lock:
            for item_id in self.active:
                self._stop_requests[item_id] = 'pause'
        self._save_queue_state()
        self.save_config()
