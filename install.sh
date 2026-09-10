#!/usr/bin/env sh
set -eu

VERSION="${AI_WORKFLOW_VERSION:-2.3.0}"
REPO="Taki7980/ai-workflow-control-plane-v2"
INSTALL_DIR="${AI_WORKFLOW_INSTALL_DIR:-$HOME/.local/bin}"

os="$(uname -s)"
arch="$(uname -m)"
case "$os/$arch" in
  Linux/x86_64|Linux/amd64) suffix="linux-x86_64" ;;
  Darwin/arm64|Darwin/aarch64) suffix="macos-arm64" ;;
  Darwin/x86_64|Darwin/amd64) suffix="macos-x86_64" ;;
  *) echo "Unsupported platform: $os/$arch" >&2; exit 1 ;;
esac

asset="ai-workflow-v${VERSION}-${suffix}"
base="https://github.com/${REPO}/releases/download/v${VERSION}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT INT TERM

curl -fsSL "$base/SHA256SUMS" -o "$tmp/SHA256SUMS"
curl -fsSL "$base/$asset" -o "$tmp/$asset"
expected="$(awk -v file="$asset" '$2 == file {print $1}' "$tmp/SHA256SUMS")"
[ -n "$expected" ] || { echo "No SHA256 checksum found for $asset" >&2; exit 1; }
if command -v sha256sum >/dev/null 2>&1; then
  actual="$(sha256sum "$tmp/$asset" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  actual="$(shasum -a 256 "$tmp/$asset" | awk '{print $1}')"
else
  echo "sha256sum or shasum is required" >&2
  exit 1
fi
[ "$expected" = "$actual" ] || { echo "SHA256 verification failed" >&2; exit 1; }

mkdir -p "$INSTALL_DIR"
install -m 0755 "$tmp/$asset" "$INSTALL_DIR/ai-workflow"
echo "Installed $INSTALL_DIR/ai-workflow"
