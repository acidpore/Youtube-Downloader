import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from yt_dlp import YoutubeDL
import os
import threading
import re

class YouTubeDownloader:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Video Downloader")
        self.root.geometry("600x400")  # Increased window size
        self.root.resizable(False, False)
        self.setup_ui()
        
        # Download control variables
        self.downloading = False
        self.cancel_requested = False

    def setup_ui(self):
        # Configure style
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure('TButton', font=('Arial', 10), padding=6)
        self.style.configure('TLabel', font=('Arial', 10))
        self.style.configure('TEntry', font=('Arial', 10), padding=6)
        self.style.configure('red.TButton', foreground='red')
        self.style.configure('green.TButton', foreground='green')
        self.style.configure('TCombobox', font=('Arial', 10), padding=5)

        # Main frame
        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # URL Entry
        ttk.Label(main_frame, text="YouTube URL:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.url_entry = ttk.Entry(main_frame, width=50)
        self.url_entry.grid(row=0, column=1, columnspan=2, pady=5, padx=5)

        # Download Path
        ttk.Label(main_frame, text="Download Path:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.path_entry = ttk.Entry(main_frame, width=40)
        self.path_entry.grid(row=1, column=1, pady=5, padx=5, sticky=tk.W)
        ttk.Button(main_frame, text="Browse", command=self.browse_folder).grid(row=1, column=2, pady=5, padx=5)

        # Resolution Selection
        ttk.Label(main_frame, text="Resolution:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.resolution_var = tk.StringVar()
        self.resolution_combobox = ttk.Combobox(main_frame, textvariable=self.resolution_var, width=15)
        self.resolution_combobox.grid(row=2, column=1, pady=5, padx=5, sticky=tk.W)
        self.resolution_combobox['values'] = ('Best', '1080p', '720p', '480p', '360p')
        self.resolution_combobox.current(0)  # Default to 'Best'

        # Progress Bar
        self.progress_bar = ttk.Progressbar(main_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.progress_bar.grid(row=3, column=0, columnspan=3, pady=15, sticky=tk.EW)

        # Status Label
        self.status_label = ttk.Label(main_frame, text="Ready", foreground="gray")
        self.status_label.grid(row=4, column=0, columnspan=3, pady=5)

        # Buttons
        self.download_btn = ttk.Button(main_frame, text="Start Download", 
                                     command=self.toggle_download, style='green.TButton')
        self.download_btn.grid(row=5, column=1, pady=15, padx=5)
        ttk.Button(main_frame, text="Exit", command=self.root.destroy, style='red.TButton').grid(row=5, column=2, pady=15, padx=5)

    def browse_folder(self):
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, folder_selected)

    def toggle_download(self):
        if self.downloading:
            self.cancel_requested = True
            self.download_btn.config(text="Cancelling...", style='red.TButton')
        else:
            self.start_download()

    def start_download(self):
        url = self.url_entry.get()
        download_path = self.path_entry.get()
        resolution = self.resolution_var.get()

        if not url:
            messagebox.showerror("Error", "Please enter a YouTube URL!")
            return

        self.downloading = True
        self.cancel_requested = False
        self.download_btn.config(text="Cancel Download", style='red.TButton')
        self.status_label.config(text="Starting download...", foreground="black")
        self.progress_bar['value'] = 0

        # Run download in separate thread
        threading.Thread(target=self.run_download, args=(url, download_path, resolution), daemon=True).start()

    def run_download(self, url, download_path, resolution):
        try:
            ffmpeg_path = r'C:\Necessary App\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe'
            
            # Set format based on resolution
            if resolution == 'Best':
                format_option = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            else:
                format_option = f'bestvideo[height<={resolution[:-1]}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'

            ydl_opts = {
                'format': format_option,
                'outtmpl': os.path.join(download_path, '%(title)s.%(ext)s') if download_path else '%(title)s.%(ext)s',
                'quiet': True,
                'no_warnings': True,
                'ffmpeg_location': ffmpeg_path,
                'progress_hooks': [self.update_progress],
            }

            with YoutubeDL(ydl_opts) as ydl:
                self.root.after(0, self.status_label.config, 
                              {'text':"Fetching video info...", 'foreground':"blue"})
                info_dict = ydl.extract_info(url, download=False)
                
                if self.cancel_requested:
                    self.reset_ui()
                    return
                
                self.root.after(0, self.status_label.config, 
                              {'text':f"Downloading: {info_dict['title']}", 'foreground':"black"})
                ydl.download([url])

            if not self.cancel_requested:
                self.root.after(0, self.status_label.config, 
                              {'text':"Download complete!", 'foreground':"green"})
                self.root.after(0, self.progress_bar.config, {'value':100})

        except Exception as e:
            self.root.after(0, self.status_label.config, 
                          {'text':f"Error: {str(e)}", 'foreground':"red"})
        finally:
            self.reset_ui()

    def update_progress(self, d):
        if d['status'] == 'downloading':
            try:
                # Clean ANSI escape codes from progress strings
                clean = lambda s: re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', '', str(s)) if s else "0"
                
                # Get and clean progress values
                percent = float(clean(d.get('percent', 0)).strip('%'))
                speed = clean(d.get('_speed_str', 'N/A')).strip()
                eta = clean(d.get('_eta_str', 'N/A')).strip()

                # Update progress bar
                self.root.after(0, self.progress_bar.config, {'value': percent})
                
                # Build status text
                status_parts = [
                    f"{percent:.1f}%",
                    f"Speed: {speed}",
                    f"ETA: {eta}"
                ]
                
                self.root.after(0, self.status_label.config, {
                    'text': " | ".join(status_parts),
                    'foreground': "black"
                })

            except Exception as e:
                print(f"Progress error: {e}")
                self.root.after(0, self.status_label.config, 
                              {'text': "Downloading...", 'foreground': "black"})
                
        elif d['status'] == 'finished':
            self.root.after(0, self.status_label.config, 
                          {'text': "Processing video...", 'foreground': "blue"})
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