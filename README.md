Sebuah aplikasi desktop berbasis GUI untuk mengunduh video dari YouTube dengan berbagai pilihan resolusi. Dibangun menggunakan Python dan library Tkinter untuk antarmuka pengguna, serta memanfaatkan yt-dlp sebagai engine pengunduhan.

Fitur Utama
  1. Multi-Resolusi Support
      - Pilih kualitas video: Best (Terbaik), 1080p, 720p, 480p, atau 360p
      - Format output otomatis dalam MP4
  2. Antarmuka Pengguna Intuitif
      - Input URL YouTube langsung
      - Browser folder untuk memilih lokasi penyimpanan
      - Tampilan progress bar real-time
      - Status update detail (persentase, kecepatan, ETA)
  3. Fungsi Kontrol
      - Tombol cancel untuk menghentikan proses
      - Notifikasi error handling
      - Auto-reset UI setelah selesai
  4. Optimasi Performa
      - Proses unduh di thread terpisah
      - Kompatibel dengan Windows 10/11
      - Mendukung ffmpeg untuk proses remuxing

Persyaratan Sistem :
    1. OS: Windows 7/8/10/11 (64-bit)
    2. Python 3.6+
    3. FFmpeg
