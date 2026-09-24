import os
import re
import json
import logging
import threading
import time
import subprocess
import glob
import shutil
import sys
import uuid
from collections import deque, OrderedDict
from typing import Optional, Callable, Any, Dict, List
from yt_dlp import YoutubeDL, DownloadError
from datetime import datetime

# Regular expression to strip ANSI escape codes from progress strings.
ANSI_REGEX = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')

LOGGER = logging.getLogger(__name__)

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


class DownloadCancelled(Exception):
    """Raised from the progress hook to abort the running yt-dlp download."""

def _app_data_dir() -> str:
    """Per-user folder for config, queue, history and log files."""
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        path = os.path.join(base, 'YouTubeDownloader')
    else:
        path = os.path.join(os.path.expanduser('~'), '.yt-downloader')
    os.makedirs(path, exist_ok=True)
    return path


class Config:
    """Application configuration constants."""
    APP_DIR = _app_data_dir()
    CONFIG_FILE = os.path.join(APP_DIR, 'yt_downloader_config.json')
    QUEUE_FILE = os.path.join(APP_DIR, 'queue_state.json')
    HISTORY_FILE = os.path.join(APP_DIR, 'download_history.json')
    LOG_FILE = os.path.join(APP_DIR, 'yt_downloader.log')
    DEFAULT_DOWNLOAD_PATH = os.path.join(os.path.expanduser("~"), "Downloads", "YouTube")
    FFMPEG_CANDIDATES = (
        '/usr/bin/ffmpeg',
        '/usr/local/bin/ffmpeg',
        '/opt/homebrew/bin/ffmpeg',
        'C:\ffmpeg\bin\ffmpeg.exe',
    )

    MEDIA_TYPES = ('Video', 'Audio')
    VIDEO_QUALITIES = ('Best', '1080p', '720p', '480p', '360p')
    AUDIO_QUALITIES = ('128k', '192k', '256k', '320k')
    AUDIO_FORMATS = ('mp3', 'aac', 'wav', 'm4a')


