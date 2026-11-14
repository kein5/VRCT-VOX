#!/bin/bash
# Runs inside a clean distribution container as root: install a VRCT-VOX deb or rpm with the
# distribution's own tool, check what it installed and that the bundled programs start, then
# remove it. Recommended packages are left out, so only the declared requirements are present.
#   check_linux_package.sh /packages/VRCT-VOX-<version>-<variant>-release.deb
set -euo pipefail
package=$1
kind=${package##*.}
case "$kind" in
    deb)
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        apt-get install -y -qq --no-install-recommends "$package" > /dev/null
        ;;
    rpm)
        dnf install -y -q --setopt=install_weak_deps=False "$package" > /dev/null
        ;;
    *)
        echo "unknown package format: $package" >&2
        exit 2
        ;;
esac
test -x /usr/bin/vrct-vox
test -f /usr/share/applications/vrct-vox.desktop
test -f /usr/share/icons/hicolor/256x256/apps/vrct-vox.png
test "$(cat /opt/vrct-vox/package-manager)" = "$kind"
# The GUI binary's libraries all resolve from the declared requirements.
missing=$(ldd /opt/vrct-vox/vrct-vox | grep 'not found' || true)
if [ -n "$missing" ]; then
    echo "$missing" >&2
    exit 1
fi
# The bundled speech engine and the frozen backend start.
/opt/vrct-vox/_internal/build/speechcpp/speech --help > /dev/null
result=$(HOME=$(mktemp -d) /opt/vrct-vox/vrct-vox-sidecar --self-check 2>&1 | tail -n 1)
if [ "$result" != "self-check passed" ]; then
    echo "self-check: $result" >&2
    exit 1
fi
# The installed tree is the package's: removing it leaves nothing behind.
case "$kind" in
    deb) apt-get remove -y -qq vrct-vox > /dev/null ;;
    rpm) dnf remove -y -q vrct-vox > /dev/null ;;
esac
test ! -e /opt/vrct-vox
test ! -e /usr/bin/vrct-vox
echo "package check passed: $(basename "$package") in $(. /etc/os-release && echo "$PRETTY_NAME")"
