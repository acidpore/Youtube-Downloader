import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional, Callable, Any, Dict, List, Tuple
import logging
import webbrowser

# Configure logging
logging.basicConfig(level=logging.DEBUG)
LOGGER = logging.getLogger(__name__)

# --- Base YouTubeDownloaderUI Class ---
class YouTubeDownloaderUI:
    def __init__(
        self,
        root: tk.Tk,
        config_handler: Callable[[str, Optional[str], Optional[Any]], Any],
        queue_handler: Callable[[str, Any], Any],
        download_handler: Callable[[str], None],
        path_validator: Callable[[str, str], bool]
    ) -> None:
        self.root = root
        self.config_handler = config_handler
        self.queue_handler = queue_handler
        self.download_handler = download_handler
        self.path_validator = path_validator

        # UI State
        self.downloading: bool = False
        self.cancel_requested: bool = False

        # Initialize main frame
        self.main_frame = ttk.Frame(self.root, padding=20)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.setup_styles()
        self.create_widgets()
        self.setup_bindings()
        self.update_format_options()

    def setup_styles(self) -> None:
        """Initialize custom widget styles."""
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure('TButton', font=('Arial', 10), padding=6)
        self.style.configure('TLabel', font=('Arial', 10))
        self.style.configure('TEntry', font=('Arial', 10), padding=6)
        self.style.configure('red.TButton', foreground='red')
        self.style.configure('green.TButton', foreground='green')
        self.style.configure('TCombobox', font=('Arial', 10), padding=5)

    def create_widgets(self) -> None:
        """Create and arrange all UI components."""
        # Media Type Selection
        ttk.Label(self.main_frame, text="Media Type:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.media_type = tk.StringVar(value=self.config_handler('get', 'media_type'))
        self.type_combobox = ttk.Combobox(
            self.main_frame,
            textvariable=self.media_type,
            values=('Video', 'Audio'),
            width=10
        )
        self.type_combobox.grid(row=0, column=1, pady=5, padx=5, sticky=tk.W)

        # URL Input (single-line by default)
        ttk.Label(self.main_frame, text="YouTube URL(s):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.url_entry = ttk.Entry(self.main_frame, width=50)
        self.url_entry.grid(row=1, column=1, columnspan=2, pady=5, padx=5, sticky=tk.W)
        self.add_queue_btn = ttk.Button(
            self.main_frame,
            text="Add URLs",
            command=self.process_url_input,
            width=12
        )
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

        # Audio Format (visible only for audio)
        self.audio_format_label = ttk.Label(self.main_frame, text="Audio Format:")
        self.audio_format_label.grid(row=4, column=2, sticky=tk.W, pady=5)
        self.audio_format = tk.StringVar(value=self.config_handler('get', 'audio_format'))
        self.audio_combobox = ttk.Combobox(
            self.main_frame,
            textvariable=self.audio_format,
            values=('mp3', 'aac', 'wav', 'm4a'),
            width=8
        )
        self.audio_combobox.grid(row=4, column=3, pady=5, padx=5, sticky=tk.W)

        # Download Queue (using Listbox)
        ttk.Label(self.main_frame, text="Download Queue:").grid(row=5, column=0, sticky=tk.W, pady=5)
        self.queue_listbox = tk.Listbox(self.main_frame, width=70, height=6)
        self.queue_listbox.grid(row=6, column=0, columnspan=4, pady=5, sticky=tk.W)

        # Queue Controls
        self.queue_controls = ttk.Frame(self.main_frame)
        self.queue_controls.grid(row=7, column=0, columnspan=4, pady=5)
        self.remove_btn = ttk.Button(
            self.queue_controls,
            text="Remove Selected",
            command=self.remove_selected
        )
        self.remove_btn.pack(side=tk.LEFT, padx=2)
        self.clear_btn = ttk.Button(
            self.queue_controls,
            text="Clear Queue",
            command=self.clear_queue
        )
        self.clear_btn.pack(side=tk.LEFT, padx=2)

        # Progress and Status
        self.progress_bar = ttk.Progressbar(self.main_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.progress_bar.grid(row=8, column=0, columnspan=4, pady=15, sticky=tk.EW)
        self.status_label = ttk.Label(self.main_frame, text="Ready", foreground="gray")
        self.status_label.grid(row=9, column=0, columnspan=4, pady=5)

        # Control Buttons
        self.download_btn = ttk.Button(
            self.main_frame,
            text="Start Queue",
            command=self.toggle_download,
            style='green.TButton'
        )
        self.download_btn.grid(row=10, column=1, pady=15, padx=5)
        ttk.Button(self.main_frame, text="Exit", command=self.clean_exit, style='red.TButton').grid(row=10, column=2, pady=15, padx=5)

    def setup_bindings(self) -> None:
        """Set up event bindings."""
        self.type_combobox.bind('<<ComboboxSelected>>', self.update_format_options)
        self.root.protocol("WM_DELETE_WINDOW", self.clean_exit)
        self.root.bind('<Control-v>', lambda e: self.paste_from_clipboard())
        self.root.bind('<Control-q>', lambda e: self.clean_exit())
        self.root.bind('<Control-d>', lambda e: self.toggle_theme())
        self.root.bind('<Control-s>', lambda e: self.save_settings())
        self.root.bind('<F5>', lambda e: self.refresh_queue())
        self.root.bind('<Delete>', lambda e: self.remove_selected())

    def update_format_options(self, event: Optional[tk.Event] = None) -> None:
        """Update quality options based on the selected media type."""
        media_type = self.media_type.get()
        if media_type == 'Video':
            self.quality_combobox['values'] = ('Best', '1080p', '720p', '480p', '360p')
            self.quality_var.set(self.get_default_quality())
            self.audio_combobox.grid_remove()
            self.audio_format_label.grid_remove()
        else:
            self.quality_combobox['values'] = ('128k', '192k', '256k', '320k')
            self.quality_var.set(self.get_default_quality())
            self.audio_combobox.grid()
            self.audio_format_label.grid()
        self.config_handler('update', 'media_type', media_type)

    def get_default_quality(self) -> str:
        """Get the default quality based on media type."""
        if self.media_type.get() == 'Video':
            return self.config_handler('get', 'video_resolution')
        else:
            return self.config_handler('get', 'audio_quality')

    def browse_folder(self) -> None:
        """Open folder dialog for download path."""
        folder = filedialog.askdirectory()
        if folder:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, folder)
            self.config_handler('update', 'download_path', folder)

    def browse_ffmpeg(self) -> None:
        """Open file dialog for FFmpeg executable with improved error handling."""
        file_path = filedialog.askopenfilename(
            title="Select FFmpeg Executable",
            filetypes=(("Executable files", "*.exe;*.bin"), ("All files", "*.*"))
        )
        if not file_path:
            return
        
        if self.path_validator(self.path_entry.get(), file_path):
            self.ffmpeg_entry.delete(0, tk.END)
            self.ffmpeg_entry.insert(0, file_path)
            self.config_handler('update', 'ffmpeg_path', file_path)
            self.status_label.config(text="FFmpeg configured successfully!", foreground="green")
        else:
            messagebox.showerror(
                "Invalid FFmpeg",
                "The selected file is not a valid FFmpeg executable.\n"
                "Please ensure you have FFmpeg installed correctly."
            )

    def process_url_input(self) -> None:
        """Process URLs with improved validation and user feedback."""
        try:
            urls = [url.strip() for url in self.url_text.get("1.0", tk.END).splitlines() if url.strip()]
            
            if not urls:
                messagebox.showwarning("No URLs", "Please enter at least one URL to download.")
                return
            
            valid_urls = []
            invalid_urls = []
            
            for url in urls:
                if self.queue_handler('validate_url', url):
                    valid_urls.append(url)
                else:
                    invalid_urls.append(url)
            
            # Add valid URLs to queue
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
                    self.queue_tree.insert('', tk.END, values=(url, self.media_type.get(), "Queued"))
            
            # Clear the text input if any URLs were valid
            if valid_urls:
                self.url_text.delete("1.0", tk.END)
                self.status_label.config(
                    text=f"Added {len(valid_urls)} URL(s) to queue", 
                    foreground="green"
                )
            
            # Show warning for invalid URLs
            if invalid_urls:
                invalid_list = "\n".join(invalid_urls)
                messagebox.showwarning(
                    "Invalid URLs",
                    f"The following URLs are invalid:\n\n{invalid_list}\n\n"
                    "Please ensure you're using valid YouTube URLs."
                )
            
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {str(e)}")
            LOGGER.exception("Error processing URL input")

    def remove_selected(self) -> None:
        """Remove the selected URL from the queue."""
        selection = self.queue_listbox.curselection()
        if selection:
            index = selection[0]
            self.queue_listbox.delete(index)
            self.queue_handler('remove', index)

    def clear_queue(self) -> None:
        """Clear the entire download queue."""
        self.queue_listbox.delete(0, tk.END)
        self.queue_handler('clear', None)

    def toggle_download(self) -> None:
        """Toggle between starting and cancelling downloads."""
        if self.downloading:
            self.cancel_requested = True
            self.download_btn.config(text="Cancelling...", style='red.TButton')
            self.download_handler('cancel')
        else:
            if self.path_validator(self.path_entry.get(), self.ffmpeg_entry.get()):
                self.start_download()

    def start_download(self) -> None:
        """Begin the download process."""
        self.downloading = True
        self.cancel_requested = False
        self.download_btn.config(text="Cancel Queue", style='red.TButton')
        self.status_label.config(text="Starting queue...", foreground="black")
        self.progress_bar['value'] = 0
        
        # Update status of first item
        first_item = self.queue_tree.get_children()[0]
        if first_item:
            self.current_item = {
                'url': self.queue_tree.item(first_item)['values'][0]
            }
            self.update_queue_item_status(self.current_item['url'], "Downloading")
        
        self.download_handler('start')

    def update_progress(self, percent: float, speed: str, eta: str) -> None:
        """Update progress bar and status label."""
        self.progress_bar['value'] = percent
        status_text = f"{percent:.1f}% | Speed: {speed} | ETA: {eta}"
        self.status_label.config(text=status_text, foreground="black")

    def download_complete(self, success: bool) -> None:
        """Handle completion of download."""
        if success:
            self.status_label.config(text="Download complete!", foreground="green")
            # Update the status of the current item
            if self.current_item:
                self.update_queue_item_status(self.current_item['url'], "Complete")
        else:
            self.status_label.config(text="Download failed!", foreground="red")
            if self.current_item:
                self.update_queue_item_status(self.current_item['url'], "Failed")
        
        self.reset_ui()

    def reset_ui(self) -> None:
        """Reset UI state after download finishes."""
        self.downloading = False
        self.cancel_requested = False
        self.download_btn.config(text="Start Queue", style='green.TButton')
        self.root.after(3000, lambda: self.status_label.config(text="Ready", foreground="gray"))

    def clean_exit(self) -> None:
        """Cleanly exit the application."""
        if self.downloading:
            self.cancel_requested = True
            self.download_handler('cancel')
        self.config_handler('save', None, None)
        self.root.destroy()


# --- Enhanced UI Subclass ---
class EnhancedYouTubeDownloaderUI(YouTubeDownloaderUI):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_context_menu()
        self._setup_validation()
        self._add_tooltips()
        self._configure_responsive_layout()

    def setup_styles(self) -> None:
        """Enhanced styling with modern theme and custom configurations."""
        super().setup_styles()
        self.style.theme_use('alt')
        self.style.configure('Header.TLabel', font=('Segoe UI', 9, 'bold'), padding=5)
        self.style.configure('Section.TFrame', relief=tk.GROOVE, borderwidth=2, padding=10)
        self.style.map('TButton',
                       foreground=[('active', 'white'), ('disabled', 'gray')],
                       background=[('active', '#45a049'), ('disabled', '#f0f0f0')])

    def create_widgets(self) -> None:
        """Reorganized widget layout with improved visual hierarchy."""
        # Clear any existing widgets in main_frame
        for widget in self.main_frame.winfo_children():
            widget.destroy()

        # Configuration Frame
        config_frame = ttk.LabelFrame(self.main_frame, text=" Download Settings ", style='Section.TFrame')
        config_frame.grid(row=0, column=0, columnspan=4, padx=10, pady=5, sticky=tk.EW)
        self._create_media_controls(config_frame)

        # URL input section with multi-line Text widget
        self._create_url_input_section()

        # Path selection section
        self._create_path_selection()

        # Enhanced Queue Display (Treeview)
        self._create_queue_display()

        # Progress Section with detailed stats
        self._create_progress_section()

        # Control Buttons
        self._create_control_buttons()

    def _create_media_controls(self, parent: ttk.Frame) -> None:
            """Create media type and quality selection controls."""
            # Create media type variable and combobox if not already created.
            if not hasattr(self, 'media_type'):
                self.media_type = tk.StringVar(value=self.config_handler('get', 'media_type'))
            ttk.Label(parent, text="Media Type:", style='Header.TLabel').grid(row=0, column=0)
            self.type_combobox = ttk.Combobox(parent, textvariable=self.media_type, values=('Video', 'Audio'), width=10)
            self.type_combobox.grid(row=0, column=1, padx=5, pady=2, sticky=tk.W)
            
            # Create quality selection controls.
            if not hasattr(self, 'quality_var'):
                # For Video, use video_resolution; for Audio, use audio_quality.
                default_quality = self.config_handler('get', 'video_resolution') if self.media_type.get() == 'Video' else self.config_handler('get', 'audio_quality')
                self.quality_var = tk.StringVar(value=default_quality)
            ttk.Label(parent, text="Quality:", style='Header.TLabel').grid(row=0, column=2)
            self.quality_combobox = ttk.Combobox(parent, textvariable=self.quality_var, width=15)
            self.quality_combobox.grid(row=0, column=3, padx=5, pady=2, sticky=tk.W)
            
            # Create audio format controls.
            self.audio_format_label = ttk.Label(parent, text="Audio Format:", style='Header.TLabel')
            self.audio_format_label.grid(row=0, column=4, padx=5, sticky=tk.W)
            if not hasattr(self, 'audio_format'):
                self.audio_format = tk.StringVar(value=self.config_handler('get', 'audio_format'))
            self.audio_combobox = ttk.Combobox(parent, textvariable=self.audio_format, values=('mp3', 'aac', 'wav', 'm4a'), width=8)
            self.audio_combobox.grid(row=0, column=5, padx=5, pady=2, sticky=tk.W)


    def _create_url_input_section(self) -> None:
        """Create URL input section with multi-line Text widget and add button."""
        url_frame = ttk.LabelFrame(self.main_frame, text=" URL Management ", style='Section.TFrame')
        url_frame.grid(row=1, column=0, columnspan=4, padx=10, pady=5, sticky=tk.EW)
        
        # URL input area
        input_frame = ttk.Frame(url_frame)
        input_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Text widget for URLs
        self.url_text = tk.Text(input_frame, width=60, height=4, font=('Consolas', 9), wrap=tk.WORD)
        self.url_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Scrollbar for text widget
        scrollbar = ttk.Scrollbar(input_frame, command=self.url_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.url_text.config(yscrollcommand=scrollbar.set)
        
        # Button frame
        button_frame = ttk.Frame(url_frame)
        button_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Add URL button
        self.add_url_btn = ttk.Button(
            button_frame,
            text="Add to Queue",
            command=self.process_url_input,
            style='green.TButton'
        )
        self.add_url_btn.pack(side=tk.LEFT, padx=5)
        
        # Clear text button
        self.clear_text_btn = ttk.Button(
            button_frame,
            text="Clear Text",
            command=lambda: self.url_text.delete("1.0", tk.END)
        )
        self.clear_text_btn.pack(side=tk.LEFT, padx=5)
        
        # URL validation indicator
        self.url_validation_label = ttk.Label(button_frame, text="✓", foreground="gray")
        self.url_validation_label.pack(side=tk.RIGHT, padx=5)

    def _create_path_selection(self) -> None:
        """Create path selection section for download and FFmpeg paths."""
        path_frame = ttk.LabelFrame(self.main_frame, text=" Path Settings ", style='Section.TFrame')
        path_frame.grid(row=2, column=0, columnspan=4, padx=10, pady=5, sticky=tk.EW)
        ttk.Label(path_frame, text="Download Path:", style='Header.TLabel').grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.path_entry = ttk.Entry(path_frame, width=40)
        self.path_entry.insert(0, self.config_handler('get', 'download_path'))
        self.path_entry.grid(row=0, column=1, padx=5, pady=2, sticky=tk.W)
        ttk.Button(path_frame, text="Browse", command=self.browse_folder).grid(row=0, column=2, padx=5, pady=2)
        ttk.Label(path_frame, text="FFmpeg Path:", style='Header.TLabel').grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.ffmpeg_entry = ttk.Entry(path_frame, width=40)
        self.ffmpeg_entry.insert(0, self.config_handler('get', 'ffmpeg_path'))
        self.ffmpeg_entry.grid(row=1, column=1, padx=5, pady=2, sticky=tk.W)
        ttk.Button(path_frame, text="Browse", command=self.browse_ffmpeg).grid(row=1, column=2, padx=5, pady=2)

    def _create_queue_display(self) -> None:
        """Create enhanced queue display using Treeview."""
        queue_frame = ttk.LabelFrame(self.main_frame, text=" Download Queue ", style='Section.TFrame')
        queue_frame.grid(row=3, column=0, columnspan=4, padx=10, pady=5, sticky=tk.NSEW)
        
        # Create queue controls
        controls_frame = ttk.Frame(queue_frame)
        controls_frame.pack(fill=tk.X, padx=5, pady=2)
        
        # Add control buttons
        ttk.Button(
            controls_frame, 
            text="Remove Selected",
            command=self.remove_selected
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(
            controls_frame, 
            text="Clear Queue",
            command=self.clear_queue
        ).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(
            controls_frame, 
            text="Clear Completed",
            command=self.clear_completed
        ).pack(side=tk.LEFT, padx=2)
        
        # Create Treeview
        columns = ('url', 'media_type', 'status')
        self.queue_tree = ttk.Treeview(queue_frame, columns=columns, show='headings', height=5)
        
        # Configure columns
        self.queue_tree.heading('url', text="URL", anchor=tk.W)
        self.queue_tree.heading('media_type', text="Type", anchor=tk.W)
        self.queue_tree.heading('status', text="Status", anchor=tk.W)
        
        self.queue_tree.column('url', width=400, stretch=True)
        self.queue_tree.column('media_type', width=80, stretch=False)
        self.queue_tree.column('status', width=100, stretch=False)
        
        # Add scrollbars
        y_scrollbar = ttk.Scrollbar(queue_frame, orient=tk.VERTICAL, command=self.queue_tree.yview)
        x_scrollbar = ttk.Scrollbar(queue_frame, orient=tk.HORIZONTAL, command=self.queue_tree.xview)
        
        self.queue_tree.configure(yscrollcommand=y_scrollbar.set, xscrollcommand=x_scrollbar.set)
        
        # Pack everything
        self.queue_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=5)
        y_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        x_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Bind right-click context menu
        self.queue_tree.bind("<Button-3>", self._show_context_menu)
        
        # Style for different statuses
        self.style.configure("Complete.Treeview", foreground="green")
        self.style.configure("Error.Treeview", foreground="red")
        self.style.configure("Processing.Treeview", foreground="blue")

        # Add tag configurations
        self.queue_tree.tag_configure('complete', foreground='green')
        self.queue_tree.tag_configure('error', foreground='red')
        self.queue_tree.tag_configure('processing', foreground='blue')

    def _create_progress_section(self) -> None:
        """Create progress section with detailed statistics."""
        progress_frame = ttk.LabelFrame(self.main_frame, text=" Download Progress ")
        progress_frame.grid(row=4, column=0, columnspan=4, padx=10, pady=5, sticky=tk.EW)
        
        # Progress bar and percentage
        progress_container = ttk.Frame(progress_frame)
        progress_container.pack(fill=tk.X, expand=True, padx=5, pady=5)
        
        self.progress_bar = ttk.Progressbar(
            progress_container, 
            orient=tk.HORIZONTAL, 
            mode='determinate', 
            length=400
        )
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.progress_percent = ttk.Label(
            progress_container,
            text="0.0%",
            width=6,
            font=('Arial', 9)
        )
        self.progress_percent.pack(side=tk.LEFT, padx=5)
        
        # File size progress
        self.file_size_label = ttk.Label(
            progress_frame,
            text="0MB / 0MB",
            font=('Arial', 9)
        )
        self.file_size_label.pack(pady=2)
        
        # Status label
        self.status_label = ttk.Label(
            progress_frame, 
            text="Ready", 
            foreground="gray",
            font=('Arial', 9)
        )
        self.status_label.pack(pady=2)
        
        # Stats frame for speed and ETA
        self.stats_frame = ttk.Frame(progress_frame)
        self.stats_frame.pack(fill=tk.X, padx=5, pady=2)
        
        # Speed display
        speed_container = ttk.Frame(self.stats_frame)
        speed_container.pack(side=tk.LEFT, padx=10)
        ttk.Label(speed_container, text="Speed:").pack(side=tk.LEFT)
        self.speed_label = ttk.Label(speed_container, text="0.00 MB/s")
        self.speed_label.pack(side=tk.LEFT, padx=5)
        
        # ETA display
        eta_container = ttk.Frame(self.stats_frame)
        eta_container.pack(side=tk.LEFT, padx=10)
        ttk.Label(eta_container, text="ETA:").pack(side=tk.LEFT)
        self.eta_label = ttk.Label(eta_container, text="00:00:00")
        self.eta_label.pack(side=tk.LEFT, padx=5)

    def _create_control_buttons(self) -> None:
        """Create control buttons with improved layout."""
        control_frame = ttk.Frame(self.main_frame)
        control_frame.grid(row=5, column=0, columnspan=4, padx=10, pady=5, sticky=tk.EW)
        self.download_btn = ttk.Button(control_frame, text="Start Queue", command=self.toggle_download, style='green.TButton')
        self.download_btn.pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Exit", command=self.clean_exit, style='red.TButton').pack(side=tk.LEFT, padx=5)

    def _create_context_menu(self) -> None:
        """Create right-click context menu for queue items."""
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Remove", command=self.remove_selected)
        self.context_menu.add_command(label="Open in Browser", command=self._open_in_browser)

    def _show_context_menu(self, event: tk.Event) -> None:
        """Display context menu on right-click."""
        item = self.queue_tree.identify_row(event.y)
        if item:
            self.queue_tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def _open_in_browser(self) -> None:
        """Open selected URL in default browser."""
        selected = self.queue_tree.selection()
        if selected:
            item = self.queue_tree.item(selected[0])
            url = item['values'][0]
            webbrowser.open(url)

    def _setup_validation(self) -> None:
        """Set up real-time URL validation for the multi-line Text widget."""
        self.url_text.bind("<KeyRelease>", self._validate_urls)

    def _validate_urls(self, event: Optional[tk.Event] = None) -> None:
        """Validate URLs in real time with visual feedback."""
        urls = self.url_text.get("1.0", tk.END).splitlines()
        valid_count = sum(1 for url in urls if url.strip() and self.queue_handler('validate_url', url.strip()))
        if valid_count == 0:
            self.url_validation_label.config(text="✗", foreground="red")
        elif valid_count == len(urls):
            self.url_validation_label.config(text="✓", foreground="green")
        else:
            self.url_validation_label.config(text="!", foreground="orange")

    def _add_tooltips(self) -> None:
        """Add tooltips to complex controls using the custom Tooltip class."""
        self.tooltips = []  # Keep references to prevent garbage collection
        
        tooltips = [
            (self.quality_combobox, "Select desired video resolution or audio bitrate"),
            (self.audio_combobox, "Choose output audio format for audio downloads"),
            (self.queue_tree, "Right-click for additional options"),
            (self.download_btn, "Start or cancel the download queue"),
            (self.type_combobox, "Choose between video or audio download"),
            (self.path_entry, "Select where to save downloaded files"),
            (self.ffmpeg_entry, "Path to FFmpeg executable (required for audio conversion)")
        ]
        
        for widget, text in tooltips:
            self.tooltips.append(Tooltip(widget, text))

    def _configure_responsive_layout(self) -> None:
        """Configure grid weights for responsive resizing."""
        # Configure column weights
        self.main_frame.columnconfigure(0, weight=1)
        
        # Configure row weights
        self.main_frame.rowconfigure(3, weight=1)  # Make queue display expandable
        
        # Set minimum window size
        self.root.minsize(800, 600)
        
        # Set initial window size and center it
        window_width = 1024
        window_height = 768
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        center_x = int((screen_width - window_width) / 2)
        center_y = int((screen_height - window_height) / 2)
        
        self.root.geometry(f'{window_width}x{window_height}+{center_x}+{center_y}')
        self.root.resizable(True, True)  # Allow window resizing

    def update_progress(self, percent: float, speed: str, eta: str, size: str) -> None:
        """Update progress bar and status labels."""
        # Update progress bar
        self.progress_bar['value'] = percent
        self.progress_percent.config(text=f"{percent:.1f}%")
        
        # Update file size
        self.file_size_label.config(text=size)
        
        # Update status
        status_text = f"Downloading... | Speed: {speed} | ETA: {eta}"
        self.status_label.config(text=status_text, foreground="black")
        
        # Update progress bar color based on progress
        if percent < 33:
            self.style.configure("Horizontal.TProgressbar", 
                               background="#ff4444", 
                               troughcolor="#f0f0f0")
        elif percent < 66:
            self.style.configure("Horizontal.TProgressbar", 
                               background="#ffd700", 
                               troughcolor="#f0f0f0")
        else:
            self.style.configure("Horizontal.TProgressbar", 
                               background="#4CAF50", 
                               troughcolor="#f0f0f0")

    def process_url_input(self) -> None:
        """Modified URL input processing to use multi-line Text widget."""
        try:
            urls = [url.strip() for url in self.url_text.get("1.0", tk.END).splitlines() if url.strip()]
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
                    # Optionally update a Treeview or other display with the new item.
                    self.queue_tree.insert('', tk.END, values=(url, self.media_type.get(), "Queued"))
            self.url_text.delete("1.0", tk.END)
        except Exception as e:
            LOGGER.exception("Error processing URL input")

    def update_queue_item_status(self, url: str, status: str) -> None:
        """Update the status of a queue item."""
        for item in self.queue_tree.get_children():
            if self.queue_tree.item(item)['values'][0] == url:
                self.queue_tree.set(item, 'status', status)
                # Apply status-specific styling
                if status == "Complete":
                    self.queue_tree.item(item, tags=('complete',))
                elif status == "Failed":
                    self.queue_tree.item(item, tags=('error',))
                elif status == "Downloading":
                    self.queue_tree.item(item, tags=('processing',))
                break

    def clear_completed(self) -> None:
        """Remove all completed items from the queue."""
        items_to_remove = []
        for item in self.queue_tree.get_children():
            if self.queue_tree.item(item)['values'][2] == "Complete":
                items_to_remove.append(item)
        
        for item in items_to_remove:
            self.queue_tree.delete(item)


# Remove the Tix import attempt and add a custom Tooltip class
class Tooltip:
    """
    Create a tooltip for a given widget with hover text.
    """
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.id = None
        self.x = self.y = 0
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.widget.bind("<Motion>", self.motion)

    def enter(self, event=None):
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hide()

    def motion(self, event):
        self.x = event.x
        self.y = event.y

    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(500, self.show)

    def unschedule(self):
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None

    def show(self):
        if self.tooltip_window:
            return

        # Get screen coordinates
        x = self.widget.winfo_rootx() + self.x + 20
        y = self.widget.winfo_rooty() + self.y + 20

        # Creates a toplevel window
        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        
        # Remove window decorations
        self.tooltip_window.wm_attributes("-topmost", True)
        
        # Create tooltip label
        label = ttk.Label(
            self.tooltip_window, 
            text=self.text, 
            background="#ffffe0", 
            relief=tk.SOLID, 
            borderwidth=1,
            padding=(5, 2)
        )
        label.pack()

        # Position the tooltip
        self.tooltip_window.wm_geometry(f"+{x}+{y}")

    def hide(self):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None

