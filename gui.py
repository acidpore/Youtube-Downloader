# gui.py
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional, Callable

class YouTubeDownloaderUI:
    def __init__(self, root, config_handler: Callable, queue_handler: Callable, 
                 download_handler: Callable, path_validator: Callable):
        self.root = root
        self.config_handler = config_handler
        self.queue_handler = queue_handler
        self.download_handler = download_handler
        self.path_validator = path_validator
        
        # UI State
        self.downloading = False
        self.cancel_requested = False
        
        # Initialize UI
        self.setup_styles()
        self.create_widgets()
        self.setup_bindings()
        self.update_format_options()

    def setup_styles(self):
        """Initialize custom widget styles"""
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure('TButton', font=('Arial', 10), padding=6)
        self.style.configure('TLabel', font=('Arial', 10))
        self.style.configure('TEntry', font=('Arial', 10), padding=6)
        self.style.configure('red.TButton', foreground='red')
        self.style.configure('green.TButton', foreground='green')
        self.style.configure('TCombobox', font=('Arial', 10), padding=5)

    def create_widgets(self):
        """Create and arrange all UI components"""
        self.main_frame = ttk.Frame(self.root, padding=20)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # Media Type Selection
        ttk.Label(self.main_frame, text="Media Type:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.media_type = tk.StringVar(value=self.config_handler('get', 'media_type'))
        self.type_combobox = ttk.Combobox(self.main_frame, textvariable=self.media_type, 
                                        values=('Video', 'Audio'), width=10)
        self.type_combobox.grid(row=0, column=1, pady=5, padx=5, sticky=tk.W)

        # URL Input
        ttk.Label(self.main_frame, text="YouTube URL(s):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.url_entry = ttk.Entry(self.main_frame, width=50)
        self.url_entry.grid(row=1, column=1, columnspan=2, pady=5, padx=5, sticky=tk.W)
        
        self.add_queue_btn = ttk.Button(self.main_frame, text="Add URLs", 
                                      command=self.process_url_input, width=12)
        self.add_queue_btn.grid(row=1, column=3, pady=5, padx=5)

        # Path Selection
        ttk.Label(self.main_frame, text="Download Path:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.path_entry = ttk.Entry(self.main_frame, width=40)
        self.path_entry.insert(0, self.config_handler('get', 'download_path'))
        self.path_entry.grid(row=2, column=1, pady=5, padx=5, sticky=tk.W)
        ttk.Button(self.main_frame, text="Browse", command=self.browse_folder).grid(row=2, column=2, pady=5, padx=5)

        # FFmpeg Path
        ttk.Label(self.main_frame, text="FFmpeg Path:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.ffmpeg_entry = ttk.Entry(self.main_frame, width=40)
        self.ffmpeg_entry.insert(0, self.config_handler('get', 'ffmpeg_path'))
        self.ffmpeg_entry.grid(row=3, column=1, pady=5, padx=5, sticky=tk.W)
        ttk.Button(self.main_frame, text="Browse", command=self.browse_ffmpeg).grid(row=3, column=2, pady=5, padx=5)

        # Quality Selection
        ttk.Label(self.main_frame, text="Quality:").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.quality_var = tk.StringVar(value=self.get_default_quality())
        self.quality_combobox = ttk.Combobox(self.main_frame, textvariable=self.quality_var, width=15)
        self.quality_combobox.grid(row=4, column=1, pady=5, padx=5, sticky=tk.W)

        # Audio Format
        self.audio_format_label = ttk.Label(self.main_frame, text="Audio Format:")
        self.audio_format_label.grid(row=4, column=2, sticky=tk.W, pady=5)
        self.audio_format = tk.StringVar(value=self.config_handler('get', 'audio_format'))
        self.audio_combobox = ttk.Combobox(self.main_frame, textvariable=self.audio_format, 
                                         values=('mp3', 'aac', 'wav', 'm4a'), width=8)
        self.audio_combobox.grid(row=4, column=3, pady=5, padx=5, sticky=tk.W)

        # Download Queue
        ttk.Label(self.main_frame, text="Download Queue:").grid(row=5, column=0, sticky=tk.W, pady=5)
        self.queue_listbox = tk.Listbox(self.main_frame, width=70, height=6)
        self.queue_listbox.grid(row=6, column=0, columnspan=4, pady=5, sticky=tk.W)
        
        # Queue Controls
        self.queue_controls = ttk.Frame(self.main_frame)
        self.queue_controls.grid(row=7, column=0, columnspan=4, pady=5)
        self.remove_btn = ttk.Button(self.queue_controls, text="Remove Selected", 
                                   command=self.remove_selected)
        self.remove_btn.pack(side=tk.LEFT, padx=2)
        self.clear_btn = ttk.Button(self.queue_controls, text="Clear Queue", 
                                  command=self.clear_queue)
        self.clear_btn.pack(side=tk.LEFT, padx=2)

        # Progress and Status
        self.progress_bar = ttk.Progressbar(self.main_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.progress_bar.grid(row=8, column=0, columnspan=4, pady=15, sticky=tk.EW)
        self.status_label = ttk.Label(self.main_frame, text="Ready", foreground="gray")
        self.status_label.grid(row=9, column=0, columnspan=4, pady=5)

        # Control Buttons
        self.download_btn = ttk.Button(self.main_frame, text="Start Queue", 
                                     command=self.toggle_download, style='green.TButton')
        self.download_btn.grid(row=10, column=1, pady=15, padx=5)
        ttk.Button(self.main_frame, text="Exit", command=self.clean_exit, 
                 style='red.TButton').grid(row=10, column=2, pady=15, padx=5)

    def setup_bindings(self):
        """Set up event bindings"""
        self.type_combobox.bind('<<ComboboxSelected>>', self.update_format_options)
        self.root.protocol("WM_DELETE_WINDOW", self.clean_exit)

    def update_format_options(self, event=None):
        """Update quality options based on media type"""
        media_type = self.media_type.get()
        if media_type == 'Video':
            self.quality_combobox['values'] = ('Best', '1080p', '720p', '480p', '360p')
            self.quality_var.set(self.config_handler('get', 'video_resolution'))
            self.audio_combobox.grid_remove()
            self.audio_format_label.grid_remove()
        else:
            self.quality_combobox['values'] = ('128k', '192k', '256k', '320k')
            self.quality_var.set(self.config_handler('get', 'audio_quality'))
            self.audio_combobox.grid()
            self.audio_format_label.grid()
        self.config_handler('update', 'media_type', media_type)

    def get_default_quality(self):
        """Get appropriate default quality based on media type"""
        return (self.config_handler('get', 'video_resolution') 
                if self.media_type.get() == 'Video' 
                else self.config_handler('get', 'audio_quality'))

    def browse_folder(self):
        """Handle folder selection dialog"""
        folder = filedialog.askdirectory()
        if folder:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, folder)
            self.config_handler('update', 'download_path', folder)

    def browse_ffmpeg(self):
        """Handle FFmpeg executable selection"""
        file_path = filedialog.askopenfilename(
            title="Select FFmpeg Executable",
            filetypes=(("Executable files", "*.exe;*.bin"), ("All files", "*.*"))
        )
        if file_path and self.path_validator(file_path, is_ffmpeg=True):
            self.ffmpeg_entry.delete(0, tk.END)
            self.ffmpeg_entry.insert(0, file_path)
            self.config_handler('update', 'ffmpeg_path', file_path)

    def process_url_input(self):
        """Process multiple URLs from input field"""
        urls = [url.strip() for url in self.url_entry.get().splitlines() if url.strip()]
        valid_urls = [url for url in urls if self.queue_handler('validate_url', url)]
        
        for url in valid_urls:
            item = {
                'url': url,
                'media_type': self.media_type.get(),
                'quality': self.quality_var.get(),
                'audio_format': self.audio_format.get(),
                'path': self.path_entry.get(),
                'ffmpeg_path': self.ffmpeg_entry.get()
            }
            if self.queue_handler('add', item):
                self.queue_listbox.insert(tk.END, f"{url} ({self.media_type.get()})")
        
        self.url_entry.delete(0, tk.END)
        if len(valid_urls) != len(urls):
            messagebox.showwarning("Invalid URLs", "Some URLs were invalid and not added to queue")

    def remove_selected(self):
        """Remove selected item from queue"""
        selection = self.queue_listbox.curselection()
        if selection:
            index = selection[0]
            self.queue_listbox.delete(index)
            self.queue_handler('remove', index)

    def clear_queue(self):
        """Clear entire download queue"""
        self.queue_listbox.delete(0, tk.END)
        self.queue_handler('clear')

    def toggle_download(self):
        """Handle download start/cancel"""
        if self.downloading:
            self.cancel_requested = True
            self.download_btn.config(text="Cancelling...", style='red.TButton')
            self.download_handler('cancel')
        else:
            if self.path_validator(self.path_entry.get(), self.ffmpeg_entry.get()):
                self.start_download()

    def start_download(self):
        """Start download process"""
        self.downloading = True
        self.cancel_requested = False
        self.download_btn.config(text="Cancel Queue", style='red.TButton')
        self.status_label.config(text="Starting queue...", foreground="black")
        self.progress_bar['value'] = 0
        self.download_handler('start')

    def update_progress(self, percent: float, speed: str, eta: str):
        """Update progress display"""
        self.progress_bar['value'] = percent
        status_text = f"{percent:.1f}% | Speed: {speed} | ETA: {eta}"
        self.status_label.config(text=status_text, foreground="black")

    def download_complete(self, success: bool):
        """Handle download completion"""
        self.progress_bar['value'] = 100
        if success:
            self.status_label.config(text="Download complete!", foreground="green")
        else:
            self.status_label.config(text="Download failed!", foreground="red")
        self.reset_ui()

    def reset_ui(self):
        """Reset UI to initial state"""
        self.downloading = False
        self.cancel_requested = False
        self.download_btn.config(text="Start Queue", style='green.TButton')
        self.root.after(3000, lambda: self.status_label.config(text="Ready", foreground="gray"))

    def clean_exit(self):
        """Handle application exit"""
        if self.downloading:
            self.cancel_requested = True
            self.download_handler('cancel')
        self.config_handler('save')
        self.root.destroy()