#!/bin/sh
# Per-user install of the VMware dual-monitor watcher. No root needed.
# Usage: ./install.sh xfce | kde-wayland | uninstall
set -eu

cd "$(dirname "$0")"
BIN="$HOME/.local/bin"
AUTOSTART="$HOME/.config/autostart"

desktop_entry() {  # name exec extra-line
    cat > "$AUTOSTART/$1.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$1
Exec=$2
TryExec=$2
NoDisplay=true
$3
EOF
}

start() {
    setsid --fork "$1" </dev/null >/dev/null 2>&1
}

mkdir -p "$BIN" "$AUTOSTART"

case "${1:-}" in
xfce)
    install -m 755 xfce/vmware-monitor-layout "$BIN/"
    desktop_entry vmware-monitor-layout "$BIN/vmware-monitor-layout" "OnlyShowIn=XFCE;"
    # Hide Kali's xautoresize for this user only; it collapses extended layouts.
    printf '[Desktop Entry]\nType=Application\nName=Xautoresize\nHidden=true\n' \
        > "$AUTOSTART/xautoresize.desktop"
    pkill -u "$(id -u)" -x xautoresize || true
    start "$BIN/vmware-monitor-layout"
    ;;
kde-wayland)
    command -v drm_info >/dev/null || { echo "Install drm-info first: sudo apt install drm-info" >&2; exit 1; }
    install -m 755 kde-wayland/vmware-monitor-wayland "$BIN/"
    desktop_entry vmware-monitor-wayland "$BIN/vmware-monitor-wayland" "X-KDE-autostart-phase=2"
    start "$BIN/vmware-monitor-wayland"
    ;;
uninstall)
    pkill -u "$(id -u)" -f "$BIN/vmware-monitor-" || true
    rm -f "$BIN/vmware-monitor-layout" "$BIN/vmware-monitor-wayland" \
        "$AUTOSTART/vmware-monitor-layout.desktop" "$AUTOSTART/vmware-monitor-wayland.desktop"
    if grep -qx 'Name=Xautoresize' "$AUTOSTART/xautoresize.desktop" 2>/dev/null; then
        rm -f "$AUTOSTART/xautoresize.desktop"
    fi
    echo "Removed. Log out and back in to restore the stock xautoresize helper."
    ;;
*)
    echo "Usage: $0 xfce | kde-wayland | uninstall" >&2
    exit 2
    ;;
esac
