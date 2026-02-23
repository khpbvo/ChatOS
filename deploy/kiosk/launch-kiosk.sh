#!/bin/sh
# launch-kiosk.sh — Start X11 + Chromium kiosk for ChatOS.
# Must run as root. Called by the rc.d service (Step 16).
#
# Flow:
#   1. Load config for display/vt values
#   2. Grant GPU/DRI access to _chatos_ui
#   3. Ensure runtime directories exist
#   4. Set Chromium resource limits
#   5. Start xinit as root (X server needs console access)
#      Chromium is dropped to _chatos_ui inside xinitrc via doas

set -eu

# Log launch-kiosk errors (xinitrc has its own log, but X failures happen before it)
LAUNCH_LOG="/var/chatos/logs/launch-kiosk.log"
exec >>"${LAUNCH_LOG}" 2>&1
echo "--- launch-kiosk start: $(date) ---"

CHATOS_DIR="/usr/local/share/chatos"
PYTHON="${CHATOS_DIR}/venv/bin/python"
KIOSK_CONF="/etc/chatos/kiosk.conf"
XINITRC="${CHATOS_DIR}/deploy/kiosk/xinitrc"

# Must be in app dir for `python -m src.*` to find the package
cd "${CHATOS_DIR}"

# Load kiosk config
eval "$("${PYTHON}" -m src.kiosk_config "${KIOSK_CONF}")"

# Grant GPU access to _chatos_ui (replicates xenodm GiveConsole)
for dev in /dev/dri/card0 /dev/dri/renderD128; do
    [ -e "${dev}" ] && chown _chatos_ui "${dev}"
done

# Ensure runtime directories (Chrome uses $HOME/.config/chromium as profile)
mkdir -p "${KIOSK_CHROMIUM_DATA_DIR}/.config/chromium"
chown -R _chatos_ui "${KIOSK_CHROMIUM_DATA_DIR}"
mkdir -p "$(dirname "${KIOSK_LOG_FILE}")"

# Chromium resource limits (matches /usr/local/bin/chrome wrapper)
ulimit -Sd 716800
ulimit -Sn 400

# X server needs VT_SETMODE which requires a controlling terminal.
# rc.d starts us detached, so we use vt-launch.py to call setsid()
# and acquire the target wscons VT before exec'ing xinit.
# X vt numbers are 1-based, ttyC devices are 0-based (vt05 = ttyC4)
_vt_num=$(echo "${KIOSK_VT#vt}" | sed 's/^0*//')
_tty_num=$((_vt_num - 1))
_tty="/dev/ttyC${_tty_num}"

echo "Launching xinit on ${_tty} (${KIOSK_DISPLAY} ${KIOSK_VT})"
exec "${PYTHON}" "${CHATOS_DIR}/deploy/kiosk/vt-launch.py" "${_tty}" \
    xinit "${XINITRC}" -- "${KIOSK_DISPLAY}" "${KIOSK_VT}"
