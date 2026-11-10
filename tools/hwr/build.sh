#!/bin/zsh
# Builds bin/hwr (tools/hwr/hwr.m): handwriting -> characters with macOS Vision, for the iDrive Touch Controller (idemu/hwr.py).
# idemu/hwr.py runs this on first use. Where Vision is missing (not macOS, no clang, no SDK with Vision.framework) nothing is built
# and the script exits 0 after saying why: the touchpad still works, only the handwritten characters are not recognised.
cd "$(dirname "$0")/../.."
skip() { echo "hwr: not built: $1 (handwriting needs macOS Vision)"; exit 0; }
[ "$(uname -s)" = Darwin ] || skip "not macOS"
command -v clang >/dev/null 2>&1 || skip "no clang (install the Xcode command line tools: xcode-select --install)"
SDK=$(xcrun --show-sdk-path 2>/dev/null)
[ -n "$SDK" ] && [ -d "$SDK/System/Library/Frameworks/Vision.framework" ] || skip "the macOS SDK has no Vision.framework"
set -e
mkdir -p bin
clang -fobjc-arc -fmodules -mmacosx-version-min=14.0 -framework Foundation -framework Vision -framework CoreGraphics -framework ImageIO \
      tools/hwr/hwr.m -o bin/hwr.tmp
mv bin/hwr.tmp bin/hwr
echo "built bin/hwr"
