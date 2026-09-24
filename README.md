# YouTube Downloader

Aplikasi desktop berbasis GUI untuk mengunduh video/audio dari YouTube. Dibangun dengan Python + Tkinter, memakai [yt-dlp](https://github.com/yt-dlp/yt-dlp) sebagai engine pengunduhan dan FFmpeg untuk menggabungkan/konversi file.

## Fitur

**Download**
- **Video**: Best, 1080p, 720p, 480p, 360p — digabung ke MP4 (termasuk sumber VP9/AV1, jadi 1440p/4K ikut terambil pada "Best")
- **Audio**: mp3, aac, wav, m4a dengan bitrate 128k–320k
- **Download paralel** (1–3 sekaligus) dan **batas kecepatan** total
- **Pause / Resume per item** — file sementara disimpan, jadi download lanjut dari posisi terakhir (juga setelah aplikasi ditutup)
- **Retry** untuk item yang gagal atau dibatalkan
- **Playlist**: disimpan di folder bernama playlist, berurutan (`001 - Judul [id].mp4`); lewat **Preview** kamu bisa memilih video mana saja yang diunduh
- **Subtitle, thumbnail (cover art), dan metadata** otomatis ditanam ke file (bisa diatur di ⚙ Settings)
- **Cookies dari browser** untuk video yang dibatasi umur atau khusus member
- Nama file memakai ID video (`Judul [id].mp4`) sehingga judul yang sama tidak saling menimpa

**Tampilan**
- Mode terang/gelap (☾/☀), validasi link langsung, tombol Paste
- **Deteksi link otomatis**: link YouTube yang kamu salin langsung muncul di kotak link
- **Preview**: thumbnail, channel, durasi, perkiraan ukuran, dan daftar video playlist
- Status per item, ringkasan antrean, riwayat download, tombol Open folder
- **Update yt-dlp** dari dalam aplikasi (⚙ Settings) — solusi pertama bila download mulai gagal

**Ringan**
- yt-dlp baru dimuat setelah jendela tampil, jadi aplikasi terbuka cepat
- Update progres dibatasi 10×/detik per item

URL yang didukung: `youtube.com/watch`, `youtu.be`, `youtube.com/shorts`, `youtube.com/live`, `youtube.com/embed`, `youtube.com/playlist`, termasuk subdomain `m.` dan `music.`.

### Shortcut

| Tombol | Fungsi |
|---|---|
| `Ctrl+Enter` (di kotak link) | Tambah ke antrean |
| `Delete` (di tabel antrean) | Hapus item terpilih |
| Klik ganda item | Buka di browser |
| Klik kanan item | Menu (preview, pause, resume/retry, cancel, buka, salin link, hapus) |
| `Ctrl+Q` | Keluar |

## Instalasi

### Windows (tanpa Python)

Unduh `YouTubeDownloader-Setup-x.y.z.exe` (installer) atau versi portable `.zip` dari halaman **Releases**. FFmpeg sudah termasuk.

### Dari source

Persyaratan:
- Python 3.9+ (dengan Tkinter; di Linux: `sudo apt install python3-tk`)
- [FFmpeg](https://ffmpeg.org/download.html) — dicari otomatis di PATH, atau pilih lokasinya di ⚙ Settings

```bash
pip install -r requirements.txt
python main.py
```

## Lokasi Data

Config, antrean, riwayat, dan log disimpan di:

- Windows: `%APPDATA%\YouTubeDownloader\`
- macOS/Linux: `~/.yt-downloader/`

## Testing

Unit test untuk logika inti dan GUI (tanpa jaringan, yt-dlp disimulasikan; test GUI otomatis dilewati bila tidak ada layar):

```bash
python -m unittest discover -s tests
```

Test juga dijalankan otomatis oleh GitHub Actions di setiap push (Linux & Windows, Python 3.9 dan 3.12).

## Membuat Release

Build aplikasi Windows + installer dilakukan otomatis oleh GitHub Actions saat tag versi di-push:

```bash
git tag v2.0.0
git push origin v2.0.0
```

Hasilnya (installer `.exe` dan `.zip` portable, dengan FFmpeg di dalamnya) muncul di halaman Releases. Build manual: `pip install pyinstaller pillow`, lalu `python packaging/build.py` (hasil di `dist/YouTubeDownloader/`), dan `iscc packaging\installer.iss` untuk installer.
