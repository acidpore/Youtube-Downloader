import os
import re
import json
import logging
import threading
import time
import subprocess
import glob
from collections import deque, OrderedDict
from typing import Optional, Callable, Any, Dict, List
from yt_dlp import YoutubeDL, DownloadError
from datetime import datetime

# Regular expression to strip ANSI escape codes from progress strings.
ANSI_REGEX = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')

LOGGER = logging.getLogger(__name__)

class Config:
    """Application configuration constants."""
    DEFAULT_PATHS = {
        'downloads': os.path.join(os.path.expanduser("~"), "Downloads", "YouTube"),
        'ffmpeg_windows': 'C:\\ffmpeg\\bin\\ffmpeg.exe',
        'ffmpeg_linux': '/usr/bin/ffmpeg'
    }
    
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

class DownloadStats:
    """Track download statistics."""
    def __init__(self):
        self.total_downloads = 0
        self.successful_downloads = 0
        self.failed_downloads = 0
        self.total_bytes_downloaded = 0
        self.start_time = None

    def start_session(self):
        self.start_time = time.time()

    def update(self, success: bool, bytes_downloaded: int):
        self.total_downloads += 1
        self.total_bytes_downloaded += bytes_downloaded
        if success:
            self.successful_downloads += 1
        else:
            self.failed_downloads += 1

    def get_session_stats(self) -> Dict[str, Any]:
        if not self.start_time:
            return {}
        
        duration = time.time() - self.start_time
        return {
            'duration': duration,
            'total_downloads': self.total_downloads,
            'successful': self.successful_downloads,
            'failed': self.failed_downloads,
            'total_bytes': self.total_bytes_downloaded,
            'average_speed': self.total_bytes_downloaded / duration if duration > 0 else 0
        }

class DownloadHistory:
    def __init__(self, max_entries=100):
        self.history_file = 'download_history.json'
        self.max_entries = max_entries
        self.history = self.load_history()

    def add_entry(self, url, title, format, status):
        entry = {
            'url': url,
            'title': title,
            'format': format,
            'status': status,
            'timestamp': datetime.now().isoformat()
        }
        self.history.insert(0, entry)
        self.history = self.history[:self.max_entries]
        self.save_history()

    def load_history(self):
        try:
            with open(self.history_file, 'r') as f:
                return json.load(f)
        except:
            return []

    def save_history(self):
        with open(self.history_file, 'w') as f:
            json.dump(self.history, f)

