#!/bin/bash
cd "$(dirname "$0")"
APP="$(cd "$(dirname "$0")" && pwd)/Hera/Scripts/hera.py"
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$APP"
fi
if command -v python >/dev/null 2>&1; then
  exec python "$APP"
fi
echo "Python 3 is not installed or not on PATH."
read -r -p "Press Return to close..."
exit 1
