#!/bin/zsh
# Builds bin/hwr (tools/hwr/hwr.m): handwriting -> characters with macOS Vision, for the iDrive Touch Controller (idemu/hwr.py).
set -e
cd "$(dirname "$0")/../.."
mkdir -p bin
clang -fobjc-arc -fmodules -mmacosx-version-min=14.0 -framework Foundation -framework Vision -framework CoreGraphics -framework ImageIO \
      -framework AppKit tools/hwr/hwr.m -o bin/hwr
echo "built bin/hwr"
