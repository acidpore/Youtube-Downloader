import logging
import os
import subprocess
import sys
import threading
import tkinter as tk
import urllib.request
import webbrowser
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from typing import Any, Callable, Dict, List, Optional, Tuple

from core import Config

LOGGER = logging.getLogger(__name__)

THEMES: Dict[str, Dict[str, str]] = {
    'light': {
        'bg': '#f4f5f7', 'card': '#ffffff', 'fg': '#1f2328', 'muted': '#6b7280',
        'border': '#d8dbe0', 'accent': '#e5383b', 'accent_hover': '#c9302c',
        'accent_fg': '#ffffff', 'select': '#fde2e2', 'input': '#ffffff',
        'success': '#1a7f37', 'error': '#cf222e', 'warning': '#b35900', 'info': '#0969da',
        'trough': '#e6e8eb',
    },
    'dark': {
        'bg': '#17181b', 'card': '#222429', 'fg': '#e6e7ea', 'muted': '#9aa0a8',
        'border': '#363a41', 'accent': '#ef4444', 'accent_hover': '#dc2626',
        'accent_fg': '#ffffff', 'select': '#4a2326', 'input': '#2b2e34',
        'success': '#4ac26b', 'error': '#ff6b6b', 'warning': '#f0a040', 'info': '#58a6ff',
        'trough': '#33363c',
    },
}

# Colors sent by core.on_status, mapped to theme keys.
STATUS_COLORS = {'green': 'success', 'red': 'error', 'orange': 'warning',
                 'black': 'fg', 'gray': 'muted', 'blue': 'info'}

STATUS_TAGS = {'Complete': 'complete', 'Failed': 'error', 'Cancelled': 'error',
               'Downloading': 'processing', 'Paused': 'paused'}
FINISHED_STATUSES = ('Complete', 'Failed', 'Cancelled')


def format_duration(seconds: Optional[float]) -> str:
    if not seconds:
        return ''
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def format_bytes(size: Optional[float]) -> str:
    if not size:
        return ''
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f"{size:.0f} {unit}" if unit in ('B', 'KB') else f"{size:.1f} {unit}"
        size /= 1024
    return ''

URL_PLACEHOLDER = "Paste one or more YouTube links here, one per line…"


