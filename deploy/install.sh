#!/bin/bash
# install.sh — Transform a fresh Ubuntu machine into a ChatOS kiosk.
#
# Usage:  sudo bash deploy/install.sh
#
# Idempotent — safe to re-run for upgrades. Existing config files in
# /etc/chatos/ are preserved (never overwritten). systemd units and
# application code are always updated.

set -eu

# ---------------------------------------------------------------------------
# Section 2: Constants
# ---------------------------------------------------------------------------

CHATOS_APP="/usr/local/share/chatos"
CHATOS_ETC="/etc/chatos"
CHATOS_VAR="/var/chatos"
CHATOS_USER="_chatos"
CHATOS_UI_USER="_chatos_ui"
PACKAGES="python3 python3-pip python3-venv nodejs npm chromium-browser"
OPT_PACKAGES="unclutter"

# Resolve project directory from this script's location
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd -P)
PROJECT_DIR=$(cd "${SCRIPT_DIR}/.." && pwd -P)

# ---------------------------------------------------------------------------
# Section 3: Helpers
# ---------------------------------------------------------------------------

info() {
    echo ">>> $*"
}

warn() {
    echo "!!! $*" >&2
}

die() {
    echo "FATAL: $*" >&2
    exit 1
}

ensure_user() {
    _name="$1"
    _home="${2:-/nonexistent}"
    if id -u "$_name" >/dev/null 2>&1; then
        info "User $_name already exists"
        return 0
    fi
    info "Creating group $_name"
    groupadd "$_name"
    info "Creating user $_name (home: $_home)"
    useradd -g "$_name" -s /usr/sbin/nologin -d "$_home" -M "$_name"
}

ensure_dir() {
    _dir="$1"
    _owner="$2"
    _mode="$3"
    mkdir -p "$_dir"
    chown "$_owner" "$_dir"
    chmod "$_mode" "$_dir"
}

install_config() {
    _src="$1"
    _dst="$2"
    _owner="$3"
    _mode="$4"
    if [ -f "$_dst" ]; then
        info "Config $_dst already exists — preserving"
        return 0
    fi
    info "Installing $_dst"
    install -o "${_owner%%:*}" -g "${_owner##*:}" -m "$_mode" "$_src" "$_dst"
}

# ---------------------------------------------------------------------------
# Section 4: Root check
# ---------------------------------------------------------------------------

if [ "$(id -u)" -ne 0 ]; then
    die "This script must be run as root (sudo bash deploy/install.sh)"
fi

# ---------------------------------------------------------------------------
# Section 5: Package installation
# ---------------------------------------------------------------------------

info "Updating package lists"
apt-get update -qq

info "Installing required packages"
apt-get install -y -qq $PACKAGES

for _pkg in $OPT_PACKAGES; do
    apt-get install -y -qq "$_pkg" || warn "Optional package $_pkg not installed (non-fatal)"
done

# ---------------------------------------------------------------------------
# Section 6: Service account creation
# ---------------------------------------------------------------------------

info "Ensuring service accounts"
ensure_user "$CHATOS_USER"
ensure_user "$CHATOS_UI_USER" "/var/chatos/chromium"

# ---------------------------------------------------------------------------
# Section 7: Directory structure
# ---------------------------------------------------------------------------

info "Creating directory structure"
ensure_dir "$CHATOS_ETC"          "root:root"                           "755"
ensure_dir "$CHATOS_VAR"          "root:root"                           "755"
ensure_dir "$CHATOS_VAR/logs"     "${CHATOS_USER}:${CHATOS_USER}"       "750"
ensure_dir "$CHATOS_VAR/run"      "${CHATOS_USER}:${CHATOS_USER}"       "750"
ensure_dir "$CHATOS_VAR/sessions" "${CHATOS_USER}:${CHATOS_USER}"       "750"
ensure_dir "$CHATOS_VAR/chromium" "${CHATOS_UI_USER}:${CHATOS_UI_USER}" "750"

# ---------------------------------------------------------------------------
# Section 8: Application file deployment
# ---------------------------------------------------------------------------

_app_real=$(cd "$CHATOS_APP" 2>/dev/null && pwd -P || echo "")
_proj_real=$(cd "$PROJECT_DIR" && pwd -P)

if [ "$_app_real" = "$_proj_real" ]; then
    info "Project already at ${CHATOS_APP} — skipping copy"
else
    info "Deploying application files to ${CHATOS_APP}"
    mkdir -p "$CHATOS_APP"
    for _item in src ui .claude deploy etc pyproject.toml; do
        cp -R "${PROJECT_DIR}/${_item}" "${CHATOS_APP}/"
    done
fi

# ---------------------------------------------------------------------------
# Section 9: Python venv + pip install
# ---------------------------------------------------------------------------

info "Setting up Python virtual environment"
if [ ! -d "${CHATOS_APP}/venv" ]; then
    python3 -m venv "${CHATOS_APP}/venv"
