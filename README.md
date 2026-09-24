# YouTube Downloader

Aplikasi desktop berbasis GUI untuk mengunduh video/audio dari YouTube. Dibangun dengan Python + Tkinter, memakai [yt-dlp](https://github.com/yt-dlp/yt-dlp) sebagai engine pengunduhan dan FFmpeg untuk menggabungkan/konversi file.

## Fitur

- **Video**: Best, 1080p, 720p, 480p, 360p — hasil digabung ke MP4 (termasuk sumber VP9/AV1, jadi kualitas 1440p/4K ikut terambil pada "Best")
- **Audio**: mp3, aac, wav, m4a dengan bitrate 128k–320k
- **Antrean (queue)**: tempel banyak URL sekaligus (satu per baris), hapus item, clear, clear completed
- **Status per item**: judul video, progres `Downloading 42%`, Complete / Failed / Cancelled
- **Playlist**: disimpan di folder bernama playlist, berurutan (`001 - Judul [id].mp4`)
- **Cancel** yang benar-benar menghentikan download dan menghapus file `.part`
- **Antrean dilanjutkan** otomatis setelah aplikasi ditutup/dibuka lagi
- **Riwayat download** dan tombol **Open Folder**
- Nama file memakai ID video (`Judul [id].mp4`) sehingga judul yang sama tidak saling menimpa

URL yang didukung: `youtube.com/watch`, `youtu.be`, `youtube.com/shorts`, `youtube.com/live`, `youtube.com/embed`, `youtube.com/playlist`, termasuk subdomain `m.` dan `music.`.

## Persyaratan

- Python 3.9+ (dengan Tkinter; di Linux: `sudo apt install python3-tk`)
- [FFmpeg](https://ffmpeg.org/download.html) — dicari otomatis di PATH, atau pilih lokasinya lewat aplikasi
- Windows 10/11, macOS, atau Linux

## Instalasi & Menjalankan

```bash
pip install -r requirements.txt
python main.py
```

Perbarui yt-dlp secara berkala bila download mulai gagal (YouTube sering berubah):

```bash
pip install -U yt-dlp
```

## Lokasi Data

Config, antrean, riwayat, dan log disimpan di:

- Windows: `%APPDATA%\YouTubeDownloader\`
- macOS/Linux: `~/.yt-downloader/`

## Testing

Unit test untuk logika inti (tanpa jaringan, yt-dlp disimulasikan):

```bash
python -m unittest discover -s tests
```
