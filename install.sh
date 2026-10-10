#!/bin/sh
# Install the desktop entry and icon for the current user only.
# Does not copy the program, does not need root, does not touch system dirs.
set -e
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
APP_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"
DESKTOP="$APP_DIR/sherlock.desktop"

mkdir -p "$APP_DIR" "$ICON_DIR"
sed "s|@ROOT@|$ROOT|g" "$ROOT/data/sherlock.desktop.in" > "$DESKTOP"
cp "$ROOT/data/sherlock.svg" "$ICON_DIR/sherlock.svg"
chmod 644 "$DESKTOP" "$ICON_DIR/sherlock.svg"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APP_DIR" || true
fi
if command -v gtk4-update-icon-cache >/dev/null 2>&1; then
    gtk4-update-icon-cache -f -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
elif command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "Installed $DESKTOP"
echo "Icon: $ICON_DIR/sherlock.svg"
echo "The launcher runs $ROOT/run.sh (leave this directory where it is)."