fi

info "Installing Python dependencies"
"${CHATOS_APP}/venv/bin/pip" install --quiet -e "${CHATOS_APP}"

# ---------------------------------------------------------------------------
# Section 10: UI build
# ---------------------------------------------------------------------------

if [ -f "${CHATOS_APP}/ui/package.json" ]; then
    info "Building web UI"
    cd "${CHATOS_APP}/ui"
    npm ci --ignore-scripts
    npm run build
    cd "${PROJECT_DIR}"
fi

# ---------------------------------------------------------------------------
# Section 11: Set ownership
# ---------------------------------------------------------------------------

info "Setting ownership"
chown -R "${CHATOS_USER}:${CHATOS_USER}" "$CHATOS_APP"

# ---------------------------------------------------------------------------
# Section 12: Config file installation (with preservation)
# ---------------------------------------------------------------------------

info "Installing configuration files"
install_config "${CHATOS_APP}/etc/chatos/rules.toml"  "${CHATOS_ETC}/rules.toml"  "root:${CHATOS_USER}" "640"
install_config "${CHATOS_APP}/etc/chatos/agents.toml" "${CHATOS_ETC}/agents.toml" "root:${CHATOS_USER}" "640"
install_config "${CHATOS_APP}/etc/chatos/kiosk.conf"  "${CHATOS_ETC}/kiosk.conf"  "root:root"           "644"

# Env file for API credentials (read by the Python app at startup)
if [ ! -f "${CHATOS_ETC}/env" ]; then
    info "Creating ${CHATOS_ETC}/env template"
    cat > "${CHATOS_ETC}/env" <<'ENVEOF'
# ChatOS environment — sourced by the agent at startup.
# Set your Anthropic API key here. The _chatos service user
# reads this file; no interactive login or setup-token needed.
#ANTHROPIC_API_KEY=sk-ant-...
ENVEOF
    chown "root:${CHATOS_USER}" "${CHATOS_ETC}/env"
    chmod 640 "${CHATOS_ETC}/env"
else
    info "Config ${CHATOS_ETC}/env already exists — preserving"
fi

# ---------------------------------------------------------------------------
# Section 13: systemd unit installation (always overwrite — code, not config)
# ---------------------------------------------------------------------------

info "Installing systemd service units"
install -o root -g root -m 644 "${CHATOS_APP}/deploy/systemd/chatos-agent.service" /etc/systemd/system/chatos-agent.service
install -o root -g root -m 644 "${CHATOS_APP}/deploy/systemd/chatos-ui.service"    /etc/systemd/system/chatos-ui.service

systemctl daemon-reload

# ---------------------------------------------------------------------------
# Section 14: sudoers.d entry for _chatos_ui
# ---------------------------------------------------------------------------

_sudoers_file="/etc/sudoers.d/chatos-ui"
_sudoers_line="_chatos_ui ALL=(ALL) NOPASSWD: ALL"
if [ -f "$_sudoers_file" ]; then
    info "sudoers entry already configured"
else
    info "Adding _chatos_ui sudoers entry"
    echo "$_sudoers_line" > "$_sudoers_file"
    chmod 440 "$_sudoers_file"
fi

# ---------------------------------------------------------------------------
# Section 15: Service enablement
# ---------------------------------------------------------------------------

info "Enabling services"
systemctl enable chatos-agent.service
systemctl enable chatos-ui.service

# ---------------------------------------------------------------------------
# Section 16: Deploy script permissions
# ---------------------------------------------------------------------------

info "Setting deploy script permissions"
chmod +x "${CHATOS_APP}/deploy/kiosk/launch-kiosk.sh"
chmod +x "${CHATOS_APP}/deploy/kiosk/xinitrc"
chmod +x "${CHATOS_APP}/deploy/kiosk/reset-console.sh"

# ---------------------------------------------------------------------------
# Section 17: Post-install summary
# ---------------------------------------------------------------------------

cat <<'EOF'

============================================================
  ChatOS installation complete!
============================================================

Next steps:

  1. Set your API key (required before first start):
     echo 'ANTHROPIC_API_KEY=sk-ant-...' >> /etc/chatos/env

     The agent reads /etc/chatos/env at startup. No interactive
     login or setup-token needed.

  2. (Optional) Configure email MCP server credentials:
     Edit /etc/chatos/mcp.toml with IMAP/SMTP settings
     chown root:_chatos /etc/chatos/mcp.toml
     chmod 640 /etc/chatos/mcp.toml

  3. Start services:
     sudo systemctl start chatos-agent
     sudo systemctl start chatos-ui

  4. Check logs:
     journalctl -u chatos-agent -f
     tail -f /var/chatos/logs/kiosk.log
     ls /var/chatos/logs/audit-*.jsonl

  5. Stop services:
     sudo systemctl stop chatos-ui
     sudo systemctl stop chatos-agent

============================================================
EOF
