#!/usr/bin/env sh
set -eu

REPO="${STREAMINGCLI_REPO:-didanrm/streamingcli}"
REF="${STREAMINGCLI_REF:-main}"
URL="${STREAMINGCLI_TARBALL_URL:-https://codeload.github.com/$REPO/tar.gz/$REF}"
TMP="${TMPDIR:-/tmp}/streamingcli-install-$$"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "streamingcli: '$1' belum terinstall." >&2
    exit 1
  }
}

need curl
need npm
need node
need python3
need tar

cleanup() {
  rm -rf "$TMP"
}
trap cleanup EXIT INT TERM

mkdir -p "$TMP"
echo "Downloading StreamingCLI from $REPO@$REF..."
curl -fsSL "$URL" -o "$TMP/source.tgz"
tar -xzf "$TMP/source.tgz" -C "$TMP"

SRC="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
npm install -g "$SRC"

echo "StreamingCLI installed. Run: streamingcli"
