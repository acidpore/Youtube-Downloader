"""
Build a standalone app folder with PyInstaller.

    python packaging/build.py            # uses ffmpeg found in packaging/ffmpeg/ if present

On Windows, put ffmpeg.exe and ffprobe.exe in packaging/ffmpeg/ to bundle
them (the release workflow downloads them automatically). The result is
dist/YouTubeDownloader/. "onedir" mode is used on purpose: "onefile" unpacks
itself to a temp folder on every launch, which makes startup slow.
"""
import os
import sys

import PyInstaller.__main__

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG_DIR = os.path.join(ROOT, 'packaging', 'ffmpeg')
EXE = '.exe' if sys.platform == 'win32' else ''

args = [
    os.path.join(ROOT, 'main.py'),
    '--name', 'YouTubeDownloader',
    '--noconfirm',
    '--clean',
    '--windowed',
    '--onedir',
    '--distpath', os.path.join(ROOT, 'dist'),
    '--workpath', os.path.join(ROOT, 'build'),
    '--specpath', os.path.join(ROOT, 'build'),
    # Not needed at runtime; keeps the bundle smaller.
    '--exclude-module', 'unittest',
    '--exclude-module', 'pydoc',
]
icon = os.path.join(ROOT, 'packaging', 'icon.ico')
if sys.platform == 'win32' and os.path.exists(icon):
    args += ['--icon', icon]
for tool in ('ffmpeg', 'ffprobe'):
    path = os.path.join(FFMPEG_DIR, tool + EXE)
    if os.path.exists(path):
        args += ['--add-binary', f'{path}{os.pathsep}.']
        print(f'Bundling {path}')

PyInstaller.__main__.run(args)
