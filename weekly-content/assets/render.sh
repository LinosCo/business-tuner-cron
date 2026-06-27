#!/usr/bin/env bash
# Render un file HTML in PNG via Chrome headless (stile sito Voler.ai).
# Uso: render.sh <input.html> <output.png> [WxH]   (default 1080x1350)
set -euo pipefail

IN="${1:?serve input.html}"
OUT="${2:?serve output.png}"
SIZE="${3:-1080x1350}"
W="${SIZE%x*}"; H="${SIZE#*x}"

# Trova Chrome/Chromium cross-platform (macOS locale + Linux GitHub Actions)
CHROME="${CHROME_BIN:-}"
if [ -z "$CHROME" ] || [ ! -x "$CHROME" ]; then
  for c in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome Canary" \
    "$(command -v google-chrome-stable 2>/dev/null)" \
    "$(command -v google-chrome 2>/dev/null)" \
    "$(command -v chromium-browser 2>/dev/null)" \
    "$(command -v chromium 2>/dev/null)"; do
    if [ -n "$c" ] && [ -x "$c" ]; then CHROME="$c"; break; fi
  done
fi
[ -n "$CHROME" ] && [ -x "$CHROME" ] || { echo "Chrome/Chromium non trovato"; exit 1; }

# percorso assoluto per file:// (i font Google e i logo accanto all'HTML si caricano da soli)
case "$IN" in /*) ABS="$IN";; *) ABS="$PWD/$IN";; esac

"$CHROME" --headless --disable-gpu --hide-scrollbars --no-sandbox \
  --force-device-scale-factor=1 --default-background-color=00000000 \
  --virtual-time-budget=3500 \
  --window-size="$W,$H" \
  --screenshot="$OUT" \
  "file://$ABS" >/dev/null 2>&1

[ -f "$OUT" ] && echo "OK -> $OUT (${W}x${H})" || { echo "FALLITO: nessun PNG generato"; exit 1; }
