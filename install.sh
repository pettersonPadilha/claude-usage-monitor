#!/usr/bin/env bash
# Installs the desktop entry (and optionally autostart) for the current user.
# Nothing is copied: the entries point at this directory.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXEC="${HERE}/claude-usage-monitor"
TEMPLATE="${HERE}/claude-usage-monitor.desktop"
APPS_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/applications"
ICONS_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/icons/hicolor"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/autostart"

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

  --autostart       also start the monitor on login
  --with-indicator  install the panel indicator library (uses sudo apt)
  --uninstall       remove the entries created by this script
  -h, --help        show this help
EOF
}

AUTOSTART=0
INDICATOR=0
UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --autostart) AUTOSTART=1 ;;
    --with-indicator) INDICATOR=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage; exit 1 ;;
  esac
done

if [[ "$UNINSTALL" == "1" ]]; then
  rm -f "${APPS_DIR}/claude-usage-monitor.desktop" \
        "${AUTOSTART_DIR}/claude-usage-monitor.desktop"
  rm -f "${ICONS_DIR}"/*/apps/claude-usage-monitor.png \
        "${ICONS_DIR}"/scalable/apps/claude-usage-monitor.svg
  gtk-update-icon-cache -f -t "$ICONS_DIR" >/dev/null 2>&1 || true
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
  echo "Removed desktop entry, autostart entry and icons."
  exit 0
fi

if [[ "$INDICATOR" == "1" ]]; then
  echo "Installing the panel indicator library (requires sudo)…"
  sudo apt install -y gir1.2-ayatanaappindicator3-0.1
fi

chmod +x "$EXEC"

# Icons: copy every generated size into the user's hicolor theme so the app
# grid, the dock and the window list all find a proper icon.
if [[ -d "${HERE}/icons" ]]; then
  for dir in "${HERE}"/icons/*/; do
    size="$(basename "$dir")"
    target="${ICONS_DIR}/${size}/apps"
    mkdir -p "$target"
    cp "${dir}"claude-usage-monitor.* "$target/"
  done
  gtk-update-icon-cache -f -t "$ICONS_DIR" >/dev/null 2>&1 || true
  echo "Installed icons into ${ICONS_DIR}"
fi

mkdir -p "$APPS_DIR"
sed "s|__EXEC__|${EXEC}|" "$TEMPLATE" > "${APPS_DIR}/claude-usage-monitor.desktop"
chmod +x "${APPS_DIR}/claude-usage-monitor.desktop"
update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
echo "Installed ${APPS_DIR}/claude-usage-monitor.desktop"

if [[ "$AUTOSTART" == "1" ]]; then
  mkdir -p "$AUTOSTART_DIR"
  sed "s|__EXEC__|${EXEC}|" "$TEMPLATE" \
    > "${AUTOSTART_DIR}/claude-usage-monitor.desktop"
  echo "Installed ${AUTOSTART_DIR}/claude-usage-monitor.desktop"
fi

echo "Done. Launch it with: ${EXEC}"
