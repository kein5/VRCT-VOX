#!/usr/bin/env bash
# Build the tested PipeWire API in an isolated CI prefix. Never start services.
set -euo pipefail

if [[ $# != 1 || -z "$1" || "$1" == *$'\n'* ]]; then
    echo 'usage: bash tools/ci/setup_pipewire.sh NEW_ABSOLUTE_DIRECTORY' >&2
    exit 2
fi
destination="$1"
if [[ "$destination" != /* || -e "$destination" || -L "$destination" ]]; then
    echo 'The isolated build destination must be absolute and must not exist.' >&2
    exit 2
fi
mkdir -m 700 -- "$destination"
version=1.6.10
sha256=93b7c4f1e62fd9ec3a921846c6bfc64442872bb2366c2bbc3ea69a427b79a4f9
curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
    --retry 3 --max-time 120 \
    "https://codeload.github.com/PipeWire/pipewire/tar.gz/refs/tags/$version" \
    --output "$destination/source.tar.gz"
printf '%s  %s\n' "$sha256" "$destination/source.tar.gz" | sha256sum --check --status
mkdir "$destination/source"
tar -xf "$destination/source.tar.gz" --strip-components=1 --no-same-owner -C "$destination/source"
prefix="$destination/prefix"
meson setup "$destination/build" "$destination/source" \
    --prefix="$prefix" --libdir=lib --buildtype=release --wrap-mode=nodownload \
    -Dauto_features=disabled -Ddbus=disabled -Dflatpak=disabled \
    -Dsession-managers=[] -Dexamples=disabled -Dtests=disabled \
    -Dpipewire-jack=disabled -Dpipewire-v4l2=disabled \
    -Dsystemd-user-service=disabled -Dsystemd-system-service=disabled \
    -Drlimits-install=false -Dpw-cat=enabled -Dsndfile=enabled
meson compile -C "$destination/build" -j 2
meson install -C "$destination/build" --no-rebuild

# The isolated policy-only fixture uses WirePlumber 0.5's --profile option;
# Ubuntu 24.04's 0.4 daemon/configuration cannot substitute for it.
wp_version=0.5.18
wp_sha256=8c8a326a5b2a570681c1503c83f1fce0cc54ba862019815604b2bc92a7d483a1
curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
    --retry 3 --max-time 120 \
    "https://codeload.github.com/PipeWire/wireplumber/tar.gz/refs/tags/$wp_version" \
    --output "$destination/wireplumber.tar.gz"
printf '%s  %s\n' "$wp_sha256" "$destination/wireplumber.tar.gz" | sha256sum --check --status
mkdir "$destination/wireplumber-source"
tar -xf "$destination/wireplumber.tar.gz" --strip-components=1 --no-same-owner -C "$destination/wireplumber-source"
PKG_CONFIG_PATH="$prefix/lib/pkgconfig" meson setup "$destination/wireplumber-build" "$destination/wireplumber-source" \
    --prefix="$prefix" --libdir=lib --buildtype=release --wrap-mode=nodownload \
    -Dauto_features=disabled -Dtests=false -Ddbus-tests=false \
    -Dsystemd-user-service=false -Dsystem-lua=true -Dsystem-lua-version=5.4
meson compile -C "$destination/wireplumber-build" -j 2
meson install -C "$destination/wireplumber-build" --no-rebuild

# GitHub Actions reads these only in subsequent steps. Headers, tools, client
# libraries, modules and SPA plugins must all come from the same installation.
cat > "$destination/environment" <<EOF
PKG_CONFIG_PATH=$prefix/lib/pkgconfig
LD_LIBRARY_PATH=$prefix/lib
PIPEWIRE_MODULE_DIR=$prefix/lib/pipewire-0.3
SPA_PLUGIN_DIR=$prefix/lib/spa-0.2
PIPEWIRE_CONFIG_DIR=$prefix/share/pipewire
WIREPLUMBER_DATA_DIR=$prefix/share/wireplumber
WIREPLUMBER_MODULE_DIR=$prefix/lib/wireplumber-0.5
EOF
PKG_CONFIG_PATH="$prefix/lib/pkgconfig" pkg-config --exact-version="$version" libpipewire-0.3
LD_LIBRARY_PATH="$prefix/lib" "$prefix/bin/pipewire" --version
LD_LIBRARY_PATH="$prefix/lib" "$prefix/bin/wireplumber" --version
printf 'Prepared %s (no services started).\n' "$prefix"
