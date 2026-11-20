#!/usr/bin/env bash
# Build IDEmu's OMAP5 QEMU on Linux without modifying an existing QEMU checkout.
# The source/build directory defaults to ~/idemu-qemu; override QEMU_BUILD_DIR or QEMU_JOBS as needed.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
W=${QEMU_BUILD_DIR:-$HOME/idemu-qemu}
TAR=$W/qemu-11.1.2.tar.xz
SRC=$W/qemu-11.1.2
BUILD=$W/build-arm
mkdir -p "$W"
if [[ ! -f $TAR ]]; then
  curl -fL --retry 5 --connect-timeout 30 https://download.qemu.org/qemu-11.1.2.tar.xz -o "$TAR.tmp"
  mv "$TAR.tmp" "$TAR"
fi
if [[ ! -d $SRC ]]; then
  tar -C "$W" -xf "$TAR"
fi
cp "$ROOT/src/qemu/omap5-uevm.c" "$SRC/hw/arm/omap5-uevm.c"
if ! grep -q 'config OMAP5_UEVM' "$SRC/hw/arm/Kconfig"; then
  patch -d "$SRC" -p1 < "$ROOT/src/qemu/qemu-v11.1.2-idemu.patch"
fi
# OMAP5430 DSS/DMM and SDMA models (from bimmulator), used only when QEMU runs with IDEMU_DSS=1 ("real_graphics" environments)
cp "$ROOT/src/qemu/omap5430_dss.c" "$ROOT/src/qemu/omap5430_dss.h" "$SRC/hw/display/"
cp "$ROOT/src/qemu/omap5430_sdma.c" "$ROOT/src/qemu/omap5430_sdma.h" "$SRC/hw/dma/"
grep -q omap5430_dss "$SRC/hw/display/meson.build" || echo "system_ss.add(when: 'CONFIG_OMAP5_UEVM', if_true: files('omap5430_dss.c'))" >> "$SRC/hw/display/meson.build"
grep -q omap5430_sdma "$SRC/hw/dma/meson.build" || echo "system_ss.add(when: 'CONFIG_OMAP5_UEVM', if_true: files('omap5430_sdma.c'))" >> "$SRC/hw/dma/meson.build"
mkdir -p "$BUILD"
cd "$BUILD"
if [[ ! -f build.ninja ]]; then
  "$SRC/configure" \
    --target-list=arm-softmmu \
    --without-default-features \
    --enable-tcg \
    --disable-docs \
    --disable-werror \
    --disable-tools \
    --disable-guest-agent \
    --disable-rust
fi
ninja -j"${QEMU_JOBS:-4}" qemu-system-arm
mkdir -p "$ROOT/bin"
cp "$BUILD/qemu-system-arm" "$ROOT/bin/qemu-system-arm.new"
mv "$ROOT/bin/qemu-system-arm.new" "$ROOT/bin/qemu-system-arm"
"$ROOT/bin/qemu-system-arm" -machine help | grep -F omap5-uevm
