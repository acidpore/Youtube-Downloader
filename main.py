# main.py
import tkinter as tk
from gui import YouTubeDownloaderUI
from core import DownloadManager

def main():
    # Initialize root window
    root = tk.Tk()
    root.title("YouTube Downloader")
    root.geometry("800x600")
    root.resizable(False, False)

    # Initialize core components
    dm = DownloadManager()

    # Configuration handler
    def config_handler(action, key=None, value=None):
        if action == 'get':
            return dm.config.get(key, '')
        elif action == 'update':
            dm.config[key] = value
            dm.save_config()
        elif action == 'save':
            dm.save_config()

    # Queue handler
    def queue_handler(action, data=None):
        if action == 'add':
            dm.add_to_queue(data)
            return True
        elif action == 'remove':
            dm.remove_from_queue(data)
        elif action == 'clear':
            dm.clear_queue()
        elif action == 'validate_url':
            return dm.validate_url(data)

    # Download handler
    def download_handler(action):
        if action == 'start':
            dm.start_download()
        elif action == 'cancel':
            dm.cancel_download()

    # Path validator
    def path_validator(dl_path, ffmpeg_path):
        return dm.validate_paths(dl_path, ffmpeg_path)

    # Initialize UI with dependency injection
    app = YouTubeDownloaderUI(
        root,
        config_handler=config_handler,
        queue_handler=queue_handler,
        download_handler=download_handler,
        path_validator=path_validator
    )

    # Set up core callbacks
    dm.on_progress = app.update_progress
    dm.on_status = lambda msg, color: app.status_label.config(text=msg, foreground=color)
    dm.on_complete = app.download_complete

    # Start application
    root.mainloop()

    # Cleanup when window closes
    dm.cleanup()

if __name__ == "__main__":
    main()
