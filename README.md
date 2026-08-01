<h1 align="center">StreamingCLI</h1>

<p align="center">
  <em>Paste link. Your video player opens. Temporary cache disappears when you are done.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9%2B-111111?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/node-%3E%3D16-111111?style=flat-square&logo=nodedotjs&logoColor=white" alt="Node >=16">
  <img src="https://img.shields.io/badge/player-auto--detect-111111?style=flat-square" alt="Auto-detect player">
  <img src="https://img.shields.io/badge/providers-acefile%20%7C%20direct%20%7C%20filedon%20%7C%20pixeldrain%20%7C%20krakenfiles-111111?style=flat-square" alt="Supported providers">
</p>

<p align="center">
  <strong>Link-to-player streaming with byte-range proxy, temporary cache, and automatic cleanup.</strong>
</p>

---

StreamingCLI memutar video dari link hosting langsung ke video player tanpa download manual. Tool ini resolve link provider, membuka proxy lokal di `127.0.0.1`, lalu player membaca video dari proxy tersebut dengan dukungan seek lewat HTTP Range.

StreamingCLI mendeteksi IINA, mpv, VLC, atau ffplay jika tersedia. Player lain bisa dipilih lewat `--player`; jika tidak ada yang terdeteksi, aplikasi bawaan OS akan dipakai.

## Preview

```text
+----------------------------------------------------------+
|                    StreamingCLI                          |
|     Link-to-player streaming with temporary cache         |
+----------------------------------------------------------+

1. Start Streaming
   Paste link video, lalu buka di video player

2. List Providers
   Lihat sumber link yang saat ini didukung

3. Exit
   Keluar dari StreamingCLI
```

## Fitur

- Stream link video ke video player tanpa menyimpan file permanen.
- Seek maju/mundur untuk provider yang mendukung byte range.
- Cache sementara per sesi, dibersihkan saat sesi berakhir.
- Auto-detect player dan dukungan path player custom.
- Bisa dipakai sebagai CLI Python atau menu Node.js.
- Minim dependency: hanya butuh Python, Node.js, dan video player.

## Install

### Dari GitHub macOS/Linux

```bash
curl -fsSL https://raw.githubusercontent.com/didanrm/streamingcli/main/install.sh | sh
```

Lalu jalankan:

```bash
streamingcli
```

### Dari GitHub Windows

Install Git, Node.js, Python, dan video player pilihanmu dulu. Kalau pakai PowerShell:

```powershell
winget install Git.Git OpenJS.NodeJS Python.Python.3.12
npm install -g github:didanrm/streamingcli#main
setx STREAMINGCLI_PYTHON python
```

Tutup PowerShell, buka lagi, lalu jalankan:

```powershell
streamingcli
```

### Dari folder project

```bash
npm install -g .
streamingcli
```

## Cara Pakai

Mode menu:

```bash
streamingcli
```

Langsung dari URL:

```bash
streamingcli "https://pixeldrain.com/u/FILE_ID"
streamingcli "https://acefile.co/f/FILE_ID/file-name-mkv"
```

Pilih player tertentu:

```bash
streamingcli --player mpv "https://pixeldrain.com/u/FILE_ID"
streamingcli --player "QuickTime Player" "https://example.com/video.mp4"
```

Atau via Python:

```bash
python3 stream.py "https://example.com/video.mp4"
```

Lihat provider:

```bash
streamingcli --list-providers
```

Update dari branch `main` GitHub:

```bash
streamingcli --update
```

## Opsi

| Opsi | Fungsi |
|---|---|
| `--player <command/path>` | Pakai video player tertentu |
| `--keep-cache` | Simpan cache setelah selesai untuk debug |
| `--port <number>` | Pakai port lokal tertentu |
| `--quiet` | Sembunyikan log proxy |
| `--list-providers` | Tampilkan provider yang didukung |
| `--update` | Install ulang versi terbaru dari GitHub `main` |

## Cara Kerja

```text
URL
 │
 ▼
Provider resolver
 │
 ▼
Direct stream URL
 │
 ▼
Local HTTP proxy 127.0.0.1
 │
 ▼
Video player
```

Saat player meminta byte tertentu, StreamingCLI mengambil range yang sama dari provider, mengirimkannya ke player, dan menyimpan chunk itu ke cache sementara. Kalau bagian yang sama diminta lagi, data dikirim dari cache lokal.

## Requirements

- Python 3.9+
- Node.js 16+
- Video player yang menerima URL HTTP dan mendukung format videonya
- macOS, Windows, atau Linux

## Development

```bash
npm test
```

Test menjalankan self-check Python dan memastikan daftar provider bisa dibaca dari CLI Node.js.

## Catatan

StreamingCLI hanya alat teknis untuk memutar link yang sudah kamu miliki aksesnya. Link private, captcha, quota limit, DRM, atau file yang sudah dihapus tetap bisa gagal karena pembatasan dari provider.

File statis dari provider tidak memiliki adaptive bitrate seperti YouTube. Kelancaran tetap dipengaruhi kecepatan provider, koneksi pengguna, format/codec, dan kemampuan buffer player. QuickTime mendukung MP4 tetapi tidak mendukung MKV secara native; gunakan IINA, mpv, VLC, atau player kompatibel untuk MKV.