class DownloadManager:
    """
    Manages the download queue and performs YouTube downloads using yt-dlp.
    """
    CONFIG_FILE: str = 'yt_downloader_config.json'
    MAX_RETRIES: int = 3
    RETRY_DELAY: int = 5
    MEDIA_TYPES = ('Video', 'Audio')
    VIDEO_QUALITIES = ('Best', '1080p', '720p', '480p', '360p')
    AUDIO_QUALITIES = ('128k', '192k', '256k', '320k')
    AUDIO_FORMATS = ('mp3', 'aac', 'wav', 'm4a')

    def __init__(self) -> None:
        """
        Initializes the download manager, including configuration, queue, and logging.
        """
        self.config: OrderedDict = self.load_config()
        self.download_queue: deque[Dict[str, Any]] = deque()
        self.state = DownloadState()
        self.stats = DownloadStats()
        self.queue_lock = threading.Lock()
        self.current_download: Optional[YoutubeDL] = None

        # Callback functions for UI feedback
        self.on_progress: Optional[Callable[[float, str, str, str], None]] = None
        self.on_status: Optional[Callable[[str, str], None]] = None
        self.on_complete: Optional[Callable[[bool], None]] = None

        self.setup_logging()
        self._load_queue_state()

    def setup_logging(self) -> None:
        """
        Sets up logging to a file with INFO level.
        """
        logging.basicConfig(
            filename='yt_downloader.log',
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            filemode='a'
        )
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
        
        # Get user's home directory for default paths
        default_download_path = os.path.join(os.path.expanduser("~"), "Downloads", "YouTube")
        
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
            common_locations = [
                'ffmpeg',  # System PATH
                '/usr/bin/ffmpeg',
                '/usr/local/bin/ffmpeg',
                'C:\\ffmpeg\\bin\\ffmpeg.exe'
            ]
            for location in common_locations:
                if self.validate_ffmpeg(location):
                    ffmpeg_path = location
                    break
                
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
            if os.path.exists('queue_state.json'):
                with open('queue_state.json', 'r') as f:
                    queue_items = json.load(f)
                for item in queue_items:
                    if item.get('status') != 'Complete':
                        self.download_queue.append(item)
        except Exception as e:
            LOGGER.error(f"Error loading queue state: {e}")

    def _save_queue_state(self) -> None:
        """Save current queue state to file."""
        try:
            queue_items = list(self.download_queue)
            with open('queue_state.json', 'w') as f:
                json.dump(queue_items, f)
        except Exception as e:
            LOGGER.error(f"Error saving queue state: {e}")

    def add_to_queue(self, item: Dict[str, Any]) -> bool:
        """Add an item to the download queue."""
        with self.queue_lock:
            self.download_queue.append(item)
            self._save_queue_state()
            return True

    def remove_from_queue(self, index: int) -> None:
        """Remove an item from the download queue."""
        with self.queue_lock:
            if 0 <= index < len(self.download_queue):
                self.download_queue.remove(index)
                self._save_queue_state()

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
        Signals the current download process to cancel with proper cleanup.
        """
        self.state.update_state(False, True)
        if self.current_download:
            try:
                self.current_download.cancel_download()
                
                # Clean up partial downloads
                if self.state.current_item:
                    partial_path = os.path.join(
                        self.state.current_item['path'],
                        '*.part'  # yt-dlp partial download files
                    )
                    for partial_file in glob.glob(partial_path):
                        try:
                            os.remove(partial_file)
                        except OSError:
                            pass
                            
                logging.info("Current download cancelled and cleaned up.")
                
                if self.on_status:
                    self.on_status("Download cancelled", "orange")
                    
            except Exception as e:
                logging.error(f"Error cancelling current download: {str(e)}")

    def process_queue(self) -> None:
        """
        Processes items in the download queue until cancelled or the queue is empty.
        Calls the on_complete callback once processing finishes.
        """
        while not self.state.cancelled:
            with self.queue_lock:
                if not self.download_queue:
                    logging.info("Download queue exhausted.")
                    break
                self.state.current_item = self.download_queue.popleft()

            try:
                self.run_download(self.state.current_item)
            except Exception as e:
                logging.error(f"Download error for {self.state.current_item.get('url')}: {str(e)}")
                self.handle_error(e, self.state.current_item)

            self.state.current_item = None

        self.state.update_state(False)
        if self.on_complete:
            # The on_complete callback receives a bool indicating whether cancellation occurred.
            self.on_complete(not self.state.cancelled)
        logging.info("Download processing completed.")

    def run_download(self, item: Dict[str, Any]) -> None:
        """
        Attempts to download a single item with improved error handling and retry logic.
        """
        for attempt in range(1, self.MAX_RETRIES + 1):
            if self.state.cancelled:
                logging.info("Download cancelled before starting.")
                return

            try:
                ydl_opts = self.build_ydl_opts(item)
                with YoutubeDL(ydl_opts) as ydl:
                    self.current_download = ydl
                    
                    # Extract info first to validate video availability
                    try:
                        info = ydl.extract_info(item['url'], download=False)
                    except DownloadError as e:
                        if 'Video unavailable' in str(e):
                            if self.on_status:
                                self.on_status(f"Video unavailable: {item['url']}", "red")
                            return
                        raise

                    if self.on_status:
                        self.on_status(f"Downloading: {info.get('title', item['url'])}", "black")

                    # Perform the actual download
                    ydl.download([item['url']])
                    
                    if self.on_status:
                        self.on_status(f"Successfully downloaded: {info.get('title', item['url'])}", "green")
                        
                    logging.info(f"Download completed: {item.get('url')}")
                    return

            except (DownloadError, Exception) as e:
                error_msg = str(e)
                
                # Check for specific error conditions
                if 'HTTP Error 429' in error_msg:
                    delay = min(60 * attempt, 300)  # Max 5 minute delay
                    if self.on_status:
                        self.on_status(f"Rate limited. Waiting {delay} seconds...", "orange")
                    time.sleep(delay)
                    continue
                    
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAY * attempt
                    if self.on_status:
                        self.on_status(f"Download failed. Retrying in {delay} seconds... ({attempt}/{self.MAX_RETRIES})", "orange")
                    time.sleep(delay)
                else:
                    logging.error(f"All attempts failed for {item.get('url')}")
                    if self.on_status:
                        self.on_status(f"Download failed after {self.MAX_RETRIES} attempts: {self.parse_error(e)}", "red")
                    raise e

    def build_ydl_opts(self, item: Dict[str, Any]) -> dict:
        """
        Builds and returns the yt-dlp options based on the download item.

        :param item: A dictionary with download parameters.
        :return: A dictionary of options for YoutubeDL.
        """
        opts: dict = {
            'outtmpl': os.path.join(item['path'], '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'ffmpeg_location': item['ffmpeg_path'],
            'progress_hooks': [self.progress_hook],
            'retries': 10,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True
        }

        if item['media_type'] == 'Video':
            if item['quality'] == 'Best':
                opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            else:
                # Remove the trailing 'p' (if present) to obtain the numeric resolution
                res = item['quality'][:-1]
                opts['format'] = f'bestvideo[height<={res}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
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

    def handle_error(self, error: Exception, item: Dict[str, Any]) -> None:
        """
        Handles errors during download by either retrying the item or reporting a permanent failure.

        :param error: The exception encountered.
        :param item: The download item that failed.
        """
        error_msg: str = self.parse_error(error)
        logging.error(f"Download failed for {item.get('url')}: {error_msg}")

        # Increment retry count and requeue if below maximum retries.
        retries: int = item.get('retries', 0)
        if retries < self.MAX_RETRIES:
            item['retries'] = retries + 1
            with self.queue_lock:
                self.download_queue.appendleft(item)
            remaining = self.MAX_RETRIES - item['retries']
            logging.info(f"Requeued {item.get('url')} with {remaining} retries remaining.")
        else:
            if self.on_status:
                self.on_status(f"Permanent failure: {error_msg}", "red")

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

    def validate_ffmpeg(self, path: str) -> bool:
        """
        Validates that FFmpeg is accessible and working.

        :param path: The path to the FFmpeg executable.
        :return: True if FFmpeg returns its version info, False otherwise.
        """
        try:
            result = subprocess.run([path, '-version'],
                                    capture_output=True,
                                    text=True,
                                    check=True)
            return 'ffmpeg version' in result.stdout.lower()
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error(f"FFmpeg validation error: {str(e)}")
            return False

    def validate_url(self, url: str) -> bool:
        """
        Validates that the URL matches common YouTube URL patterns.

        :param url: The URL to validate.
        :return: True if the URL is valid, False otherwise.
        """
        patterns = [
            r'^(https?://)?(www\.)?youtube\.com/watch\?v=',
            r'^(https?://)?(www\.)?youtu\.be/',
            r'^(https?://)?(www\.)?youtube\.com/playlist\?list='
        ]
        is_valid = any(re.match(pattern, url) for pattern in patterns)
        logging.debug(f"URL validation for '{url}': {is_valid}")
        return is_valid

    def cleanup(self) -> None:
        """
        Performs cleanup actions before exiting the application.
        """
        self._save_queue_state()
        self.save_config()
        if self.current_download:
            try:
                self.current_download.cancel_download()
            except Exception as e:
                logging.error(f"Cleanup error: {str(e)}")
