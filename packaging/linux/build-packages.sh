#!/usr/bin/env bash
# Build Linux packages for Sherlock into ./release/.
#
#   packaging/linux/build-packages.sh          # .deb and .rpm (whichever tools exist)
#   packaging/linux/build-packages.sh deb      # only the .deb (needs dpkg-deb)
#   packaging/linux/build-packages.sh rpm      # only the .rpm (needs rpmbuild)
#
# Packages are named "sherlock-search" (command: sherlock-search) because
# Debian/Ubuntu already ship an unrelated "sherlock" package.
# The version comes from sherlock/__init__.py. In CI, RELEASE_TAG (e.g. v1.0.0)
# must match it, so a tag can never ship a package with the wrong version.
set -euo pipefail

MODULE=sherlock
PKG=sherlock-search
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$MODULE/__init__.py")"
if [[ -z "$VERSION" ]]; then
  echo "Could not read __version__ from $MODULE/__init__.py" >&2
  exit 1
fi
if [[ -n "${RELEASE_TAG:-}" && "${RELEASE_TAG#v}" != "$VERSION" ]]; then
  echo "Tag $RELEASE_TAG does not match __version__ $VERSION in $MODULE/__init__.py" >&2
  exit 1
fi
if ! grep -q "<release version=\"$VERSION\"" data/$PKG.metainfo.xml; then
  echo "Add <release version=\"$VERSION\" date=\"YYYY-MM-DD\"/> to data/$PKG.metainfo.xml" >&2
  exit 1
fi

want=("$@")
if [[ ${#want[@]} -eq 0 ]]; then
  command -v dpkg-deb >/dev/null && want+=(deb)
  command -v rpmbuild >/dev/null && want+=(rpm)
fi
if [[ ${#want[@]} -eq 0 ]]; then
  echo "Neither dpkg-deb nor rpmbuild is installed." >&2
  exit 1
fi

OUT="$ROOT/release"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$OUT"

build_deb() {
  local stage="$WORK/deb"
  install -d "$stage/DEBIAN" "$stage/usr/share/$PKG" "$stage/usr/share/doc/$PKG"
  cp -a "$MODULE" "$stage/usr/share/$PKG/$MODULE"
  find "$stage/usr/share/$PKG" -name '__pycache__' -prune -exec rm -rf {} +
  install -Dm0755 packaging/linux/$PKG.sh "$stage/usr/bin/$PKG"
  install -Dm0644 data/$PKG.desktop "$stage/usr/share/applications/$PKG.desktop"
  install -Dm0644 data/sherlock.svg "$stage/usr/share/icons/hicolor/scalable/apps/$PKG.svg"
  install -Dm0644 data/$PKG.metainfo.xml "$stage/usr/share/metainfo/$PKG.metainfo.xml"
  install -m0644 README.md "$stage/usr/share/doc/$PKG/README.md"
  install -m0644 LICENSE "$stage/usr/share/doc/$PKG/copyright"

  local size
  size="$(du -sk --exclude=DEBIAN "$stage" | cut -f1)"
  sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$size/" packaging/linux/debian-control.in \
    > "$stage/DEBIAN/control"
  printf '%s\n' '#!/bin/sh' 'set -e' \
    "if command -v py3compile >/dev/null 2>&1; then py3compile /usr/share/$PKG/$MODULE || true; fi" \
    > "$stage/DEBIAN/postinst"
  printf '%s\n' '#!/bin/sh' 'set -e' \
    "if command -v py3clean >/dev/null 2>&1; then py3clean /usr/share/$PKG/$MODULE || true; fi" \
    "find /usr/share/$PKG -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true" \
    > "$stage/DEBIAN/prerm"
  chmod 0755 "$stage/DEBIAN/postinst" "$stage/DEBIAN/prerm"

  local deb="$OUT/${PKG}_${VERSION}-1_all.deb"
  dpkg-deb --root-owner-group -Zxz --build "$stage" "$deb" >/dev/null
  echo "Built $deb"
}

build_rpm() {
  local top="$WORK/rpm" name="$PKG-$VERSION"
  mkdir -p "$top"/{SOURCES,SPECS,BUILD,RPMS,SRPMS} "$WORK/src/$name"
  cp -a "$MODULE" data README.md LICENSE "$WORK/src/$name/"
  install -Dm0755 packaging/linux/$PKG.sh "$WORK/src/$name/packaging/linux/$PKG.sh"
  find "$WORK/src/$name" -name '__pycache__' -prune -exec rm -rf {} +
  tar -C "$WORK/src" -czf "$top/SOURCES/$name.tar.gz" "$name"

  local date
  date="$(LC_ALL=C date -u +'%a %b %d %Y')"
  sed -e "s/@VERSION@/$VERSION/g" -e "s/@DATE@/$date/" packaging/linux/$PKG.spec.in \
    > "$top/SPECS/$PKG.spec"

  local nodeps=()
  # On a non-RPM system (e.g. Ubuntu) the build dependencies cannot be checked.
  [[ -f /etc/redhat-release || -f /etc/fedora-release ]] || nodeps=(--nodeps)
  rpmbuild -bb "${nodeps[@]}" --define "_topdir $top" "$top/SPECS/$PKG.spec" >"$WORK/rpmbuild.log" 2>&1 || {
    cat "$WORK/rpmbuild.log" >&2
    exit 1
  }
  local rpm
  for rpm in "$top"/RPMS/*/*.rpm; do
    cp "$rpm" "$OUT/"
    echo "Built $OUT/$(basename "$rpm")"
  done
}

for kind in "${want[@]}"; do
  case "$kind" in
    deb) build_deb ;;
    rpm) build_rpm ;;
    *) echo "Unknown package type: $kind (use deb or rpm)" >&2; exit 1 ;;
  esac
done
