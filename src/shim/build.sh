#!/usr/bin/env bash
# Build guest translation libraries (ARMv7, freestanding) with clang + ld.lld.
# Usage: SHIM_PROFILE=default|1803 ./build.sh <matching-firmware libc.so.3> [python-with-ziglang]
# Optional: IDEMU_SHIM_OUT=<output-directory> CC=clang LLD=ld.lld EXTRA_CF=<extra-flags>
set -euo pipefail
cd "$(dirname "$0")"
if [[ $# -lt 1 ]]; then
  echo "Usage: SHIM_PROFILE=default|1803 $0 <matching-firmware libc.so.3> [python-with-ziglang]" >&2
  exit 2
fi
LIBC=$1
PY=${2:-python3}
[[ -f $LIBC ]] || { echo "Firmware libc not found: $LIBC" >&2; exit 1; }
DEFAULT_OUT=../../idemu/shim/lib
PROFILE=${SHIM_PROFILE:-default}
case "$PROFILE" in
  default)
    PROFILE_CF=()
    PROFILE_OUT=$DEFAULT_OUT
    ;;
  1803)
    PROFILE_CF=(-DHMI_PROFILE_1803=1)
    PROFILE_OUT=../../idemu/shim/lib-1803
    ;;
  *)
    echo "Unsupported shim profile: $PROFILE" >&2
    exit 2
    ;;
esac
# The profile selector, not an unrelated compiler flag, determines the guest ABI/address profile.
if [[ ${EXTRA_CF:-} == *HMI_PROFILE_1803* ]]; then
  echo "Use SHIM_PROFILE=1803 instead of putting HMI_PROFILE_1803 in EXTRA_CF" >&2
  exit 2
fi
OUT=${IDEMU_SHIM_OUT:-$PROFILE_OUT}
IOIPC=$DEFAULT_OUT/ioipc-idemu.so
[[ -f $IOIPC ]] || { echo "Shared guest component is missing: $IOIPC" >&2; exit 1; }
printf 'Building shim profile %s -> %s\n' "$PROFILE" "$OUT"
mkdir -p lib out "$OUT"
python3 gen.py >/dev/null
rm -f lib/libc.so.3
cp "$LIBC" lib/libc.so.3
CC=${CC:-clang}
CF=(-target armv7-none-eabi -march=armv7-a -mfloat-abi=soft -ffreestanding -fPIC -Os -mno-unaligned-access -Wno-incompatible-library-redeclaration -Wno-builtin-requires-header -Wno-int-conversion -Wno-pointer-sign)
CF+=("${PROFILE_CF[@]}")
if [[ -n ${EXTRA_CF:-} ]]; then
  read -r -a EXTRA <<< "$EXTRA_CF"
  CF+=("${EXTRA[@]}")
fi
if [[ -z ${LLD:-} ]]; then
  LLD=$(command -v ld.lld || true)
fi
if [[ -n ${LLD:-} ]]; then
  LDBIN=("$LLD")
else
  LDBIN=("$PY" -m ziglang ld.lld)
fi
LD=("${LDBIN[@]}" -shared -z max-page-size=4096 -z common-page-size=4096 -z norelro -z noseparate-code --no-rosegment --hash-style=sysv --no-eh-frame-hdr -z nognustack)
for f in bridge gles egl dbg hook; do
  "$CC" "${CF[@]}" -c "$f.c" -o "out/$f.o"
done
"${LD[@]}" -soname libscreen.so.1 -o out/libscreen.so.1 out/bridge.o out/gles.o out/egl.o out/dbg.o out/hook.o -Llib -l:libc.so.3
echo 'int dummy_sym;' > out/empty.c
"$CC" "${CF[@]}" -c out/empty.c -o out/empty.o
"${LD[@]}" -soname libEGL.so.1 -o out/libEGL.so.1 out/empty.o -Llib -l:libc.so.3 -Lout -l:libscreen.so.1
"${LD[@]}" -soname libGLESv2.so.1 -o out/libGLESv2.so.1 out/empty.o -Llib -l:libc.so.3 -Lout -l:libscreen.so.1
"$CC" "${CF[@]}" -c otf.c -o out/otf.o
"${LD[@]}" -soname libBMWOTFapi.so.3 -o out/libBMWOTFapi.so.3 out/otf.o -Llib -l:libc.so.3 -Lout -l:libscreen.so.1
"$CC" "${CF[@]}" -c ilm.c -o out/ilm.o
"${LD[@]}" -soname libilmClient.gpp.so.1 -o out/libilmClient.gpp.so.1 out/ilm.o -Llib -l:libc.so.3 -Lout -l:libscreen.so.1
cp out/lib*.so* "$OUT/"
if [[ "$OUT" != "$DEFAULT_OUT" ]]; then
  cp "$IOIPC" "$OUT/"
fi
printf '%s\n' "$PROFILE" > out/shim-profile
ls -l "$OUT"
