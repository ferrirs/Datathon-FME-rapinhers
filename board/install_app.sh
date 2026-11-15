#!/usr/bin/env bash
# Install or update the Cangur Tutor App Lab app on the board.
#
#   bash board/install_app.sh          # run it on the board, from the repository folder
#
# It copies into /home/arduino/ArduinoApps/cangur-tutor:
#   - app/cangur-tutor (app.yaml, python/main.py, sketch/)
#   - the page:          tutor_web/               -> assets/
#   - the tutor code:    copilot/ and config.env  -> python/
#   - the problem bank:  data/tutor.db            -> python/data/tutor.db
#   - the images:        data/images/*_<lang>.png -> assets/img/
#
# App Lab runs the app's Python in a container that only sees the app folder,
# so everything it needs is copied in. Stop the app and run this again after you
# change the code or rebuild the bank. Students and their history live in the
# app's copy of tutor.db, and they are kept.
#
# Then start the app in App Lab, or:
#   arduino-app-cli app start user:cangur-tutor
#   arduino-app-cli app logs /home/arduino/ArduinoApps/cangur-tutor --all
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="${APP_DIR:-/home/arduino/ArduinoApps/cangur-tutor}"
LANGUAGE="$(grep -E '^TUTOR_LANGUAGE=' "$REPO/config.env" 2>/dev/null | cut -d= -f2 || true)"
LANGUAGE="${TUTOR_LANGUAGE:-${LANGUAGE:-cat}}"

if [ ! -f "$REPO/data/tutor.db" ]; then
  echo "No data/tutor.db yet. Build it first: python3 tutor_build.py all" >&2
  exit 1
fi

echo "Installing into $APP"
mkdir -p "$APP/python/data" "$APP/assets/img" "$APP/sketch"
cp "$REPO/app/cangur-tutor/app.yaml" "$APP/"
cp "$REPO/app/cangur-tutor/python/main.py" "$APP/python/"
cp "$REPO/app/cangur-tutor/sketch/sketch.ino" "$REPO/app/cangur-tutor/sketch/sketch.yaml" "$APP/sketch/"
cp -r "$REPO/tutor_web/." "$APP/assets/"
cp "$REPO/config.env" "$APP/python/"
rm -rf "$APP/python/copilot"
cp -r "$REPO/copilot" "$APP/python/copilot"
find "$APP/python/copilot" -name __pycache__ -prune -exec rm -rf {} +

# The new bank goes in, and the students who already practised on the app stay
students="$(cd "$REPO" && python3 -c "
import sys
from copilot.tutor.db import connect, copy_bank, is_current
if not is_current(connect(sys.argv[1])):
    sys.exit('data/tutor.db was built by an older version. Run: python3 tutor_build.py all')
print(copy_bank(sys.argv[1], sys.argv[2]))" "$REPO/data/tutor.db" "$APP/python/data/tutor.db")"
echo "  problem bank installed, $students students in the app"

if [ -d "$REPO/data/images" ]; then
  count=0
  for image in "$REPO"/data/images/*_"$LANGUAGE".png; do
    [ -e "$image" ] || continue
    cp -u "$image" "$APP/assets/img/"
    count=$((count + 1))
  done
  echo "  $count images in '$LANGUAGE' copied"
else
  echo "  no data/images: problems without OCR options won't be shown"
fi

echo
echo "Done. Start it in App Lab, or: arduino-app-cli app start user:cangur-tutor"
echo "If it was already running, stop it and start it again."
echo "Then open http://<board-ip>:7000, or over USB: adb forward tcp:7000 tcp:7000"
echo "The app folder holds M3Kang data: never commit it."
