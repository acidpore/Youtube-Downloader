# core.py
import os
import re
import json
import logging
import threading
import time
import subprocess
from collections import deque, OrderedDict
from yt_dlp import YoutubeDL, DownloadError
from typing import Optional, Callable

ANSI_REGEX = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
class DownloadManager:
    CONFIG_FILE = 'yt_downloader_config.json'
    MAX_RETRIES = 3
    RETRY_DELAY = 5
    MEDIA_TYPES = ('Video', 'Audio')
    VIDEO_QUALITIES = ('Best', '1080p', '720p', '480p', '360p')
    AUDIO_QUALITIES = ('128k', '192k', '256k', '320k')
    AUDIO_FORMATS = ('mp3', 'aac', 'wav', 'm4a')

    def __init__(self):
        self.config = self.load_config()
        self.download_queue = deque()
        self.current_item: Optional[dict] = None
        self.queue_lock = threading.Lock()
        self.downloading = False
        self.cancel_requested = False
        self.current_download: Optional[YoutubeDL] = None
        
        # Callbacks
        self.on_progress: Optional[Callable] = None
        self.on_status: Optional[Callable] = None
        self.on_complete: Optional[Callable] = None
        
        self.setup_logging()

    def setup_logging(self):
        logging.basicConfig(
            filename='yt_downloader.log',
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            filemode='a'
        )

    # Configuration Management
    def load_config(self):
        try:
            if os.path.exists(self.CONFIG_FILE):
                with open(self.CONFIG_FILE, 'r') as f:
                    config = json.load(f, object_pairs_hook=OrderedDict)
                    return self.validate_config(config)
        except (json.JSONDecodeError, Exception) as e:
            logging.error(f"Config error: {str(e)}")
            return OrderedDict()

    def validate_config(self, config):
        validated = OrderedDict()
        validated['download_path'] = config.get('download_path', '')
        validated['ffmpeg_path'] = config.get('ffmpeg_path', '')
        validated['media_type'] = self._validate_value(config.get('media_type'), self.MEDIA_TYPES, 'Video')
        validated['video_resolution'] = self._validate_value(config.get('video_resolution'), self.VIDEO_QUALITIES, 'Best')
        validated['audio_quality'] = self._validate_value(config.get('audio_quality'), self.AUDIO_QUALITIES, '128k')
        validated['audio_format'] = self._validate_value(config.get('audio_format'), self.AUDIO_FORMATS, 'mp3')
        return validated

    def _validate_value(self, value, valid_values, default):
        return value if value in valid_values else default

    def save_config(self):
        try:
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            logging.error(f"Config save failed: {str(e)}")

    # Queue Management
    def add_to_queue(self, item: dict):
        with self.queue_lock:
            self.download_queue.append(item)
            logging.info(f"Added to queue: {item['url']}")

    def remove_from_queue(self, index: int):
        with self.queue_lock:
            if 0 <= index < len(self.download_queue):
                del self.download_queue[index]
                logging.info(f"Removed queue item at index {index}")

    def clear_queue(self):
        with self.queue_lock:
            self.download_queue.clear()
            logging.info("Queue cleared")

    # Download Control
    def start_download(self):
        if not self.download_queue:
            return

        self.downloading = True
        self.cancel_requested = False
        threading.Thread(target=self.process_queue, daemon=True).start()
        logging.info("Download process started")

    def cancel_download(self):
        self.cancel_requested = True
        if self.current_download:
            try:
                self.current_download.cancel_download()
                logging.info("Download cancelled")
            except Exception as e:
                logging.error(f"Cancel error: {str(e)}")

    def process_queue(self):
        while not self.cancel_requested:
            with self.queue_lock:
                if not self.download_queue:
                    break
                self.current_item = self.download_queue.popleft()

            try:
                self.run_download(self.current_item)
            except Exception as e:
                logging.error(f"Download failed: {str(e)}")
                self.handle_error(e, self.current_item)

            self.current_item = None

        self.downloading = False
        if self.on_complete:
            self.on_complete(not self.cancel_requested)

    def run_download(self, item: dict):
        for attempt in range(1, self.MAX_RETRIES + 1):
            if self.cancel_requested:
                return

            try:
                ydl_opts = self.build_ydl_opts(item)
                with YoutubeDL(ydl_opts) as ydl:
                    self.current_download = ydl
                    info = ydl.extract_info(item['url'], download=False)
                    
                    if self.on_status:
                        self.on_status(f"Downloading: {info['title']}", "black")
                    
                    ydl.download([item['url']])
                    logging.info(f"Download completed: {item['url']}")
                    return

            except (DownloadError, Exception) as e:
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAY * attempt
                    logging.warning(f"Retrying ({attempt}/{self.MAX_RETRIES}) in {delay}s")
                    time.sleep(delay)
                else:
                    raise e

    def build_ydl_opts(self, item: dict) -> dict:
        opts = {
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

    # Progress and Error Handling
    def progress_hook(self, d: dict):
         if d['status'] == 'downloading':
            percent = d.get('percent', 0)
            speed = ANSI_REGEX.sub('', d.get('_speed_str', 'N/A')).strip()
            eta = ANSI_REGEX.sub('', d.get('_eta_str', 'N/A')).strip()
            
            if self.on_progress:
                self.on_progress(percent, speed, eta)

    def handle_error(self, error: Exception, item: dict):
        error_msg = self.parse_error(error)
        logging.error(f"Download failed: {error_msg}")
        
        if item.get('retries', 0) < self.MAX_RETRIES:
            item['retries'] += 1
            with self.queue_lock:
                self.download_queue.appendleft(item)
                logging.info(f"Requeued item with {self.MAX_RETRIES - item['retries']} retries left")
        else:
            if self.on_status:
                self.on_status(f"Permanent failure: {error_msg}", "red")

    def parse_error(self, error: Exception) -> str:
        error_str = str(error).lower()
        if 'unavailable' in error_str:
            return "Content unavailable"
        if 'age restricted' in error_str:
            return "Age-restricted content"
        if 'requested format' in error_str:
            return "Format not available"
        return f"Unknown error: {str(error)}"

    # Validation Methods
    def validate_paths(self, download_path: str, ffmpeg_path: str) -> bool:
        valid_dl = os.path.exists(download_path) or os.makedirs(download_path, exist_ok=True)
        valid_ffmpeg = self.validate_ffmpeg(ffmpeg_path)
        return valid_dl and valid_ffmpeg

    def validate_ffmpeg(self, path: str) -> bool:
        try:
            result = subprocess.run([path, '-version'], 
                                  capture_output=True, 
                                  text=True, 
                                  check=True)
            return 'ffmpeg version' in result.stdout
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def validate_url(self, url: str) -> bool:
        patterns = [
            r'^(https?://)?(www\.)?youtube\.com/watch\?v=',
            r'^(https?://)?(www\.)?youtu\.be/',
            r'^(https?://)?(www\.)?youtube\.com/playlist\?list='
        ]
        return any(re.match(pattern, url) for pattern in patterns)

    def cleanup(self):
        self.save_config()
        if self.current_download:
            try:
                self.current_download.cancel_download()
            except Exception as e:
                logging.error(f"Cleanup error: {str(e)}")