class DownloadState:
    """Manage download state and transitions."""
    def __init__(self):
        self.downloading = False
        self.cancelled = False
        self.current_item = None
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
    Manages the download queue and performs YouTube downloads using yt-dlp.
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
        """
        Initializes the download manager, including configuration, queue, and logging.
        """
        self._migrate_legacy_files()
        self.config: OrderedDict = self.load_config()
        self.download_queue: deque[Dict[str, Any]] = deque()
        self.state = DownloadState()
        self.history = DownloadHistory()
        self.queue_lock = threading.Lock()
        self.current_download: Optional[YoutubeDL] = None

        # Callback functions for UI feedback
        self.on_progress: Optional[Callable[[float, str, str, str], None]] = None
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
        """
        Sets up logging to a file with INFO level.
        """
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
        """
        Loads and validates configuration from the config file.

        :return: An OrderedDict containing configuration parameters.
        """
        try:
            if os.path.exists(self.CONFIG_FILE):
                with open(self.CONFIG_FILE, 'r') as f:
                    config = json.load(f, object_pairs_hook=OrderedDict)
                    validated_config = self.validate_config(config)
                    logging.info("Configuration loaded and validated.")
                    return validated_config
        except (json.JSONDecodeError, Exception) as e:
            logging.error(f"Config load error: {str(e)}")
        return OrderedDict()

    def validate_config(self, config: dict) -> OrderedDict:
        """
        Validates and sets default configuration values with improved path handling.
        """
        validated = OrderedDict()
        
        default_download_path = Config.DEFAULT_DOWNLOAD_PATH
        
        # Validate and create download path if it doesn't exist
        download_path = config.get('download_path', default_download_path)
        try:
            os.makedirs(download_path, exist_ok=True)
            validated['download_path'] = download_path
        except Exception as e:
            logging.error(f"Error creating download directory: {e}")
            validated['download_path'] = default_download_path
        
        # Try to find FFmpeg in common locations
        ffmpeg_path = config.get('ffmpeg_path', '')
        if not self.validate_ffmpeg(ffmpeg_path):
            ffmpeg_path = self.find_ffmpeg() or ffmpeg_path
                
        validated['ffmpeg_path'] = ffmpeg_path
        
        # Validate media options
        validated['media_type'] = self._validate_value(config.get('media_type'), self.MEDIA_TYPES, 'Video')
        validated['video_resolution'] = self._validate_value(config.get('video_resolution'), self.VIDEO_QUALITIES, 'Best')
        validated['audio_quality'] = self._validate_value(config.get('audio_quality'), self.AUDIO_QUALITIES, '128k')
        validated['audio_format'] = self._validate_value(config.get('audio_format'), self.AUDIO_FORMATS, 'mp3')
        
        return validated

    def _validate_value(self, value: Any, valid_values: tuple, default: Any) -> Any:
        """
        Validates that a value is within the accepted options.

        :param value: The value to validate.
        :param valid_values: A tuple of valid options.
        :param default: The default value if validation fails.
        :return: The original value if valid, otherwise the default.
        """
        return value if value in valid_values else default

    def save_config(self) -> None:
        """
        Saves the current configuration to a file.
        """
        try:
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=2)
            logging.info("Configuration saved successfully.")
        except Exception as e:
            logging.error(f"Config save failed: {str(e)}")

    # ==============================
    # Queue Management
    # ==============================

    def _load_queue_state(self) -> None:
        """Load saved queue state from file."""
        try:
            if os.path.exists(self.QUEUE_FILE):
                with open(self.QUEUE_FILE, 'r') as f:
                    queue_items = json.load(f)
                for item in queue_items:
                    if item.get('status') != 'Complete':
                        item.setdefault('id', uuid.uuid4().hex)
                        self.download_queue.append(item)
        except Exception as e:
            LOGGER.error(f"Error loading queue state: {e}")

    def _save_queue_state(self) -> None:
        """Save current queue state to file."""
        try:
            queue_items = list(self.download_queue)
            with open(self.QUEUE_FILE, 'w') as f:
                json.dump(queue_items, f)
        except Exception as e:
            LOGGER.error(f"Error saving queue state: {e}")

    def add_to_queue(self, item: Dict[str, Any]) -> bool:
        """Add an item to the download queue."""
        with self.queue_lock:
            item.setdefault('id', uuid.uuid4().hex)
            self.download_queue.append(item)
            self._save_queue_state()
            return True

    def get_queue(self) -> List[Dict[str, Any]]:
        """Return a snapshot of the pending queue items."""
        with self.queue_lock:
            return list(self.download_queue)

    def remove_from_queue(self, item_id: str) -> None:
        """Remove the pending item with the given id from the download queue."""
        with self.queue_lock:
            for item in self.download_queue:
                if item.get('id') == item_id:
                    self.download_queue.remove(item)
                    self._save_queue_state()
                    break

    def clear_queue(self) -> None:
        """Clear the entire download queue."""
        with self.queue_lock:
            self.download_queue.clear()
            self._save_queue_state()

    # ==============================
    # Download Control
    # ==============================

    def start_download(self) -> None:
        """
        Initiates the download process in a separate thread.
        """
        if not self.download_queue:
            logging.info("Download queue is empty. Nothing to start.")
            return

        self.state.update_state(True)
        threading.Thread(target=self.process_queue, daemon=True).start()
        logging.info("Download process started.")

    def cancel_download(self) -> None:
        """
        Signals the current download to stop. The running download is aborted
        from within progress_hook, which raises DownloadCancelled.
        """
        self.state.update_state(self.state.downloading, True)
        logging.info("Cancellation requested.")
        if self.on_status:
            self.on_status("Cancelling download...", "orange")

    def _remove_partial_files(self, item: Dict[str, Any]) -> None:
        """Delete yt-dlp partial download files left in the item's folder."""
        for partial_file in glob.glob(os.path.join(glob.escape(item['path']), '*.part')):
            try:
                os.remove(partial_file)
            except OSError:
                pass

    def _set_item_status(self, item: Dict[str, Any], status: str) -> None:
        if self.on_item_status:
            self.on_item_status(item.get('id'), status)

    def process_queue(self) -> None:
        """
        Processes items in the download queue until cancelled or the queue is empty.
        Calls the on_complete callback once processing finishes.
        """
        failed = 0
        while not self.state.cancelled:
            with self.queue_lock:
                if not self.download_queue:
                    logging.info("Download queue exhausted.")
                    break
                item = self.download_queue.popleft()
                self.state.current_item = item
                self._save_queue_state()

            self._set_item_status(item, "Downloading")
            try:
                ok = self.run_download(item)
            except DownloadCancelled:
                ok = None
            except Exception as e:
                logging.error(f"Download error for {item.get('url')}: {str(e)}")
                if self.on_status:
                    self.on_status(f"Download failed: {self.parse_error(e)}", "red")
                ok = False

            status = {None: 'Cancelled', True: 'Complete', False: 'Failed'}[ok]
            fmt = item.get('quality', '') if item.get('media_type') == 'Video' else item.get('audio_format', '')
            self.history.add_entry(item.get('url'), item.get('title', item.get('url')), fmt, status)

            if ok is None:
                self._remove_partial_files(item)
                self._set_item_status(item, "Cancelled")
                logging.info(f"Download cancelled: {item.get('url')}")
            elif ok:
                self._set_item_status(item, "Complete")
            else:
                failed += 1
                self._set_item_status(item, "Failed")

            self.state.current_item = None
            self.current_download = None

        cancelled = self.state.cancelled
        self.state.update_state(False, cancelled)
        if self.on_status and cancelled:
            self.on_status("Download cancelled", "orange")
        if self.on_complete:
            # Success only when nothing failed and the user did not cancel.
            self.on_complete(failed == 0 and not cancelled)
        logging.info("Download processing completed.")

    def run_download(self, item: Dict[str, Any]) -> bool:
        """
        Downloads a single item, retrying up to MAX_RETRIES times.

        :return: True on success, False on permanent failure.
        :raises DownloadCancelled: if the user cancelled the download.
        """
        for attempt in range(1, self.MAX_RETRIES + 1):
            if self.state.cancelled:
                raise DownloadCancelled()

            try:
                ydl_opts = self.build_ydl_opts(item)
                with YoutubeDL(ydl_opts) as ydl:
                    self.current_download = ydl
                    
                    # Extract info first to validate video availability
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
                        self.on_item_title(item.get('id'), item['title'])
                    if self.on_status:
                        self.on_status(f"Downloading: {item['title']}", "black")

                    # Perform the actual download
                    ydl.download([item['url']])
                    
                    if self.on_status:
                        self.on_status(f"Successfully downloaded: {info.get('title', item['url'])}", "green")
                        
                    logging.info(f"Download completed: {item.get('url')}")
                    return True

            except Exception as e:
                if self.state.cancelled or isinstance(e, DownloadCancelled):
                    raise DownloadCancelled()
                error_msg = str(e)
                
                # Check for specific error conditions
                if 'HTTP Error 429' in error_msg:
                    delay = min(60 * attempt, 300)  # Max 5 minute delay
                    if self.on_status:
                        self.on_status(f"Rate limited. Waiting {delay} seconds...", "orange")
                    self._interruptible_sleep(delay)
                    continue
                    
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAY * attempt
                    if self.on_status:
                        self.on_status(f"Download failed. Retrying in {delay} seconds... ({attempt}/{self.MAX_RETRIES})", "orange")
                    self._interruptible_sleep(delay)
                else:
                    logging.error(f"All attempts failed for {item.get('url')}")
                    if self.on_status:
                        self.on_status(f"Download failed after {self.MAX_RETRIES} attempts: {self.parse_error(e)}", "red")
                    return False
        return False

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep for the given time, waking early (and raising) on cancel."""
        end = time.time() + seconds
        while time.time() < end:
            if self.state.cancelled:
                raise DownloadCancelled()
            time.sleep(0.2)

    def build_ydl_opts(self, item: Dict[str, Any]) -> dict:
        """
        Builds and returns the yt-dlp options based on the download item.

        :param item: A dictionary with download parameters.
        :return: A dictionary of options for YoutubeDL.
        """
        if self.is_playlist_url(item['url']):
            # Keep each playlist in its own folder, in playlist order.
            name = os.path.join('%(playlist_title)s', '%(playlist_index)03d - %(title)s [%(id)s].%(ext)s')
        else:
            name = '%(title)s [%(id)s].%(ext)s'
        opts: dict = {
            'outtmpl': os.path.join(item['path'], name),
            'noplaylist': not self.is_playlist_url(item['url']),
            'ignoreerrors': 'only_download' if self.is_playlist_url(item['url']) else False,
            'quiet': True,
            'no_warnings': True,
            'ffmpeg_location': item['ffmpeg_path'],
            'progress_hooks': [self.progress_hook],
            'retries': 10,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True
        }

        if item['media_type'] == 'Video':
            # Any codec is allowed so 1440p/4K (VP9/AV1) is not skipped;
            # the result is merged into an MP4 container.
            if item['quality'] == 'Best':
                opts['format'] = 'bestvideo+bestaudio/best'
            else:
                res = item['quality'].rstrip('p')
                opts['format'] = f'bestvideo[height<={res}]+bestaudio/best[height<={res}]/best'
            opts['merge_output_format'] = 'mp4'
        else:
            opts['format'] = 'bestaudio/best'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': item['audio_format'],
                'preferredquality': item['quality'].rstrip('k')
            }]

        return opts

    # ==============================
    # Progress and Error Handling
    # ==============================

    def progress_hook(self, d: dict) -> None:
        """
        A hook function for yt-dlp to report progress.
        
        :param d: A dictionary containing progress information.
        """
        if self.state.cancelled:
            # yt-dlp has no cancel API; raising here aborts the download.
            raise DownloadCancelled()
        if d.get('status') == 'downloading':
            try:
                # Calculate percentage
                total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded_bytes = d.get('downloaded_bytes', 0)
                
                if total_bytes:
                    percent = (downloaded_bytes / total_bytes) * 100
                else:
                    percent = 0.0
                    
                # Format speed
                speed = ANSI_REGEX.sub('', d.get('_speed_str', 'N/A')).strip()
                
                # Format ETA
                eta = ANSI_REGEX.sub('', d.get('_eta_str', 'N/A')).strip()
                
                # Format file size
                downloaded_mb = downloaded_bytes / (1024 * 1024)
                total_mb = total_bytes / (1024 * 1024)
                size_str = f"{downloaded_mb:.1f}MB / {total_mb:.1f}MB"

                if self.on_progress:
                    self.on_progress(percent, speed, eta, size_str)
                
            except Exception as e:
                logging.error(f"Error in progress hook: {str(e)}")

    def parse_error(self, error: Exception) -> str:
        """
        Parses the error message to return a user-friendly string.

        :param error: The exception encountered.
        :return: A string describing the error.
        """
        error_str = str(error).lower()
        if 'unavailable' in error_str:
            return "Content unavailable"
        if 'age restricted' in error_str:
            return "Age-restricted content"
        if 'requested format' in error_str:
            return "Format not available"
        return f"Unknown error: {str(error)}"

    # ==============================
    # Validation Methods
    # ==============================

    def validate_paths(self, download_path: str, ffmpeg_path: str) -> bool:
        """
        Validates the download and FFmpeg paths.

        :param download_path: The directory where downloads will be saved.
        :param ffmpeg_path: The path to the FFmpeg executable.
        :return: True if both paths are valid, False otherwise.
        """
        try:
            valid_dl: bool = os.path.exists(download_path) or os.makedirs(download_path, exist_ok=True) is None
        except Exception as e:
            logging.error(f"Download path validation error: {str(e)}")
            valid_dl = False

        valid_ffmpeg: bool = self.validate_ffmpeg(ffmpeg_path)
        return valid_dl and valid_ffmpeg

    def find_ffmpeg(self) -> str:
        """Return the first working FFmpeg found on PATH or in common folders."""
        candidates = [shutil.which('ffmpeg')]
        candidates += [p for p in Config.FFMPEG_CANDIDATES if os.path.isfile(p)]
        for candidate in candidates:
            if candidate and self.validate_ffmpeg(candidate):
                return candidate
        return ''

    def validate_ffmpeg(self, path: str) -> bool:
        """
        Validates that FFmpeg is accessible and working.

        :param path: The path to the FFmpeg executable.
        :return: True if FFmpeg returns its version info, False otherwise.
        """
        if not path:
            return False
        try:
            result = subprocess.run([path, '-version'],
                                    capture_output=True,
                                    text=True,
                                    check=True,
                                    timeout=10)
            return 'ffmpeg version' in result.stdout.lower()
        except (subprocess.SubprocessError, OSError) as e:
            logging.error(f"FFmpeg validation error: {str(e)}")
            return False

    def validate_url(self, url: str) -> bool:
        """
        Validates that the URL matches common YouTube URL patterns.

        :param url: The URL to validate.
        :return: True if the URL is valid, False otherwise.
        """
        is_valid = bool(YOUTUBE_URL_REGEX.match(url.strip()))
        logging.debug(f"URL validation for '{url}': {is_valid}")
        return is_valid

    @staticmethod
    def is_playlist_url(url: str) -> bool:
        """True for playlist pages (not a single video that carries a list= param)."""
        return bool(re.search(r'youtube\.com/playlist\?', url))

    def get_history(self) -> List[Dict[str, Any]]:
        with self.history.lock:
            return list(self.history.history)

    def cleanup(self) -> None:
        """
        Performs cleanup actions before exiting the application.
        """
        if self.state.downloading:
            self.cancel_download()
        with self.queue_lock:
            # Keep the interrupted item so it is resumed on next launch.
            if self.state.current_item is not None:
                self.download_queue.appendleft(self.state.current_item)
            self._save_queue_state()
        self.save_config()
