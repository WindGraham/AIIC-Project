#!/usr/bin/env bash
# Robust tarball downloader for GitHub repos using API default-branch + codeload.
# Usage: fetch_repos.sh <dest_dir> <repo1> <repo2> ...
# Route through local mihomo proxy (mixed-port 7890) to stabilize github access.
export https_proxy="${https_proxy:-http://127.0.0.1:7890}"
export http_proxy="${http_proxy:-http://127.0.0.1:7890}"
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="$https_proxy"
set -u
DEST="$1"; shift
mkdir -p "$DEST"
cd "$DEST"

for r in "$@"; do
  name=$(basename "$r")
  if [ -d "$name" ] && [ -n "$(ls -A "$name" 2>/dev/null)" ] && [ ! -e "$name/.download-fail" ]; then
    echo "SKIP  $r (already present)"
    continue
  fi
  # get default branch
  branch=""
  def=$(timeout 20 curl -sSL "https://api.github.com/repos/$r" 2>/dev/null | grep -m1 '"default_branch"' | sed -E 's/.*: *"([^"]+)".*/\1/')
  [ -n "$def" ] && branch="$def"
  echo "== $r (default=${branch:-?}) =="
  rm -rf "$name" "$name.tar.gz" 2>/dev/null
  ok=0
  for b in "$branch" main master; do
    [ -z "$b" ] && continue
    if timeout 60 curl -sSL -o "$name.tar.gz" -w "" "https://codeload.github.com/$r/tar.gz/refs/heads/$b" 2>/dev/null \
         && [ -s "$name.tar.gz" ] \
         && file "$name.tar.gz" | grep -q gzip; then
      mkdir -p "$name"
      tar -xzf "$name.tar.gz" -C "$name" --strip-components=1 2>/dev/null && ok=1
      break
    fi
  done
  rm -f "$name.tar.gz"
  if [ "$ok" -eq 1 ]; then
    echo "OK    $r -> $name"
  else
    echo "FAIL  $r"
    touch "$name/.download-fail"
  fi
done
echo "ALL_DONE"
