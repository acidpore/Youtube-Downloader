import tkinter as tk
from tkinter import ttk

class QueuePanel(ttk.Frame):
    def __init__(self, parent, download_manager):
        super().__init__(parent)
        self.download_manager = download_manager
        self.create_widgets()

    def create_widgets(self):
        self.queue_listbox = tk.Listbox(self, width=70, height=6)
        self.remove_btn = ttk.Button(self, text="Remove Selected")
        self.clear_btn = ttk.Button(self, text="Clear Queue")
        
        self.queue_listbox.pack(fill=tk.BOTH, expand=True)
        self.remove_btn.pack(side=tk.LEFT)
        self.clear_btn.pack(side=tk.LEFT)