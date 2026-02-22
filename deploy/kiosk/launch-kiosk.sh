#!/bin/sh
# launch-kiosk.sh — Start X11 + Chromium kiosk for ChatOS.
# Must run as root. Called by the rc.d service (Step 16).
#
# Flow:
#   1. Load config for display/vt values
#   2. Grant GPU/DRI access to _chatos_ui
#   3. Ensure runtime directories exist
#   4. Set Chromium resource limits
#   5. Drop privileges via doas and start xinit

set -eu

CHATOS_DIR="/usr/local/share/chatos"
PYTHON="${CHATOS_DIR}/venv/bin/python"
KIOSK_CONF="/etc/chatos/kiosk.conf"
XINITRC="${CHATOS_DIR}/deploy/kiosk/xinitrc"

# Load kiosk config
eval "$("${PYTHON}" -m src.kiosk_config "${KIOSK_CONF}")"

# Grant GPU access to _chatos_ui (replicates xenodm GiveConsole)
for dev in /dev/dri/card0 /dev/dri/renderD128; do
    [ -e "${dev}" ] && chown _chatos_ui "${dev}"
done

# Ensure runtime directories
mkdir -p "${KIOSK_CHROMIUM_DATA_DIR}"
chown _chatos_ui "${KIOSK_CHROMIUM_DATA_DIR}"
mkdir -p "$(dirname "${KIOSK_LOG_FILE}")"

# Chromium resource limits (matches /usr/local/bin/chrome wrapper)
ulimit -Sd 716800
ulimit -Sn 400

# Drop privileges and start X
exec doas -u _chatos_ui \
    xinit "${XINITRC}" -- "${KIOSK_DISPLAY}" "${KIOSK_VT}"
