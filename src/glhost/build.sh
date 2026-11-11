#!/usr/bin/env bash
# Build the host renderer on macOS or Linux.
set -euo pipefail
cd "$(dirname "$0")"
cp ../shim/glops.h ../shim/gen_host.inc ../shim/opnames.inc ../shim/gl_hand_names.inc . 2>/dev/null || true
mkdir -p ../../bin
CC=${CC:-cc}
case "$(uname -s)" in
  Darwin)
    "$CC" -O2 -Wno-everything host.c pngload.c -framework GLUT -framework OpenGL -framework ApplicationServices -framework CoreFoundation -o ../../bin/glhost
    ;;
  Linux)
    "$CC" -std=gnu11 -O2 -Wno-deprecated-declarations -Wno-int-conversion -Wno-pointer-sign -Wno-implicit-function-declaration \
      host.c pngload.c -lglut -lGL -lpng -lm -o ../../bin/glhost
    ;;
  *)
    echo "Unsupported host: $(uname -s)" >&2
    exit 1
    ;;
esac
ls -l ../../bin/glhost
