import tkinter as tk
from tkinter import ttk

class SettingsPanel(ttk.Frame):
    def __init__(self, parent, config):
        super().__init__(parent)
        self.config = config
        self.create_widgets()

    def create_widgets(self):
        self.media_type_label = ttk.Label(self, text="Media Type:")
        self.media_type = ttk.Combobox(self, values=('Video', 'Audio'), width=10)
        
        self.url_entry = ttk.Entry(self, width=50)
        self.add_queue_btn = ttk.Button(self, text="Add to Queue")
        
        self.path_entry = ttk.Entry(self, width=40)
        self.browse_path_btn = ttk.Button(self, text="Browse")
        
        self.ffmpeg_entry = ttk.Entry(self, width=40)
        self.browse_ffmpeg_btn = ttk.Button(self, text="Browse")
        
        self.arrange_layout()

    def arrange_layout(self):
        self.media_type_label.grid(row=0, column=0, sticky=tk.W)
        self.media_type.grid(row=0, column=1, sticky=tk.W)
        # Add remaining grid layout for other components