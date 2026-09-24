import sys
import tkinter as tk

from core import DownloadManager
from gui import YouTubeDownloaderUI


def _enable_windows_dpi_awareness() -> None:
    """Render crisp text on high-DPI Windows displays instead of a blurry bitmap."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def main():
    _enable_windows_dpi_awareness()
    root = tk.Tk()
    dm = DownloadManager()

    # -------------------------
    # Handlers passed to the GUI
    # -------------------------
    def config_handler(action: str, key: str = None, value=None):
        if action == 'get':
            return dm.config.get(key, '')
        elif action == 'update':
            dm.update_config(key, value)
        elif action == 'save':
            dm.save_config()

    def queue_handler(action: str, data=None):
        actions = {
            'add': lambda: dm.add_to_queue(data),
            'remove': lambda: dm.remove_from_queue(data),
            'clear': dm.clear_queue,
            'list': dm.get_queue,
            'items': dm.get_items,
            'history': dm.get_history,
            'validate_url': lambda: dm.validate_url(data),
            'pause': lambda: dm.pause_item(data),
            'resume': lambda: dm.resume_item(data),
            'retry': lambda: dm.retry_item(data),
            'cancel_item': lambda: dm.cancel_item(data),
            'update_item': lambda: dm.update_item(data[0], **data[1]),
            'fetch_info': lambda: dm.fetch_info(data),
            'yt_dlp_version': dm.get_yt_dlp_version,
            'update_yt_dlp': dm.update_yt_dlp,
        }
        return actions[action]()

    def download_handler(action: str):
        if action == 'start':
            dm.start_download()
        elif action == 'cancel':
            dm.cancel_download()

    def path_validator(dl_path: str, ffmpeg_path: str) -> bool:
        return dm.validate_paths(dl_path, ffmpeg_path)

    app = YouTubeDownloaderUI(
        root,
        config_handler=config_handler,
        queue_handler=queue_handler,
        download_handler=download_handler,
        path_validator=path_validator
    )

    # -------------------------
    # Core callbacks run on worker threads; hand them to the Tk thread.
    # -------------------------
    dm.on_progress = lambda *args: root.after(0, app.update_progress, *args)
    dm.on_status = lambda msg, color: root.after(0, app.set_status, msg, color)
    dm.on_complete = lambda success: root.after(0, app.download_complete, success)
    dm.on_item_title = lambda item_id, title: root.after(0, app.update_queue_item_title, item_id, title)
    dm.on_item_status = lambda item_id, status: root.after(0, app.update_queue_item_status, item_id, status)
    dm.state.add_observer(lambda downloading, cancelled:
                          root.after(0, app.update_download_state, downloading, cancelled))

    # Load yt-dlp in the background once the window is visible.
    root.after(500, dm.preload)
    root.mainloop()

    # When the window closes, perform cleanup
    dm.cleanup()


if __name__ == "__main__":
    main()
