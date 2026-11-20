#!/usr/bin/env bash
# Build idemu/realgfx/hmimirror (QNX 6.5, ARMv7) from hmimirror.c.
# Needs a QNX 6.5 ARM cross GCC; by default the Docker image of https://github.com/luka-dev/qnx65-armv7-toolchain
# (GCC 4.9.4, arm-unknown-nto-qnx6.5.0eabi), built there with `host-scripts/qnx-run.sh build 4.9`.
# Usage: src/realgfx/build.sh            (Docker image: QNX_IMAGE, default qnx65-armv7-toolchain:4.9)
#        QNX_GCC=<path to arm-unknown-nto-qnx6.5.0eabi-gcc> src/realgfx/build.sh      (a local toolchain instead)
# libscreen is loaded at run time with dlopen, so only the toolchain's own libc headers and libraries are used.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
FLAGS="-std=gnu99 -O2 -Wall -Wextra -s"
if [[ -n ${QNX_GCC:-} ]]; then
  "$QNX_GCC" $FLAGS -o "$ROOT/idemu/realgfx/hmimirror" "$HERE/hmimirror.c"
else
  docker run --rm --platform=linux/amd64 -v "$HERE:/src:ro" -v "$ROOT/idemu/realgfx:/out" -w /src "${QNX_IMAGE:-qnx65-armv7-toolchain:4.9}" \
    sh -c "arm-unknown-nto-qnx6.5.0eabi-gcc $FLAGS -o /out/hmimirror.new hmimirror.c && mv /out/hmimirror.new /out/hmimirror"
fi
file "$ROOT/idemu/realgfx/hmimirror" 2>/dev/null || ls -l "$ROOT/idemu/realgfx/hmimirror"
