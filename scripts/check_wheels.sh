#!/usr/bin/env bash
# Check that pyipp, pypdfium2 and Pillow have prebuilt musl (Alpine) wheels,
# which is what Home Assistant OS / the HA container images use.
#
# Preferred: try a real install inside python:<ver>-alpine via Docker.
# Fallback (no usable Docker): `pip download --only-binary=:all:` for the
# musllinux platform tags on amd64 and aarch64.
#
# Usage: scripts/check_wheels.sh [python-version]   (default 3.13)
set -u

PYVER="${1:-3.13}"
PKGS=(pyipp pypdfium2 Pillow)
status=0

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "== Docker: pip install in python:${PYVER}-alpine =="
  for pkg in "${PKGS[@]}"; do
    if docker run --rm "python:${PYVER}-alpine" \
        pip install --quiet --only-binary=:all: "$pkg" >/dev/null 2>&1; then
      echo "OK   $pkg"
    else
      echo "FAIL $pkg"; status=1
    fi
  done
  exit $status
fi

echo "== Docker unavailable: pip download fallback (python ${PYVER}) =="
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
for arch in x86_64 aarch64; do
  for pkg in "${PKGS[@]}"; do
    if python3 -m pip download --quiet --no-deps --only-binary=:all: \
        --platform "musllinux_1_2_${arch}" --python-version "$PYVER" \
        -d "$tmp/$arch" "$pkg" >"$tmp/log" 2>&1; then
      echo "OK   $arch $pkg ($(ls "$tmp/$arch" | grep -i "^${pkg//-/_}" | head -1))"
    else
      echo "FAIL $arch $pkg"; status=1
    fi
  done
done
exit $status
