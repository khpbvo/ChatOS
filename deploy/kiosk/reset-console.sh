#!/bin/sh
# reset-console.sh — Restore DRI/console ownership after kiosk exits.
# Called by systemd ExecStopPost.

set -eu

# Restore DRI device ownership to root:root
for dev in /dev/dri/card0 /dev/dri/renderD128; do
    [ -e "${dev}" ] && chown root:root "${dev}"
done

# Restore console ownership
[ -e /dev/console ] && chown root:root /dev/console
