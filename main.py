import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from yt_dlp import YoutubeDL, DownloadError
import os
import threading
import re
import json
from collections import OrderedDict

class YouTubeDownloader:
    CONFIG_FILE = 'yt_downloader_config.json'
    
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Downloader")
        self.root.geometry("680x450")
        self.root.resizable(False, False)
        self.config = self.load_config()
        self.setup_ui()
        self.downloading = False
        self.cancel_requested = False

    def setup_ui(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure('TButton', font=('Arial', 10), padding=6)
        self.style.configure('TLabel', font=('Arial', 10))
        self.style.configure('TEntry', font=('Arial', 10), padding=6)
        self.style.configure('red.TButton', foreground='red')
        self.style.configure('green.TButton', foreground='green')
        self.style.configure('TCombobox', font=('Arial', 10), padding=5)

        self.main_frame = ttk.Frame(self.root, padding=20)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(self.main_frame, text="Media Type:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.media_type = tk.StringVar(value=self.config.get('media_type', 'Video'))
        self.type_combobox = ttk.Combobox(self.main_frame, textvariable=self.media_type, width=10)
        self.type_combobox['values'] = ('Video', 'Audio')
        self.type_combobox.grid(row=0, column=1, pady=5, padx=5, sticky=tk.W)
        self.type_combobox.bind('<<ComboboxSelected>>', self.update_format_options)

        ttk.Label(self.main_frame, text="YouTube URL:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.url_entry = ttk.Entry(self.main_frame, width=50)
        self.url_entry.grid(row=1, column=1, columnspan=3, pady=5, padx=5)

        ttk.Label(self.main_frame, text="Download Path:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.path_entry = ttk.Entry(self.main_frame, width=40)
        self.path_entry.insert(0, self.config.get('download_path', ''))
        self.path_entry.grid(row=2, column=1, pady=5, padx=5, sticky=tk.W)
        ttk.Button(self.main_frame, text="Browse", command=self.browse_folder).grid(row=2, column=2, pady=5, padx=5)

        ttk.Label(self.main_frame, text="FFmpeg Path:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.ffmpeg_entry = ttk.Entry(self.main_frame, width=40)
        self.ffmpeg_entry.insert(0, self.config.get('ffmpeg_path', ''))
        self.ffmpeg_entry.grid(row=3, column=1, pady=5, padx=5, sticky=tk.W)
        ttk.Button(self.main_frame, text="Browse", command=self.browse_ffmpeg).grid(row=3, column=2, pady=5, padx=5)

        ttk.Label(self.main_frame, text="Quality:").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.quality_var = tk.StringVar(value=self.config.get('video_resolution', 'Best'))
        self.quality_combobox = ttk.Combobox(self.main_frame, textvariable=self.quality_var, width=15)
        self.quality_combobox.grid(row=4, column=1, pady=5, padx=5, sticky=tk.W)

        self.audio_format_label = ttk.Label(self.main_frame, text="Audio Format:")
        self.audio_format_label.grid(row=4, column=2, sticky=tk.W, pady=5)
        self.audio_format = tk.StringVar(value=self.config.get('audio_format', 'mp3'))
        self.audio_combobox = ttk.Combobox(self.main_frame, textvariable=self.audio_format, width=8)
        self.audio_combobox['values'] = ('mp3', 'aac', 'wav', 'm4a')
        self.audio_combobox.grid(row=4, column=3, pady=5, padx=5, sticky=tk.W)

        self.update_format_options()

        self.progress_bar = ttk.Progressbar(self.main_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.progress_bar.grid(row=5, column=0, columnspan=4, pady=15, sticky=tk.EW)

        self.status_label = ttk.Label(self.main_frame, text="Ready", foreground="gray")
        self.status_label.grid(row=6, column=0, columnspan=4, pady=5)

        self.download_btn = ttk.Button(self.main_frame, text="Start Download", 
                                     command=self.toggle_download, style='green.TButton')
        self.download_btn.grid(row=7, column=1, pady=15, padx=5)
        ttk.Button(self.main_frame, text="Exit", command=self.root.destroy, style='red.TButton').grid(row=7, column=2, pady=15, padx=5)

    def update_format_options(self, event=None):
        if self.media_type.get() == 'Video':
            self.quality_combobox['values'] = ('Best', '1080p', '720p', '480p', '360p')
            self.quality_var.set(self.config.get('video_resolution', 'Best'))
            self.audio_combobox.grid_remove()
            self.audio_format_label.grid_remove()
        else:
            self.quality_combobox['values'] = ('128k', '192k', '256k', '320k')
            self.quality_var.set(self.config.get('audio_quality', '128k'))
            self.audio_combobox.grid()
            self.audio_format_label.grid()

    def browse_folder(self):
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, folder_selected)
            self.save_config()

    def browse_ffmpeg(self):
        file_selected = filedialog.askopenfilename(title="Select FFmpeg Executable",
                                                  filetypes=(("Executable files", "*.exe"),))
        if file_selected:
            self.ffmpeg_entry.delete(0, tk.END)
            self.ffmpeg_entry.insert(0, file_selected)
            self.save_config()

    def toggle_download(self):
        if self.downloading:
            self.cancel_requested = True
            self.download_btn.config(text="Cancelling...", style='red.TButton')
        else:
            self.start_download()

    def load_config(self):
        try:
            if os.path.exists(self.CONFIG_FILE):
                with open(self.CONFIG_FILE, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return OrderedDict()

    def save_config(self):
        config = OrderedDict([
            ('download_path', self.path_entry.get().strip()),
            ('ffmpeg_path', self.ffmpeg_entry.get().strip()),
            ('media_type', self.media_type.get()),
            ('video_resolution', self.quality_var.get() if self.media_type.get() == 'Video' else ''),
            ('audio_quality', self.quality_var.get() if self.media_type.get() == 'Audio' else ''),
            ('audio_format', self.audio_format.get())
        ])
        with open(self.CONFIG_FILE, 'w') as f:
            json.dump(config, f)

    def is_valid_youtube_url(self, url):
        pattern = r'^(https?\:\/\/)?(www\.)?(youtube\.com|youtu\.?be)\/.+'
        return re.match(pattern, url) is not None

    def start_download(self):
        url = self.url_entry.get().strip()
        download_path = self.path_entry.get().strip()
        ffmpeg_path = self.ffmpeg_entry.get().strip()

        if not url or not self.is_valid_youtube_url(url):
            messagebox.showerror("Error", "Invalid YouTube URL format")
            return

        if not download_path or not os.path.isdir(download_path):
            messagebox.showerror("Error", "Invalid download directory")
            return

        if not os.access(download_path, os.W_OK):
            messagebox.showerror("Error", "No write permissions for download directory")
            return

        if not ffmpeg_path or not os.path.isfile(ffmpeg_path):
            messagebox.showerror("Error", "Invalid FFmpeg path")
            return

        self.save_config()
        self.downloading = True
        self.cancel_requested = False
        self.download_btn.config(text="Cancel Download", style='red.TButton')
        self.status_label.config(text="Starting download...", foreground="black")
        self.progress_bar['value'] = 0

        threading.Thread(target=self.run_download, args=(url, download_path, ffmpeg_path), daemon=True).start()

    def run_download(self, url, download_path, ffmpeg_path):
        try:
            media_type = self.media_type.get()
            quality = self.quality_var.get()
            audio_format = self.audio_format.get()

            ydl_opts = {
                'outtmpl': os.path.join(download_path, '%(title)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'ffmpeg_location': ffmpeg_path,
                'progress_hooks': [self.update_progress],
            }

            if media_type == 'Video':
                if quality == 'Best':
                    ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
                else:
                    ydl_opts['format'] = f'bestvideo[height<={quality[:-1]}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            else:
                ydl_opts['format'] = 'bestaudio/best'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': audio_format,
                    'preferredquality': quality[:-1]
                }]

            with YoutubeDL(ydl_opts) as ydl:
                self.root.after(0, self.status_label.config, {'text':"Fetching info...", 'foreground':"blue"})
                info_dict = ydl.extract_info(url, download=False)
                
                if self.cancel_requested:
                    self.reset_ui()
                    return
                
                self.root.after(0, self.status_label.config, {'text':f"Downloading: {info_dict['title']}", 'foreground':"black"})
                ydl.download([url])

            if not self.cancel_requested:
                self.root.after(0, self.status_label.config, {'text':"Download complete!", 'foreground':"green"})
                self.root.after(0, self.progress_bar.config, {'value':100})

        except DownloadError as e:
            error_msg = str(e).lower()
            if 'unavailable' in error_msg:
                specific = "Video unavailable (private/deleted)"
            elif 'age restricted' in error_msg:
                specific = "Age-restricted content (login required)"
            elif 'requested format' in error_msg:
                specific = "Selected quality not available"
            else:
                specific = f"Download error: {str(e)}"
            self.root.after(0, self.status_label.config, {'text':specific, 'foreground':"red"})
        except Exception as e:
            self.root.after(0, self.status_label.config, {'text':f"Error: {str(e)}", 'foreground':"red"})
        finally:
            self.reset_ui()

    def update_progress(self, d):
        if d['status'] == 'downloading':
            try:
                clean = lambda s: re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', '', str(s)) if s else "0"
                percent = float(clean(d.get('percent', 0)).strip('%'))
                speed = clean(d.get('_speed_str', 'N/A')).strip()
                eta = clean(d.get('_eta_str', 'N/A')).strip()

                self.root.after(0, self.progress_bar.config, {'value': percent})
                status_parts = [f"{percent:.1f}%", f"Speed: {speed}", f"ETA: {eta}"]
                self.root.after(0, self.status_label.config, {'text': " | ".join(status_parts), 'foreground': "black"})

            except Exception as e:
                self.root.after(0, self.status_label.config, {'text': "Downloading...", 'foreground': "black"})
                
        elif d['status'] == 'finished':
            self.root.after(0, self.status_label.config, {'text': "Processing...", 'foreground': "blue"})
            self.root.after(0, self.progress_bar.config, {'value': 100})

    def reset_ui(self):
        self.downloading = False
        self.cancel_requested = False
        self.download_btn.config(text="Start Download", style='green.TButton')
        self.root.after(3000, lambda: self.status_label.config(text="Ready", foreground="gray"))

if __name__ == "__main__":
    root = tk.Tk()
    app = YouTubeDownloader(root)
    root.mainloop()
