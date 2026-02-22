#!/bin/sh
# reset-console.sh — Restore DRI/console ownership after kiosk exits.
# Counterpart to xenodm's TakeConsole. Called by rc.d rc_post() (Step 16).

set -eu

# Restore DRI device ownership to root:wheel
for dev in /dev/dri/card0 /dev/dri/renderD128; do
    [ -e "${dev}" ] && chown root:wheel "${dev}"
done

# Restore console ownership
[ -e /dev/console ] && chown root:wheel /dev/console
