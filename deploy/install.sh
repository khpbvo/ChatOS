#!/bin/ksh
# install.sh — Transform a fresh OpenBSD 7.8 machine into a ChatOS kiosk.
#
# Usage:  doas ksh deploy/install.sh
#
# Idempotent — safe to re-run for upgrades. Existing config files in
# /etc/chatos/ are preserved (never overwritten). rc.d scripts and
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
PACKAGES="python%3.12 py3-pip node chromium"
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
    useradd -g "$_name" -s /sbin/nologin -d "$_home" "$_name"
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
    die "This script must be run as root (doas ksh deploy/install.sh)"
fi

# ---------------------------------------------------------------------------
# Section 5: Package installation
# ---------------------------------------------------------------------------

info "Installing required packages"
pkg_add -I $PACKAGES

for _pkg in $OPT_PACKAGES; do
    pkg_add -I "$_pkg" || warn "Optional package $_pkg not installed (non-fatal)"
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
ensure_dir "$CHATOS_ETC"          "root:wheel"              "755"
ensure_dir "$CHATOS_VAR"          "root:wheel"              "755"
ensure_dir "$CHATOS_VAR/logs"     "${CHATOS_USER}:${CHATOS_USER}"     "750"
ensure_dir "$CHATOS_VAR/run"      "${CHATOS_USER}:${CHATOS_USER}"     "750"
ensure_dir "$CHATOS_VAR/sessions" "${CHATOS_USER}:${CHATOS_USER}"     "750"
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
    python3.12 -m venv "${CHATOS_APP}/venv"
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
install_config "${CHATOS_APP}/etc/chatos/kiosk.conf"  "${CHATOS_ETC}/kiosk.conf"  "root:wheel"          "644"

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
# Section 13: rc.d script installation (always overwrite — code, not config)
# ---------------------------------------------------------------------------

info "Installing rc.d scripts"
install -o root -g wheel -m 755 "${CHATOS_APP}/deploy/rc.d/chatos_agent" /etc/rc.d/chatos_agent
install -o root -g wheel -m 755 "${CHATOS_APP}/deploy/rc.d/chatos_ui"    /etc/rc.d/chatos_ui

# ---------------------------------------------------------------------------
# Section 14: doas.conf update
# ---------------------------------------------------------------------------

_doas_line="permit nopass root as _chatos_ui"
if grep -qF "$_doas_line" /etc/doas.conf 2>/dev/null; then
    info "doas.conf already configured"
else
    info "Adding _chatos_ui rule to /etc/doas.conf"
    echo "$_doas_line" >> /etc/doas.conf
fi

# ---------------------------------------------------------------------------
# Section 15: Service enablement
# ---------------------------------------------------------------------------

info "Enabling services"
rcctl enable chatos_agent
rcctl enable chatos_ui
rcctl set chatos_agent timeout 60
rcctl set chatos_ui timeout 60

# ---------------------------------------------------------------------------
# Section 16: Deploy script permissions
# ---------------------------------------------------------------------------

info "Setting deploy script permissions"
chmod +x "${CHATOS_APP}/deploy/kiosk/launch-kiosk.sh"
chmod +x "${CHATOS_APP}/deploy/kiosk/xinitrc"
chmod +x "${CHATOS_APP}/deploy/kiosk/reset-console.sh"
chmod +x "${CHATOS_APP}/deploy/rc.d/chatos_agent"
chmod +x "${CHATOS_APP}/deploy/rc.d/chatos_ui"

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
     rcctl start chatos_agent
     rcctl start chatos_ui

  4. Check logs:
     tail -f /var/chatos/logs/kiosk.log
     ls /var/chatos/logs/audit-*.jsonl

  5. Stop services:
     rcctl stop chatos_ui
     rcctl stop chatos_agent

============================================================
EOF
