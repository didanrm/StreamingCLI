<h1 align="center">StreamingCLI</h1>

<p align="center">
  <em>Paste link. VLC opens. Temporary cache disappears when you are done.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9%2B-111111?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/node-%3E%3D16-111111?style=flat-square&logo=nodedotjs&logoColor=white" alt="Node >=16">
  <img src="https://img.shields.io/badge/player-VLC-111111?style=flat-square&logo=vlcmediaplayer&logoColor=white" alt="VLC">
  <img src="https://img.shields.io/badge/providers-direct%20%7C%20filedon%20%7C%20pixeldrain%20%7C%20krakenfiles-111111?style=flat-square" alt="Supported providers">
</p>

<p align="center">
  <strong>Link-to-VLC streamer with byte-range proxy, temporary cache, and automatic cleanup.</strong>
</p>

---

StreamingCLI memutar video dari link hosting langsung ke VLC tanpa download manual. Tool ini resolve link provider, membuka proxy lokal di `127.0.0.1`, lalu VLC membaca video dari proxy tersebut dengan dukungan seek lewat HTTP Range.

Begitu VLC ditutup, server lokal berhenti dan cache sementara dibersihkan otomatis.

## Preview

```text
+----------------------------------------------------------+
|                    StreamingCLI                          |
|      Link-to-VLC streamer with temporary cache            |
+----------------------------------------------------------+

1. Start Streaming
   Paste link video, lalu buka langsung di VLC

2. List Providers
   Lihat sumber link yang saat ini didukung

3. Exit
   Keluar dari StreamingCLI
```

## Fitur

- Stream link video ke VLC tanpa menyimpan file permanen.
- Seek maju/mundur untuk provider yang mendukung byte range.
- Cache sementara per sesi, otomatis hilang setelah VLC ditutup.
- Bisa dipakai sebagai CLI Python atau menu Node.js.
- Minim dependency: hanya butuh Python, Node.js, dan VLC.

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

Install Git, Node.js, Python, dan VLC dulu. Kalau pakai PowerShell:

```powershell
winget install Git.Git OpenJS.NodeJS Python.Python.3.12 VideoLAN.VLC
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
```

Atau via Python:

```bash
python3 stream.py "https://example.com/video.mp4"
```

Lihat provider:

```bash
streamingcli --list-providers
```

## Opsi

| Opsi | Fungsi |
|---|---|
| `--vlc-path <path>` | Pakai path VLC custom |
| `--keep-cache` | Simpan cache setelah selesai untuk debug |
| `--port <number>` | Pakai port lokal tertentu |
| `--quiet` | Sembunyikan log proxy |
| `--list-providers` | Tampilkan provider yang didukung |

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
VLC
```

Saat VLC meminta byte tertentu, StreamingCLI mengambil range yang sama dari provider, mengirimkannya ke VLC, dan menyimpan chunk itu ke cache sementara. Kalau bagian yang sama diminta lagi, data dikirim dari cache lokal.

## Requirements

- Python 3.9+
- Node.js 16+
- VLC Media Player
- macOS atau Windows

## Development

```bash
npm test
```

Test menjalankan self-check Python dan memastikan daftar provider bisa dibaca dari CLI Node.js.

## Catatan

StreamingCLI hanya alat teknis untuk memutar link yang sudah kamu miliki aksesnya. Link private, captcha, quota limit, DRM, atau file yang sudah dihapus tetap bisa gagal karena pembatasan dari provider.
