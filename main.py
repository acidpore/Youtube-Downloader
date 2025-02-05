import tkinter as tk
from gui import YouTubeDownloaderUI, EnhancedYouTubeDownloaderUI
from core import DownloadManager

def main():
    # Initialize the main Tkinter window
    root = tk.Tk()
    root.title("YouTube Downloader")
    root.geometry("800x600")
    root.resizable(True, True)  # Allow window resizing

    # Initialize the DownloadManager (core component)
    dm = DownloadManager()

    # -------------------------
    # Handlers for Dependency Injection
    # -------------------------
    def config_handler(action: str, key: str = None, value=None):
        """
        Handles configuration get, update, and save actions.
        """
        if action == 'get':
            return dm.config.get(key, '')
        elif action == 'update':
            dm.config[key] = value
            dm.save_config()
        elif action == 'save':
            dm.save_config()

    def queue_handler(action: str, data=None):
        """
        Handles queue operations: add, remove, clear, and URL validation.
        """
        if action == 'add':
            return dm.add_to_queue(data)
        elif action == 'remove':
            dm.remove_from_queue(data)
        elif action == 'clear':
            dm.clear_queue()
        elif action == 'validate_url':
            return dm.validate_url(data)

    def download_handler(action: str):
        """
        Handles starting and canceling the download process.
        """
        if action == 'start':
            dm.start_download()
        elif action == 'cancel':
            dm.cancel_download()

    def path_validator(dl_path: str, ffmpeg_path: str) -> bool:
        """
        Validates the download and FFmpeg paths using the DownloadManager.
        """
        return dm.validate_paths(dl_path, ffmpeg_path)

    # -------------------------
    # Thread-Safe Callback Wrappers for UI Updates
    # -------------------------
    def safe_update_progress(percent: float, speed: str, eta: str, size: str):
        # Schedule the progress update on the main thread
        root.after(0, app.update_progress, percent, speed, eta, size)
    
    def safe_update_status(msg: str, color: str):
        # Schedule the status update on the main thread
        root.after(0, app.status_label.config, {'text': msg, 'foreground': color})

    def safe_download_complete(success: bool):
        # Schedule the download complete update on the main thread
        root.after(0, app.download_complete, success)

    # Set core callbacks to our safe wrappers
    dm.on_progress = safe_update_progress
    dm.on_status = safe_update_status
    dm.on_complete = safe_download_complete

    # Add state observer
    def on_state_change(downloading: bool, cancelled: bool):
        root.after(0, app.update_download_state, downloading, cancelled)
    dm.state.add_observer(on_state_change)

    # -------------------------
    # Initialize the Enhanced GUI and pass the dependencies
    # -------------------------
    app = EnhancedYouTubeDownloaderUI(
        root,
        config_handler=config_handler,
        queue_handler=queue_handler,
        download_handler=download_handler,
        path_validator=path_validator
    )

    # Start the main event loop
    root.mainloop()

    # When the window closes, perform cleanup
    dm.cleanup()

if __name__ == "__main__":
    main()
