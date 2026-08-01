<h1 align="center">StreamingCLI</h1>

<p align="center">
  <em>Paste a link. Watch in your video player or browser. Temporary cache disappears when you are done.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9%2B-111111?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/node-%3E%3D16-111111?style=flat-square&logo=nodedotjs&logoColor=white" alt="Node >=16">
  <img src="https://img.shields.io/badge/playback-player%20%7C%20browser-111111?style=flat-square" alt="Video player or browser">
  <img src="https://img.shields.io/badge/providers-acefile%20%7C%20direct%20%7C%20filedon%20%7C%20pixeldrain%20%7C%20krakenfiles-111111?style=flat-square" alt="Supported providers">
</p>

<p align="center">
  <strong>Link streaming with a byte-range proxy, temporary cache, and automatic cleanup.</strong>
</p>

---

StreamingCLI resolves supported hosting links and exposes the video through a local proxy at `127.0.0.1`. You can watch through an installed video player or an automatically opened browser page, with seeking supported through HTTP byte ranges.

For local playback, StreamingCLI detects IINA, mpv, VLC, or ffplay when available. Any other player can be selected with `--player`; otherwise, the operating system default is used.

## Preview

```text
+----------------------------------------------------------+
|                    StreamingCLI                          |
|     Stream in your video player or browser               |
+----------------------------------------------------------+

1. Start Streaming
   Paste a video link and choose where to watch

2. List Providers
   Show currently supported link providers

3. Exit
   Close StreamingCLI

Playback Mode
1. Video Player
2. Browser
3. Back
```

## Features

- Stream hosted videos without saving a permanent copy.
- Watch in a local video player or browser.
- Get consistent browser controls through Video.js with native HTML5 fallback.
- Seek forward and backward when the provider supports byte ranges.
- Use a temporary per-session cache that is removed when the session ends.
- Auto-detect common players or use a custom player path.
- Run through either the Node.js menu or the Python CLI.
- No third-party runtime dependencies.

## Install

### From GitHub on macOS/Linux

```bash
curl -fsSL https://raw.githubusercontent.com/didanrm/streamingcli/main/install.sh | sh
```

Then run:

```bash
streamingcli
```

### From GitHub on Windows

Install Git, Node.js, Python, and your preferred video player first. In PowerShell:

```powershell
winget install Git.Git OpenJS.NodeJS Python.Python.3.12
npm install -g github:didanrm/streamingcli#main
setx STREAMINGCLI_PYTHON python
```

Close PowerShell, open it again, then run:

```powershell
streamingcli
```

### From the project folder

```bash
npm install -g .
streamingcli
```

## Usage

Open the interactive menu:

```bash
streamingcli
```

Open a URL in an automatically detected video player:

```bash
streamingcli "https://pixeldrain.com/u/FILE_ID"
streamingcli "https://acefile.co/f/FILE_ID/file-name-mkv"
```

Open a URL in the browser:

```bash
streamingcli --browser "https://pixeldrain.com/u/FILE_ID"
```

Choose a specific player:

```bash
streamingcli --player mpv "https://pixeldrain.com/u/FILE_ID"
streamingcli --player "QuickTime Player" "https://example.com/video.mp4"
```

Run through Python:

```bash
python3 stream.py --browser "https://example.com/video.mp4"
```

List providers:

```bash
streamingcli --list-providers
```

Update from the GitHub `main` branch:

```bash
streamingcli --update
```

## Options

| Option | Purpose |
|---|---|
| `--browser` | Print a local watch link and open it in the browser |
| `--player <command/path>` | Use a specific video player |
| `--keep-cache` | Keep the temporary cache for debugging |
| `--port <number>` | Use a specific local proxy port |
| `--quiet` | Hide proxy request logs |
| `--list-providers` | Show supported providers |
| `--update` | Reinstall the latest version from GitHub `main` |

## How It Works

```text
URL
 |
 v
Provider resolver
 |
 v
Direct stream URL
 |
 v
Local HTTP proxy at 127.0.0.1
 |
 +--> Video player
 |
 +--> Browser page
```

When playback requests a byte range, StreamingCLI fetches the same range from the provider, forwards it, and saves the chunk in the temporary cache. Repeated requests for cached bytes are served locally.

## Requirements

- Python 3.9+
- Node.js 16+
- macOS, Windows, or Linux
- A compatible video player for local-player mode
- A browser-supported container and codec for browser mode

## Development

```bash
npm test
```

The test command runs the Python self-check and verifies that the provider list is available through the Node.js CLI.

## Notes

StreamingCLI is a technical tool for playing links you already have permission to access. Private links, captchas, quotas, DRM, removed files, and provider restrictions can still prevent playback.

Browser mode uses the stable Video.js 8 player and falls back to native HTML5 video if its CDN is unavailable. It supports current Chrome, Edge, Firefox, and Safari releases, but the browser must still support the file's container and codecs.

Static provider files do not offer adaptive bitrate like YouTube. Playback quality still depends on provider speed, network quality, the file codec, and player buffering. Browsers and QuickTime do not natively support every MKV file; use IINA, mpv, VLC, or another compatible player when needed.
