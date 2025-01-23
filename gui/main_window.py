import tkinter as tk
from tkinter import ttk
from .components.settings_panel import SettingsPanel
from .components.queue_panel import QueuePanel

class MainWindow:
    def __init__(self, root, config, download_manager):
        self.root = root
        self.config = config
        self.download_manager = download_manager
        self.style = ttk.Style()
        self.setup_window()
        self.create_widgets()

    def setup_window(self):
        self.root.title("YouTube Downloader")
        self.root.geometry("800x600")
        self.root.resizable(False, False)
        self.style.theme_use('clam')
        self.configure_styles()

    def configure_styles(self):
        self.style.configure('TButton', font=('Arial', 10), padding=6)
        self.style.configure('TLabel', font=('Arial', 10))
        self.style.configure('TEntry', font=('Arial', 10), padding=6)
        self.style.configure('red.TButton', foreground='red')
        self.style.configure('green.TButton', foreground='green')

    def create_widgets(self):
        self.main_frame = ttk.Frame(self.root, padding=20)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        self.settings_panel = SettingsPanel(self.main_frame, self.config)
        self.queue_panel = QueuePanel(self.main_frame, self.download_manager)
        
        self.settings_panel.grid(row=0, column=0, sticky="nsew")
        self.queue_panel.grid(row=1, column=0, sticky="nsew")