class YouTubeDownloaderUI:
    """Main application window."""

    def __init__(
        self,
        root: tk.Tk,
        config_handler: Callable[..., Any],
        queue_handler: Callable[..., Any],
        download_handler: Callable[[str], None],
        path_validator: Callable[[str, str], bool],
    ) -> None:
        self.root = root
        self.config_handler = config_handler
        self.queue_handler = queue_handler
        self.download_handler = download_handler
        self.path_validator = path_validator

        self.downloading = False
        self.cancel_requested = False
        self.active_ids: set = set()
        self.item_progress: Dict[str, float] = {}
        self.item_speed: Dict[str, float] = {}
        self._last_clipboard = ''
        self._status_reset_job: Optional[str] = None
        self._status_color = 'muted'
        self._placeholder_active = False
        self.tooltips: List[Tooltip] = []

        self.theme_name = self.config_handler('get', 'theme') or 'light'
        self.style = ttk.Style(self.root)
        self.style.theme_use('clam')
        self._setup_fonts()

        self.root.title("YouTube Downloader")
        self.root.minsize(720, 560)
        self._center_window(960, 720)

        self.main_frame = ttk.Frame(self.root, padding=16)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        self.main_frame.columnconfigure(0, weight=1)

        self._build_header()
        self._build_input_card()
        self._build_queue_card()
        self._build_footer()
        self._build_context_menu()
        self._setup_bindings()
        self._add_tooltips()

        self.apply_theme()
        self.update_format_options()
        self._show_placeholder()
        self._load_existing_queue()
        self._refresh_queue_summary()
        self._last_clipboard = self._read_clipboard()
        self.root.after(1000, self._poll_clipboard)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_fonts(self) -> None:
        family = 'Segoe UI' if sys.platform == 'win32' else None
        default = tkfont.nametofont('TkDefaultFont')
        if family:
            default.configure(family=family)
        default.configure(size=10)
        base = default.actual()['family']
        self.fonts = {
            'title': tkfont.Font(family=base, size=16, weight='bold'),
            'subtitle': tkfont.Font(family=base, size=9),
            'section': tkfont.Font(family=base, size=10, weight='bold'),
            'small': tkfont.Font(family=base, size=9),
            'mono': tkfont.Font(family='Consolas' if sys.platform == 'win32' else 'TkFixedFont', size=10),
        }

    def _center_window(self, width: int, height: int) -> None:
        width = min(width, self.root.winfo_screenwidth() - 40)
        height = min(height, self.root.winfo_screenheight() - 80)
        x = max((self.root.winfo_screenwidth() - width) // 2, 0)
        y = max((self.root.winfo_screenheight() - height) // 3, 0)
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def _card(self, row: int, title: str, weight: int = 0) -> ttk.Frame:
        """A bordered section with a bold heading."""
        outer = ttk.Frame(self.main_frame, style='Card.TFrame', padding=12)
        outer.grid(row=row, column=0, sticky=tk.NSEW, pady=(0, 12))
        outer.columnconfigure(0, weight=1)
        self.main_frame.rowconfigure(row, weight=weight)
        ttk.Label(outer, text=title, style='Section.TLabel').grid(row=0, column=0, sticky=tk.W, pady=(0, 8))
        return outer

    def _build_header(self) -> None:
        header = ttk.Frame(self.main_frame)
        header.grid(row=0, column=0, sticky=tk.EW, pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="▶  YouTube Downloader", style='Title.TLabel').grid(row=0, column=0, sticky=tk.W)
        ttk.Label(header, text="Download videos and audio with yt-dlp",
                  style='Subtitle.TLabel').grid(row=1, column=0, sticky=tk.W)
        self.theme_btn = ttk.Button(header, width=3, command=self.toggle_theme, style='Icon.TButton')
        self.theme_btn.grid(row=0, column=1, rowspan=2, padx=(8, 0))
        self.settings_btn = ttk.Button(header, text="⚙", width=3, command=self.show_settings, style='Icon.TButton')
        self.settings_btn.grid(row=0, column=2, rowspan=2, padx=(8, 0))

    def _build_input_card(self) -> None:
        card = self._card(1, "Add links")

        text_frame = ttk.Frame(card, style='Card.TFrame')
        text_frame.grid(row=1, column=0, sticky=tk.EW)
        text_frame.columnconfigure(0, weight=1)
        self.url_text = tk.Text(text_frame, height=3, wrap=tk.NONE, relief=tk.FLAT,
                                borderwidth=0, highlightthickness=1, font=self.fonts['mono'],
                                padx=8, pady=6, undo=True)
        self.url_text.grid(row=0, column=0, sticky=tk.EW)

        buttons = ttk.Frame(text_frame, style='Card.TFrame')
        buttons.grid(row=0, column=1, sticky=tk.NS, padx=(8, 0))
        self.paste_btn = ttk.Button(buttons, text="Paste", command=self.paste_from_clipboard)
        self.paste_btn.pack(fill=tk.X)
        self.add_url_btn = ttk.Button(buttons, text="Add to queue", style='Accent.TButton',
                                      command=self.process_url_input)
        self.add_url_btn.pack(fill=tk.X, pady=(6, 0))

        self.url_validation_label = ttk.Label(card, text="", style='CardMuted.TLabel')
        self.url_validation_label.grid(row=2, column=0, sticky=tk.W, pady=(4, 8))

        # Download options
        options = ttk.Frame(card, style='Card.TFrame')
        options.grid(row=3, column=0, sticky=tk.EW)
        options.columnconfigure(7, weight=1)

        self.media_type = tk.StringVar(value=self.config_handler('get', 'media_type') or 'Video')
        ttk.Label(options, text="Type", style='Card.TLabel').grid(row=0, column=0, sticky=tk.W, padx=(0, 6))
        type_frame = ttk.Frame(options, style='Card.TFrame')
        type_frame.grid(row=0, column=1, sticky=tk.W, padx=(0, 16))
        for value in Config.MEDIA_TYPES:
            ttk.Radiobutton(type_frame, text=value, value=value, variable=self.media_type,
                            command=self.update_format_options, style='Toggle.TRadiobutton'
                            ).pack(side=tk.LEFT)

        ttk.Label(options, text="Quality", style='Card.TLabel').grid(row=0, column=2, sticky=tk.W, padx=(0, 6))
        self.quality_var = tk.StringVar()
        self.quality_combobox = ttk.Combobox(options, textvariable=self.quality_var, width=8, state='readonly')
        self.quality_combobox.grid(row=0, column=3, sticky=tk.W, padx=(0, 16))
        self.quality_combobox.bind('<<ComboboxSelected>>', self._on_quality_selected)

        self.audio_format_label = ttk.Label(options, text="Format", style='Card.TLabel')
        self.audio_format_label.grid(row=0, column=4, sticky=tk.W, padx=(0, 6))
        self.audio_format = tk.StringVar(value=self.config_handler('get', 'audio_format') or 'mp3')
        self.audio_combobox = ttk.Combobox(options, textvariable=self.audio_format, width=6,
                                           values=Config.AUDIO_FORMATS, state='readonly')
        self.audio_combobox.grid(row=0, column=5, sticky=tk.W, padx=(0, 16))
        self.audio_combobox.bind('<<ComboboxSelected>>',
                                 lambda e: self.config_handler('update', 'audio_format', self.audio_format.get()))

        ttk.Label(options, text="Save to", style='Card.TLabel').grid(row=0, column=6, sticky=tk.W, padx=(0, 6))
        self.path_entry = ttk.Entry(options)
        self.path_entry.insert(0, self.config_handler('get', 'download_path'))
        self.path_entry.grid(row=0, column=7, sticky=tk.EW)
        self.path_entry.bind('<FocusOut>', lambda e: self._save_download_path())
        ttk.Button(options, text="Browse…", command=self.browse_folder).grid(row=0, column=8, padx=(6, 0))

        # FFmpeg path is edited in the settings dialog; kept as an Entry so
        # the rest of the code can read it the same way as the download path.
        self.ffmpeg_entry = ttk.Entry(self.root)
        self.ffmpeg_entry.insert(0, self.config_handler('get', 'ffmpeg_path'))

    def _build_queue_card(self) -> None:
        card = self._card(2, "Queue", weight=1)
        card.rowconfigure(1, weight=1)

        self.queue_summary = ttk.Label(card, text="", style='CardMuted.TLabel')
        self.queue_summary.grid(row=0, column=0, sticky=tk.E)

        tree_frame = ttk.Frame(card, style='Card.TFrame')
        tree_frame.grid(row=1, column=0, sticky=tk.NSEW)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        columns = ('title', 'url', 'media_type', 'quality', 'status')
        self.queue_tree = ttk.Treeview(tree_frame, columns=columns, show='headings',
                                       displaycolumns=('title', 'media_type', 'quality', 'status'),
                                       selectmode='extended', height=6)
        for col, text, width, stretch in (('title', "Title", 380, True), ('url', "URL", 0, False),
                                          ('media_type', "Type", 70, False),
                                          ('quality', "Quality", 90, False),
                                          ('status', "Status", 160, False)):
            self.queue_tree.heading(col, text=text, anchor=tk.W)
            self.queue_tree.column(col, width=width, minwidth=50, stretch=stretch, anchor=tk.W)
        self.queue_tree.grid(row=0, column=0, sticky=tk.NSEW)
        y_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.queue_tree.yview)
        y_scroll.grid(row=0, column=1, sticky=tk.NS)
        self.queue_tree.configure(yscrollcommand=y_scroll.set)

        toolbar = ttk.Frame(card, style='Card.TFrame')
        toolbar.grid(row=2, column=0, sticky=tk.EW, pady=(8, 0))
        self.preview_btn = ttk.Button(toolbar, text="Preview…", command=self.show_preview)
        self.preview_btn.pack(side=tk.LEFT)
        self.pause_btn = ttk.Button(toolbar, text="Pause", command=self.pause_selected)
        self.pause_btn.pack(side=tk.LEFT, padx=(6, 0))
        self.resume_btn = ttk.Button(toolbar, text="Resume / Retry", command=self.resume_selected)
        self.resume_btn.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(toolbar, text="Clear all", command=self.clear_queue).pack(side=tk.RIGHT)
        ttk.Button(toolbar, text="Clear finished", command=self.clear_completed).pack(side=tk.RIGHT, padx=6)
        ttk.Button(toolbar, text="Remove", command=self.remove_selected).pack(side=tk.RIGHT)

    def _build_footer(self) -> None:
        footer = ttk.Frame(self.main_frame, style='Card.TFrame', padding=12)
        footer.grid(row=3, column=0, sticky=tk.EW)
        footer.columnconfigure(0, weight=1)

        self.progress_bar = ttk.Progressbar(footer, orient=tk.HORIZONTAL, mode='determinate',
                                            style='Accent.Horizontal.TProgressbar')
        self.progress_bar.grid(row=0, column=0, columnspan=2, sticky=tk.EW)

        info = ttk.Frame(footer, style='Card.TFrame')
        info.grid(row=1, column=0, sticky=tk.EW, pady=(8, 0))
        self.status_label = ttk.Label(info, text="Ready", style='Card.TLabel')
        self.status_label.pack(anchor=tk.W)
        self.stats_label = ttk.Label(info, text="", style='CardMuted.TLabel')
        self.stats_label.pack(anchor=tk.W)

        actions = ttk.Frame(footer, style='Card.TFrame')
        actions.grid(row=1, column=1, sticky=tk.E, pady=(8, 0))
        ttk.Button(actions, text="History", command=self.show_history).pack(side=tk.LEFT)
        ttk.Button(actions, text="Open folder", command=self.open_download_folder).pack(side=tk.LEFT, padx=6)
        self.download_btn = ttk.Button(actions, text="Start downloads", width=16,
                                       style='Accent.TButton', command=self.toggle_download)
        self.download_btn.pack(side=tk.LEFT)

    def _build_context_menu(self) -> None:
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Preview / choose videos…", command=self.show_preview)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Pause", command=self.pause_selected)
        self.context_menu.add_command(label="Resume / Retry", command=self.resume_selected)
        self.context_menu.add_command(label="Cancel", command=self.cancel_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Open in browser", command=self._open_in_browser)
        self.context_menu.add_command(label="Copy link", command=self._copy_link)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Remove", command=self.remove_selected)

    def _setup_bindings(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self.clean_exit)
        self.root.bind('<Control-q>', lambda e: self.clean_exit())
        self.url_text.bind('<Control-Return>', lambda e: (self.process_url_input(), 'break')[1])
        self.url_text.bind('<KeyRelease>', self._validate_urls)
        self.url_text.bind('<FocusIn>', lambda e: self._hide_placeholder())
        self.url_text.bind('<FocusOut>', lambda e: self._show_placeholder())
        self.url_text.bind('<<Paste>>', lambda e: (self._hide_placeholder(),
                                                   self.root.after(1, self._validate_urls)))
        self.queue_tree.bind('<Delete>', lambda e: self.remove_selected())
        self.queue_tree.bind('<Button-3>', self._show_context_menu)
        self.queue_tree.bind('<Button-2>', self._show_context_menu)  # macOS
        self.queue_tree.bind('<Double-1>', lambda e: self._open_in_browser())

    def _add_tooltips(self) -> None:
        for widget, text in (
            (self.add_url_btn, "Add the links above to the queue (Ctrl+Enter)"),
            (self.paste_btn, "Paste links from the clipboard"),
            (self.quality_combobox, "Maximum video resolution or audio bitrate"),
            (self.audio_combobox, "Output audio format"),
            (self.theme_btn, "Switch light / dark theme"),
            (self.settings_btn, "Settings (FFmpeg)"),
            (self.queue_tree, "Double-click to open in browser, right-click for more"),
            (self.preview_btn, "Show details; pick which videos of a playlist to download"),
            (self.pause_btn, "Pause the selected items (the partial download is kept)"),
            (self.resume_btn, "Resume paused items or retry failed ones"),
        ):
            self.tooltips.append(Tooltip(widget, text))

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    @property
    def colors(self) -> Dict[str, str]:
        return THEMES.get(self.theme_name, THEMES['light'])

    def apply_theme(self) -> None:
        c = self.colors
        s = self.style
        self.root.configure(background=c['bg'])
        s.configure('.', background=c['bg'], foreground=c['fg'], bordercolor=c['border'],
                    lightcolor=c['bg'], darkcolor=c['bg'], troughcolor=c['trough'],
                    fieldbackground=c['input'], insertcolor=c['fg'],
                    selectbackground=c['select'], selectforeground=c['fg'])
        s.configure('TFrame', background=c['bg'])
        s.configure('Card.TFrame', background=c['card'], relief=tk.SOLID, borderwidth=0)
        s.configure('TLabel', background=c['bg'], foreground=c['fg'])
        s.configure('Card.TLabel', background=c['card'], foreground=c['fg'])
        s.configure('CardMuted.TLabel', background=c['card'], foreground=c['muted'], font=self.fonts['small'])
        s.configure('Title.TLabel', background=c['bg'], foreground=c['fg'], font=self.fonts['title'])
        s.configure('Subtitle.TLabel', background=c['bg'], foreground=c['muted'], font=self.fonts['subtitle'])
        s.configure('Section.TLabel', background=c['card'], foreground=c['fg'], font=self.fonts['section'])

        s.configure('TButton', background=c['card'], foreground=c['fg'], bordercolor=c['border'],
                    lightcolor=c['card'], darkcolor=c['card'], focusthickness=0, padding=(12, 5))
        s.map('TButton', background=[('pressed', c['trough']), ('active', c['trough'])],
              bordercolor=[('focus', c['accent'])])
        s.configure('Icon.TButton', padding=(4, 4))
        s.configure('Accent.TButton', background=c['accent'], foreground=c['accent_fg'],
                    bordercolor=c['accent'], lightcolor=c['accent'], darkcolor=c['accent'])
        s.map('Accent.TButton',
              background=[('disabled', c['trough']), ('pressed', c['accent_hover']), ('active', c['accent_hover'])],
              foreground=[('disabled', c['muted'])],
              bordercolor=[('active', c['accent_hover'])])

        s.configure('TEntry', fieldbackground=c['input'], foreground=c['fg'], bordercolor=c['border'],
                    lightcolor=c['border'], darkcolor=c['border'], padding=5)
        s.map('TEntry', bordercolor=[('focus', c['accent'])], lightcolor=[('focus', c['accent'])])
        s.configure('TCombobox', fieldbackground=c['input'], background=c['card'], foreground=c['fg'],
                    arrowcolor=c['fg'], bordercolor=c['border'], lightcolor=c['border'],
                    darkcolor=c['border'], padding=4)
        s.map('TCombobox', fieldbackground=[('readonly', c['input'])],
              background=[('active', c['trough']), ('readonly', c['card'])],
              foreground=[('readonly', c['fg'])], selectbackground=[('readonly', c['input'])],
              selectforeground=[('readonly', c['fg'])], bordercolor=[('focus', c['accent'])])
        self.root.option_add('*TCombobox*Listbox.background', c['input'])
        self.root.option_add('*TCombobox*Listbox.foreground', c['fg'])
        self.root.option_add('*TCombobox*Listbox.selectBackground', c['accent'])
        self.root.option_add('*TCombobox*Listbox.selectForeground', c['accent_fg'])

        s.configure('Card.TCheckbutton', background=c['card'], foreground=c['fg'],
                    indicatorcolor=c['input'], padding=(0, 3))
        s.map('Card.TCheckbutton', background=[('active', c['card'])],
              indicatorcolor=[('selected', c['accent'])])
        s.configure('Toggle.TRadiobutton', background=c['card'], foreground=c['fg'],
                    indicatorcolor=c['input'], padding=(4, 2))
        s.map('Toggle.TRadiobutton', background=[('active', c['card'])],
              indicatorcolor=[('selected', c['accent'])])

        s.configure('Treeview', background=c['input'], fieldbackground=c['input'], foreground=c['fg'],
                    bordercolor=c['border'], lightcolor=c['border'], darkcolor=c['border'], rowheight=26)
        s.map('Treeview', background=[('selected', c['select'])], foreground=[('selected', c['fg'])])
        s.configure('Treeview.Heading', background=c['card'], foreground=c['muted'],
                    bordercolor=c['border'], lightcolor=c['card'], darkcolor=c['card'],
                    relief=tk.FLAT, font=self.fonts['small'])
        s.map('Treeview.Heading', background=[('active', c['trough'])])
        for name in ('TScrollbar', 'Vertical.TScrollbar'):
            s.configure(name, background=c['trough'], troughcolor=c['input'], bordercolor=c['input'],
                        arrowcolor=c['muted'], lightcolor=c['trough'], darkcolor=c['trough'], gripcount=0)
            s.map(name, background=[('active', c['border'])])
        s.configure('Accent.Horizontal.TProgressbar', background=c['accent'], troughcolor=c['trough'],
                    bordercolor=c['trough'], lightcolor=c['accent'], darkcolor=c['accent'], thickness=8)

        self.queue_tree.tag_configure('complete', foreground=c['success'])
        self.queue_tree.tag_configure('error', foreground=c['error'])
        self.queue_tree.tag_configure('processing', foreground=c['info'])
        self.queue_tree.tag_configure('paused', foreground=c['warning'])

        self.url_text.configure(background=c['input'], foreground=c['fg'], insertbackground=c['fg'],
                                highlightbackground=c['border'], highlightcolor=c['accent'],
                                selectbackground=c['select'], selectforeground=c['fg'])
        self.context_menu.configure(background=c['card'], foreground=c['fg'],
                                    activebackground=c['select'], activeforeground=c['fg'])
        self.theme_btn.configure(text="☀" if self.theme_name == 'dark' else "☾")
        self.status_label.configure(foreground=c[self._status_color])
        if self._placeholder_active:
            self.url_text.configure(foreground=c['muted'])

    def toggle_theme(self) -> None:
        self.theme_name = 'light' if self.theme_name == 'dark' else 'dark'
        self.config_handler('update', 'theme', self.theme_name)
        self.apply_theme()

    # ------------------------------------------------------------------
    # URL input
    # ------------------------------------------------------------------

    def _show_placeholder(self) -> None:
        if not self.url_text.get('1.0', 'end-1c').strip() and self.root.focus_get() is not self.url_text:
            self.url_text.delete('1.0', tk.END)
            self.url_text.insert('1.0', URL_PLACEHOLDER)
            self.url_text.configure(foreground=self.colors['muted'])
            self._placeholder_active = True

    def _hide_placeholder(self) -> None:
        if self._placeholder_active:
            self.url_text.delete('1.0', tk.END)
            self.url_text.configure(foreground=self.colors['fg'])
            self._placeholder_active = False

    def _get_url_lines(self) -> List[str]:
        if self._placeholder_active:
            return []
        return [line.strip() for line in self.url_text.get('1.0', tk.END).splitlines() if line.strip()]

    def paste_from_clipboard(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            return
        self._hide_placeholder()
        current = self.url_text.get('1.0', 'end-1c')
        if current and not current.endswith('\n'):
            self.url_text.insert(tk.END, '\n')
        self.url_text.insert(tk.END, text.strip() + '\n')
        self._validate_urls()

    def _validate_urls(self, event: Optional[tk.Event] = None) -> None:
        urls = self._get_url_lines()
        if not urls:
            self.url_validation_label.config(text="", foreground=self.colors['muted'])
            return
        valid = sum(1 for url in urls if self.queue_handler('validate_url', url))
        invalid = len(urls) - valid
        if invalid == 0:
            text, color = f"✓ {valid} link{'s' if valid != 1 else ''} ready", 'success'
        elif valid == 0:
            text, color = "✗ No valid YouTube links", 'error'
        else:
            text, color = f"! {valid} valid, {invalid} not recognised", 'warning'
        self.url_validation_label.config(text=text, foreground=self.colors[color])

    def process_url_input(self) -> None:
        """Queue every valid link; invalid lines stay in the box for fixing."""
        urls = self._get_url_lines()
        if not urls:
            self.set_status("Paste a YouTube link first", 'orange')
            return
        valid = [url for url in urls if self.queue_handler('validate_url', url)]
        invalid = [url for url in urls if url not in valid]
        media_type = self.media_type.get()
        for url in valid:
            item = {
                'url': url,
                'media_type': media_type,
                'quality': self.quality_var.get(),
                'audio_format': self.audio_format.get(),
                'path': self.path_entry.get(),
                'ffmpeg_path': self.ffmpeg_entry.get(),
            }
            if self.queue_handler('add', item):
                self._insert_queue_row(item)

        self.url_text.delete('1.0', tk.END)
        if invalid:
            self.url_text.insert('1.0', '\n'.join(invalid))
            self.set_status(f"Added {len(valid)}; {len(invalid)} link(s) not recognised", 'orange')
        elif valid:
            self.set_status(f"Added {len(valid)} item(s) to the queue", 'green')
        self._validate_urls()
        self._refresh_queue_summary()

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------

    def update_format_options(self, event: Optional[tk.Event] = None) -> None:
        media_type = self.media_type.get()
        if media_type == 'Video':
            self.quality_combobox['values'] = Config.VIDEO_QUALITIES
            self.quality_var.set(self.config_handler('get', 'video_resolution') or 'Best')
            self.audio_format_label.grid_remove()
            self.audio_combobox.grid_remove()
        else:
            self.quality_combobox['values'] = Config.AUDIO_QUALITIES
            self.quality_var.set(self.config_handler('get', 'audio_quality') or '192k')
            self.audio_format_label.grid()
            self.audio_combobox.grid()
        self.config_handler('update', 'media_type', media_type)

    def _on_quality_selected(self, event: Optional[tk.Event] = None) -> None:
        key = 'video_resolution' if self.media_type.get() == 'Video' else 'audio_quality'
        self.config_handler('update', key, self.quality_var.get())

    def _save_download_path(self) -> None:
        path = self.path_entry.get().strip()
        if path and path != self.config_handler('get', 'download_path'):
            self.config_handler('update', 'download_path', path)

    def browse_folder(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.path_entry.get() or None)
        if folder:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, folder)
            self.config_handler('update', 'download_path', folder)

    def _dialog(self, title: str) -> Tuple[tk.Toplevel, ttk.Frame]:
        """A themed modal-less child window with a card frame."""
        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(background=self.colors['bg'])
        win.transient(self.root)
        frame = ttk.Frame(win, style='Card.TFrame', padding=16)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        win.bind('<Escape>', lambda e: win.destroy())
        return win, frame

    def show_settings(self) -> None:
        """Settings: FFmpeg, parallel downloads, speed limit, extras, cookies, yt-dlp."""
        c = self.colors
        get = lambda key: self.config_handler('get', key)
        win, frame = self._dialog("Settings")
        win.resizable(False, False)
        frame.columnconfigure(1, weight=1)
        row = 0

        def section(text: str) -> None:
            nonlocal row
            ttk.Label(frame, text=text, style='Section.TLabel').grid(
                row=row, column=0, columnspan=3, sticky=tk.W, pady=(12 if row else 0, 4))
            row += 1

        def label(text: str) -> None:
            ttk.Label(frame, text=text, style='Card.TLabel').grid(row=row, column=0, sticky=tk.W, padx=(0, 12), pady=3)

        # --- FFmpeg
        section("FFmpeg")
        label("Location")
        ffmpeg_entry = ttk.Entry(frame, width=44)
        ffmpeg_entry.insert(0, self.ffmpeg_entry.get())
        ffmpeg_entry.grid(row=row, column=1, sticky=tk.EW)

        def browse_ffmpeg() -> None:
            path = filedialog.askopenfilename(parent=win, title="Select FFmpeg executable")
            if path:
                ffmpeg_entry.delete(0, tk.END)
                ffmpeg_entry.insert(0, path)
        ttk.Button(frame, text="Browse…", command=browse_ffmpeg).grid(row=row, column=2, padx=(6, 0))
        row += 1

        # --- Downloads
        section("Downloads")
        label("Parallel downloads")
        concurrent_var = tk.StringVar(value=str(get('max_concurrent') or 2))
        ttk.Combobox(frame, textvariable=concurrent_var, values=('1', '2', '3'), width=4,
                     state='readonly').grid(row=row, column=1, sticky=tk.W)
        row += 1
        label("Speed limit (KB/s)")
        limit_var = tk.StringVar(value=str(get('rate_limit_kb') or 0))
        limit_frame = ttk.Frame(frame, style='Card.TFrame')
        limit_frame.grid(row=row, column=1, columnspan=2, sticky=tk.W)
        ttk.Entry(limit_frame, textvariable=limit_var, width=10).pack(side=tk.LEFT)
        ttk.Label(limit_frame, text="0 = unlimited, shared by all downloads",
                  style='CardMuted.TLabel').pack(side=tk.LEFT, padx=8)
        row += 1

        # --- Extras
        section("Add to files")
        subs_var = tk.BooleanVar(value=bool(get('embed_subtitles')))
        thumb_var = tk.BooleanVar(value=bool(get('embed_thumbnail')))
        meta_var = tk.BooleanVar(value=bool(get('add_metadata')))
        ttk.Checkbutton(frame, text="Subtitles (video)", variable=subs_var,
                        style='Card.TCheckbutton').grid(row=row, column=0, sticky=tk.W)
        langs_frame = ttk.Frame(frame, style='Card.TFrame')
        langs_frame.grid(row=row, column=1, columnspan=2, sticky=tk.W)
        ttk.Label(langs_frame, text="Languages", style='Card.TLabel').pack(side=tk.LEFT)
        langs_entry = ttk.Entry(langs_frame, width=14)
        langs_entry.insert(0, get('subtitle_langs') or 'en,id')
        langs_entry.pack(side=tk.LEFT, padx=6)
        ttk.Label(langs_frame, text="e.g. en,id", style='CardMuted.TLabel').pack(side=tk.LEFT)
        row += 1
        ttk.Checkbutton(frame, text="Thumbnail as cover art", variable=thumb_var,
                        style='Card.TCheckbutton').grid(row=row, column=0, columnspan=3, sticky=tk.W)
        row += 1
        ttk.Checkbutton(frame, text="Metadata (title, artist, date…)", variable=meta_var,
                        style='Card.TCheckbutton').grid(row=row, column=0, columnspan=3, sticky=tk.W)
        row += 1

        # --- Access
        section("Age-restricted / members-only videos")
        label("Cookies from browser")
        browser_var = tk.StringVar(value=get('cookies_browser') or 'none')
        ttk.Combobox(frame, textvariable=browser_var, width=12, state='readonly',
                     values=['none'] + [b for b in Config.COOKIE_BROWSERS if b]
                     ).grid(row=row, column=1, sticky=tk.W)
        row += 1
        ttk.Label(frame, text="Uses your browser login. Close the browser first if reading cookies fails.",
                  style='CardMuted.TLabel').grid(row=row, column=0, columnspan=3, sticky=tk.W)
        row += 1

        # --- Behaviour
        section("Behaviour")
        clip_var = tk.BooleanVar(value=bool(get('watch_clipboard')))
        ttk.Checkbutton(frame, text="Detect YouTube links copied to the clipboard", variable=clip_var,
                        style='Card.TCheckbutton').grid(row=row, column=0, columnspan=3, sticky=tk.W)
        row += 1

        # --- yt-dlp
        section("yt-dlp")
        version_label = ttk.Label(frame, text=f"Installed version: {self.queue_handler('yt_dlp_version')}",
                                  style='Card.TLabel')
        version_label.grid(row=row, column=0, columnspan=2, sticky=tk.W)
        update_btn = ttk.Button(frame, text="Update yt-dlp")
        update_btn.grid(row=row, column=2, sticky=tk.E)
        row += 1
        update_result = ttk.Label(frame, text="If downloads start failing, update yt-dlp first.",
                                  style='CardMuted.TLabel', wraplength=460)
        update_result.grid(row=row, column=0, columnspan=3, sticky=tk.W)
        row += 1

        def run_update() -> None:
            update_btn.config(state=tk.DISABLED, text="Updating…")
            update_result.config(text="Downloading the latest yt-dlp…", foreground=c['muted'])

            def work() -> None:
                ok, message = self.queue_handler('update_yt_dlp')
                self.root.after(0, done, ok, message)

            def done(ok: bool, message: str) -> None:
                if not update_btn.winfo_exists():
                    return
                update_btn.config(state=tk.NORMAL, text="Update yt-dlp")
                update_result.config(text=message, foreground=c['success' if ok else 'error'])
            threading.Thread(target=work, daemon=True).start()
        update_btn.config(command=run_update)

        error_label = ttk.Label(frame, text="", style='CardMuted.TLabel')
        error_label.grid(row=row, column=0, columnspan=3, sticky=tk.W, pady=(8, 0))
        row += 1

        def save() -> None:
            ffmpeg = ffmpeg_entry.get().strip()
            if ffmpeg != self.ffmpeg_entry.get():
                if ffmpeg and not self.path_validator(self.path_entry.get(), ffmpeg):
                    error_label.config(text="✗ FFmpeg: not a working FFmpeg executable", foreground=c['error'])
                    return
                self.ffmpeg_entry.delete(0, tk.END)
                self.ffmpeg_entry.insert(0, ffmpeg)
                self.config_handler('update', 'ffmpeg_path', ffmpeg)
            try:
                limit = int(limit_var.get().strip() or 0)
                if limit < 0:
                    raise ValueError
            except ValueError:
                error_label.config(text="✗ Speed limit must be a whole number ≥ 0", foreground=c['error'])
                return
            browser = browser_var.get()
            for key, value in (('max_concurrent', int(concurrent_var.get())), ('rate_limit_kb', limit),
                               ('embed_subtitles', subs_var.get()),
                               ('subtitle_langs', langs_entry.get().strip() or 'en'),
                               ('embed_thumbnail', thumb_var.get()), ('add_metadata', meta_var.get()),
                               ('cookies_browser', '' if browser == 'none' else browser),
                               ('watch_clipboard', clip_var.get())):
                self.config_handler('update', key, value)
            self.set_status("Settings saved", 'green', reset_after=3000)
            win.destroy()

        buttons = ttk.Frame(frame, style='Card.TFrame')
        buttons.grid(row=row, column=0, columnspan=3, sticky=tk.E, pady=(12, 0))
        ttk.Button(buttons, text="Get FFmpeg",
                   command=lambda: webbrowser.open('https://ffmpeg.org/download.html')).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text="Save", style='Accent.TButton', command=save).pack(side=tk.LEFT)
        win.grab_set()

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def show_preview(self) -> None:
        """Show details of the selected item; for playlists, choose which videos to get."""
        selected = self.queue_tree.selection()
        if not selected:
            self.set_status("Select an item in the queue to preview", 'orange', reset_after=3000)
            return
        item_id = selected[0]
        url = self.queue_tree.set(item_id, 'url')
        c = self.colors
        win, frame = self._dialog("Preview")
        win.geometry("620x480")
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(2, weight=1)

        thumb_label = ttk.Label(frame, style='Card.TLabel')
        thumb_label.grid(row=0, column=0, rowspan=2, sticky=tk.NW, padx=(0, 12))
        title_label = ttk.Label(frame, text="Loading details…", style='Section.TLabel', wraplength=380)
        title_label.grid(row=0, column=1, sticky=tk.NW)
        meta_label = ttk.Label(frame, text=url, style='CardMuted.TLabel', wraplength=380)
        meta_label.grid(row=1, column=1, sticky=tk.NW, pady=(4, 0))

        def work() -> None:
            try:
                info = self.queue_handler('fetch_info', url)
            except Exception as e:  # network or extraction error
                self.root.after(0, failed, str(e))
                return
            self.root.after(0, loaded, info)
            thumb = self._load_thumbnail(info.get('thumbnail'))
            if thumb is not None:
                self.root.after(0, show_thumb, thumb)

        def failed(message: str) -> None:
            if win.winfo_exists():
                title_label.config(text="Could not load details")
                meta_label.config(text=message.replace('ERROR: ', '')[:300], foreground=c['error'])

        def show_thumb(data: Any) -> None:
            if not win.winfo_exists():
                return
            try:
                from PIL import ImageTk
                image = ImageTk.PhotoImage(data)
            except Exception:
                return
            thumb_label.configure(image=image)
            thumb_label.image = image  # keep a reference

        def loaded(info: Dict[str, Any]) -> None:
            if not win.winfo_exists():
                return
            title_label.config(text=info['title'])
            if self.queue_tree.exists(item_id):
                self.update_queue_item_title(item_id, info['title'])
            parts = [info.get('uploader'), format_duration(info.get('duration'))]
            if info.get('view_count'):
                parts.append(f"{info['view_count']:,} views")
            if info.get('filesize'):
                parts.append(f"≈ {format_bytes(info['filesize'])}")
            if info['entries']:
                parts.append(f"{len(info['entries'])} videos")
            meta_label.config(text="  ·  ".join(p for p in parts if p))
            if info['entries']:
                build_playlist(info['entries'])
            else:
                ttk.Button(frame, text="Close", command=win.destroy).grid(
                    row=3, column=0, columnspan=2, sticky=tk.E, pady=(12, 0))

        def build_playlist(entries: List[Dict[str, Any]]) -> None:
            chosen = set(self._parse_playlist_items(self.queue_tree.set(item_id, 'quality')))
            list_frame = ttk.Frame(frame, style='Card.TFrame')
            list_frame.grid(row=2, column=0, columnspan=2, sticky=tk.NSEW, pady=(12, 0))
            list_frame.columnconfigure(0, weight=1)
            list_frame.rowconfigure(0, weight=1)
            tree = ttk.Treeview(list_frame, columns=('check', 'index', 'title', 'duration'), show='headings',
                                selectmode='none')
            for col, text, width, stretch in (('check', "", 30, False), ('index', "#", 44, False),
                                              ('title', "Title", 380, True), ('duration', "Length", 70, False)):
                tree.heading(col, text=text, anchor=tk.W)
                tree.column(col, width=width, stretch=stretch, anchor=tk.W)
            scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
            tree.configure(yscrollcommand=scroll.set)
            tree.grid(row=0, column=0, sticky=tk.NSEW)
            scroll.grid(row=0, column=1, sticky=tk.NS)
            for entry in entries:
                mark = '☑' if not chosen or entry['index'] in chosen else '☐'
                tree.insert('', tk.END, iid=str(entry['index']),
                            values=(mark, entry['index'], entry['title'], format_duration(entry.get('duration'))))

            count_label = ttk.Label(frame, style='CardMuted.TLabel')
            count_label.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))

            def refresh_count() -> None:
                picked = sum(1 for iid in tree.get_children() if tree.set(iid, 'check') == '☑')
                count_label.config(text=f"{picked} of {len(entries)} selected — click a row to toggle")

            def toggle(event: tk.Event) -> None:
                row_id = tree.identify_row(event.y)
                if row_id:
                    tree.set(row_id, 'check', '☐' if tree.set(row_id, 'check') == '☑' else '☑')
                    refresh_count()

            def set_all(value: str) -> None:
                for iid in tree.get_children():
                    tree.set(iid, 'check', value)
                refresh_count()

            def apply() -> None:
                picked = [int(iid) for iid in tree.get_children() if tree.set(iid, 'check') == '☑']
                if not picked:
                    count_label.config(text="Select at least one video", foreground=c['error'])
                    return
                spec = '' if len(picked) == len(entries) else self._format_playlist_items(picked)
                if self.queue_handler('update_item', (item_id, {'playlist_items': spec})):
                    self._update_row_playlist(item_id, spec)
                    self.set_status(f"Will download {len(picked)} of {len(entries)} videos", 'green',
                                    reset_after=4000)
                    win.destroy()
                else:
                    count_label.config(text="This item already started — pause it first", foreground=c['error'])

            tree.bind('<Button-1>', toggle)
            refresh_count()
            buttons = ttk.Frame(frame, style='Card.TFrame')
            buttons.grid(row=4, column=0, columnspan=2, sticky=tk.EW, pady=(8, 0))
            ttk.Button(buttons, text="Select all", command=lambda: set_all('☑')).pack(side=tk.LEFT)
            ttk.Button(buttons, text="Select none", command=lambda: set_all('☐')).pack(side=tk.LEFT, padx=6)
            ttk.Button(buttons, text="Apply", style='Accent.TButton', command=apply).pack(side=tk.RIGHT)
            ttk.Button(buttons, text="Cancel", command=win.destroy).pack(side=tk.RIGHT, padx=6)

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _load_thumbnail(url: Optional[str]) -> Any:
        """Download a thumbnail and return a PIL image, or None (Pillow is optional)."""
        if not url:
            return None
        try:
            import io
            from PIL import Image
            with urllib.request.urlopen(url, timeout=10) as response:
                image = Image.open(io.BytesIO(response.read()))
                image.load()
            image.thumbnail((200, 112))
            return image
        except Exception:
            return None

    @staticmethod
    def _format_playlist_items(indexes: List[int]) -> str:
        """[1,2,3,5,7,8] -> '1-3,5,7-8' (yt-dlp playlist_items syntax)."""
        parts: List[str] = []
        start = prev = None
        for index in sorted(indexes) + [None]:
            if start is None:
                start = prev = index
            elif index is not None and index == prev + 1:
                prev = index
            else:
                parts.append(str(start) if start == prev else f"{start}-{prev}")
                start = prev = index
        return ','.join(parts)

    @staticmethod
    def _parse_playlist_items(text: str) -> List[int]:
        """Read the '#1-3,5' suffix shown in the Quality column back into indexes."""
        if '#' not in text:
            return []
        indexes: List[int] = []
        for part in text.split('#', 1)[1].split(','):
            part = part.strip()
            if '-' in part:
                low, high = part.split('-', 1)
                if low.isdigit() and high.isdigit():
                    indexes.extend(range(int(low), int(high) + 1))
            elif part.isdigit():
                indexes.append(int(part))
        return indexes

    def _update_row_playlist(self, item_id: str, spec: str) -> None:
        quality = self.queue_tree.set(item_id, 'quality').split(' · #')[0]
        self.queue_tree.set(item_id, 'quality', f"{quality} · #{spec}" if spec else quality)

    # ------------------------------------------------------------------
    # Clipboard
    # ------------------------------------------------------------------

    def _read_clipboard(self) -> str:
        try:
            return self.root.clipboard_get()
        except tk.TclError:
            return ''

    def _poll_clipboard(self) -> None:
        """Put newly copied YouTube links into the link box."""
        try:
            if self.config_handler('get', 'watch_clipboard'):
                text = self._read_clipboard()
                if text and text != self._last_clipboard:
                    self._last_clipboard = text
                    self._take_clipboard_links(text)
        finally:
            self.root.after(1000, self._poll_clipboard)

    def _take_clipboard_links(self, text: str) -> None:
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        if not lines or len(lines) > 200 or not all(self.queue_handler('validate_url', l) for l in lines):
            return
        known = set(self._get_url_lines())
        known.update(self.queue_tree.set(iid, 'url') for iid in self.queue_tree.get_children())
        new = [line for line in lines if line not in known]
        if not new:
            return
        self._hide_placeholder()
        current = self.url_text.get('1.0', 'end-1c')
        if current and not current.endswith('\n'):
            self.url_text.insert(tk.END, '\n')
        self.url_text.insert(tk.END, '\n'.join(new) + '\n')
        self._validate_urls()
        self.set_status(f"Link{'s' if len(new) > 1 else ''} from clipboard ready — press Add to queue",
                        'black', reset_after=5000)

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------

    def _load_existing_queue(self) -> None:
        for item in self.queue_handler('items') or []:
            self._insert_queue_row(item)
            if item.get('state') == 'paused':
                self.update_queue_item_status(item['id'], 'Paused')

    def _insert_queue_row(self, item: Dict[str, Any]) -> None:
        quality = item['quality']
        if item['media_type'] == 'Audio':
            quality = f"{item.get('audio_format', '')} {quality}"
        if item.get('playlist_items'):
            quality += f" · #{item['playlist_items']}"
        self.queue_tree.insert('', tk.END, iid=item['id'],
                               values=(item.get('title') or item['url'], item['url'],
                                       item['media_type'], quality, "Queued"))

    def _refresh_queue_summary(self) -> None:
        rows = self.queue_tree.get_children()
        if not rows:
            self.queue_summary.config(text="Empty — add links above")
            return
        counts: Dict[str, int] = {}
        for iid in rows:
            status = self.queue_tree.set(iid, 'status').split(' ')[0]
            counts[status] = counts.get(status, 0) + 1
        parts = [f"{counts[k]} {k.lower()}" for k in ('Queued', 'Downloading', 'Paused', 'Complete',
                                                      'Failed', 'Cancelled')
                 if counts.get(k)]
        self.queue_summary.config(text=" · ".join(parts))

    def remove_selected(self) -> None:
        skipped = 0
        for iid in self.queue_tree.selection():
            if iid in self.active_ids:
                skipped += 1
                continue
            self.queue_tree.delete(iid)
            self.queue_handler('remove', iid)
        if skipped:
            self.set_status("Items that are downloading must be cancelled or paused first", 'orange')
        self._refresh_queue_summary()

    def clear_queue(self) -> None:
        """Clear everything except the item currently downloading."""
        for iid in self.queue_tree.get_children():
            if iid not in self.active_ids:
                self.queue_tree.delete(iid)
        self.queue_handler('clear', None)
        self._refresh_queue_summary()

    def clear_completed(self) -> None:
        """Remove finished rows (complete, failed or cancelled)."""
        for iid in self.queue_tree.get_children():
            if self.queue_tree.set(iid, 'status') in FINISHED_STATUSES:
                self.queue_tree.delete(iid)
                self.queue_handler('remove', iid)
        self._refresh_queue_summary()

    def update_queue_item_status(self, item_id: str, status: str) -> None:
        if not self.queue_tree.exists(item_id):
            return
        self.queue_tree.set(item_id, 'status', status)
        if status == 'Downloading':
            self.active_ids.add(item_id)
        else:
            self.active_ids.discard(item_id)
            self.item_progress.pop(item_id, None)
            self.item_speed.pop(item_id, None)
        tag = STATUS_TAGS.get(status)
        self.queue_tree.item(item_id, tags=(tag,) if tag else ())
        if status == 'Downloading':
            self.queue_tree.see(item_id)
        self._refresh_queue_summary()

    def update_queue_item_title(self, item_id: str, title: str) -> None:
        if self.queue_tree.exists(item_id):
            self.queue_tree.set(item_id, 'title', title)

    def pause_selected(self) -> None:
        paused = sum(1 for iid in self.queue_tree.selection()
                     if self.queue_tree.set(iid, 'status').split(' ')[0] in ('Queued', 'Downloading')
                     and self.queue_handler('pause', iid))
        if paused:
            self.set_status(f"Pausing {paused} item(s) — partial downloads are kept", 'orange', reset_after=4000)

    def resume_selected(self) -> None:
        resumed = 0
        for iid in self.queue_tree.selection():
            status = self.queue_tree.set(iid, 'status')
            if status == 'Paused':
                resumed += bool(self.queue_handler('resume', iid))
            elif status in ('Failed', 'Cancelled'):
                resumed += bool(self.queue_handler('retry', iid))
        if resumed:
            self.set_status(f"Resuming {resumed} item(s)", 'black', reset_after=4000)
        else:
            self.set_status("Select paused, failed or cancelled items to resume", 'orange', reset_after=4000)

    def cancel_selected(self) -> None:
        for iid in self.queue_tree.selection():
            if iid in self.active_ids:
                self.queue_handler('cancel_item', iid)

    def _show_context_menu(self, event: tk.Event) -> None:
        row = self.queue_tree.identify_row(event.y)
        if row:
            if row not in self.queue_tree.selection():
                self.queue_tree.selection_set(row)
            self.context_menu.tk_popup(event.x_root, event.y_root)

    def _open_in_browser(self) -> None:
        selected = self.queue_tree.selection()
        if selected:
            webbrowser.open(self.queue_tree.set(selected[0], 'url'))

    def _copy_link(self) -> None:
        selected = self.queue_tree.selection()
        if selected:
            self.root.clipboard_clear()
            self.root.clipboard_append('\n'.join(self.queue_tree.set(i, 'url') for i in selected))

    # ------------------------------------------------------------------
    # Downloading
    # ------------------------------------------------------------------

    def toggle_download(self) -> None:
        if self.downloading:
            self.download_handler('cancel')
            return
        if not self.queue_handler('list'):
            self.set_status("Queue is empty — add links first", 'orange')
            return
        self._save_download_path()
        if not self.path_validator(self.path_entry.get(), self.ffmpeg_entry.get()):
            if messagebox.askyesno(
                    "FFmpeg not found",
                    "FFmpeg is needed to merge video/audio and convert audio.\n\n"
                    "Open settings to choose the FFmpeg executable?"):
                self.show_settings()
            return
        self.start_download()

    def start_download(self) -> None:
        if not self.downloading:
            self.progress_bar['value'] = 0
            self.stats_label.config(text="")
        self.set_status("Starting…", 'black')
        self.download_handler('start')

    def update_download_state(self, downloading: bool, cancelled: bool) -> None:
        self.downloading = downloading
        self.cancel_requested = cancelled
        if downloading and cancelled:
            self.download_btn.config(text="Cancelling…", style='TButton', state=tk.DISABLED)
        elif downloading:
            self.download_btn.config(text="Cancel", style='TButton', state=tk.NORMAL)
        else:
            self.download_btn.config(text="Start downloads", style='Accent.TButton', state=tk.NORMAL)

    def update_progress(self, item_id: str, percent: float, speed: str, eta: str, size: str,
                        speed_bps: float = 0.0) -> None:
        if item_id not in self.active_ids:
            return
        self.item_progress[item_id] = percent
        self.item_speed[item_id] = speed_bps
        if self.queue_tree.exists(item_id):
            self.queue_tree.set(item_id, 'status', f"Downloading {percent:.0f}%")

        active = len(self.item_progress)
        self.progress_bar['value'] = sum(self.item_progress.values()) / active
        if active == 1:
            self.stats_label.config(text=f"{percent:.1f}%  ·  {speed}  ·  ETA {eta}  ·  {size}")
        else:
            total_speed = format_bytes(sum(self.item_speed.values()))
            self.stats_label.config(text=f"{active} downloads  ·  {total_speed}/s total")

    def download_complete(self, success: bool) -> None:
        if success:
            self.set_status("All downloads finished", 'green', reset_after=5000)
            self.root.bell()
        elif self.cancel_requested:
            self.set_status("Downloads cancelled", 'orange', reset_after=5000)
        else:
            self.set_status("Finished with errors — see the queue for failed items", 'red')
        self.stats_label.config(text="")
        self.reset_ui()

    def reset_ui(self) -> None:
        self.downloading = False
        self.cancel_requested = False
        self.active_ids.clear()
        self.item_progress.clear()
        self.item_speed.clear()
        self.update_download_state(False, False)
        self._refresh_queue_summary()

    def set_status(self, message: str, color: str = 'black', reset_after: Optional[int] = None) -> None:
        """Show a status message; `color` is a core color name (green/red/orange/black)."""
        self._status_color = STATUS_COLORS.get(color, 'fg')
        self.status_label.config(text=message, foreground=self.colors[self._status_color])
        if self._status_reset_job:
            self.root.after_cancel(self._status_reset_job)
            self._status_reset_job = None
        if reset_after:
            self._status_reset_job = self.root.after(reset_after, lambda: self.set_status("Ready", 'gray'))

    # ------------------------------------------------------------------
    # Other windows / actions
    # ------------------------------------------------------------------

    def open_download_folder(self) -> None:
        path = self.path_entry.get()
        if not os.path.isdir(path):
            messagebox.showerror("Folder not found", f"Folder not found:\n{path}")
            return
        try:
            if sys.platform == 'win32':
                os.startfile(path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except OSError as e:
            messagebox.showerror("Error", f"Could not open folder: {e}")

    def show_history(self) -> None:
        c = self.colors
        win = tk.Toplevel(self.root)
        win.title("Download history")
        win.geometry("760x400")
        win.configure(background=c['bg'])
        win.transient(self.root)
        frame = ttk.Frame(win, style='Card.TFrame', padding=12)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        columns = ('time', 'title', 'format', 'status', 'url')
        tree = ttk.Treeview(frame, columns=columns, show='headings',
                            displaycolumns=('time', 'title', 'format', 'status'))
        for col, text, width in (('time', "Time", 140), ('title', "Title", 380),
                                 ('format', "Format", 80), ('status', "Status", 90)):
            tree.heading(col, text=text, anchor=tk.W)
            tree.column(col, width=width, stretch=(col == 'title'))
        tree.tag_configure('Complete', foreground=c['success'])
        tree.tag_configure('Failed', foreground=c['error'])
        tree.tag_configure('Cancelled', foreground=c['warning'])
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.grid(row=0, column=0, sticky=tk.NSEW)
        scrollbar.grid(row=0, column=1, sticky=tk.NS)

        entries = self.queue_handler('history') or []
        for entry in entries:
            timestamp = entry.get('timestamp', '')[:16].replace('T', ' ')
            status = entry.get('status', '')
            tree.insert('', tk.END, tags=(status,),
                        values=(timestamp, entry.get('title', ''), entry.get('format', ''),
                                status, entry.get('url', '')))
        tree.bind('<Double-1>', lambda e: tree.selection() and webbrowser.open(tree.set(tree.selection()[0], 'url')))
        ttk.Label(frame, text=f"{len(entries)} entries · double-click to open in browser",
                  style='CardMuted.TLabel').grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        win.bind('<Escape>', lambda e: win.destroy())

    def clean_exit(self) -> None:
        self._save_download_path()
        if self.downloading:
            self.download_handler('cancel')
        self.config_handler('save', None, None)
        self.root.destroy()


# Backwards-compatible name used by main.py
EnhancedYouTubeDownloaderUI = YouTubeDownloaderUI


class Tooltip:
    """Small hover tooltip for a widget."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.window: Optional[tk.Toplevel] = None
        self.job: Optional[str] = None
        widget.bind('<Enter>', lambda e: self._schedule(), add='+')
        widget.bind('<Leave>', lambda e: self._hide(), add='+')
        widget.bind('<ButtonPress>', lambda e: self._hide(), add='+')

    def _schedule(self) -> None:
        self._cancel()
        self.job = self.widget.after(600, self._show)

    def _cancel(self) -> None:
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None

    def _show(self) -> None:
        if self.window:
            return
        x = self.widget.winfo_pointerx() + 12
        y = self.widget.winfo_pointery() + 16
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f'+{x}+{y}')
        tk.Label(self.window, text=self.text, background='#2b2e34', foreground='#ffffff',
                 padx=8, pady=4, font=('TkDefaultFont', 9)).pack()

    def _hide(self) -> None:
        self._cancel()
        if self.window:
            self.window.destroy()
            self.window = None
