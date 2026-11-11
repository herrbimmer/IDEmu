# NBT Evo on Linux and WSL

IDEmu's NBT Evo / iDrive 5/6 renderer can run on Linux, including Ubuntu under WSL2. The guest still runs the original QNX HMI in QEMU; replacement Screen/EGL/GLES/ILM shims send its graphics commands to the Linux host renderer. This is not PowerVR SGX emulation or native QNX Screen/DISPC composition.

The Linux path was validated with Ubuntu 24.04 under WSL2, Mesa llvmpipe and QEMU 11.1.2. The existing macOS renderer remains supported.

## Requirements

- Your own supported NBT Evo firmware packages. IDEmu does not include BMW firmware or map data.
- Python 3.10 or newer.
- A C compiler and the normal QEMU build dependencies.
- OpenGL/GLUT and libpng development packages. WSL also needs an X server; `xvfb-run` is sufficient for headless use.

On Ubuntu 24.04, the additional packages used for the review build were:

```sh
sudo apt-get install -y \
  build-essential clang curl patch ninja-build pkg-config \
  libglib2.0-dev libpixman-1-dev \
  freeglut3-dev libgl1-mesa-dev libpng-dev xvfb
```

## Build

Build the patched ARM QEMU and the host renderer:

```sh
bash tools/qemu/build-arm-linux.sh
bash src/glhost/build.sh
```

The QEMU script downloads the official QEMU 11.1.2 source into `~/idemu-qemu` and builds in a separate directory. Set `QEMU_BUILD_DIR` to use another location or `QEMU_JOBS` to change build parallelism. It does not modify an existing QEMU checkout.

The resulting programs are `bin/qemu-system-arm` and `bin/glhost`. Their build products are not committed.

## Create and start an environment

Use **New environment** in the normal IDEmu interface and select your own firmware packages, or use the usual command-line environment/build workflow. Check that `build.json` reports `hmi_validated: true`; fixed-address guest shims must match the exact `HmiMain3D` build.

For headless WSL use:

```sh
LIBGL_ALWAYS_SOFTWARE=1 IDEMU_NO_SNAPSHOT=1 \
  xvfb-run -a python3 -m idemu gui --no-browser
```

Open `http://127.0.0.1:8765`, select the environment and start it. On a Linux desktop with a working display, `xvfb-run` is not required.

`IDEMU_NO_SNAPSHOT=1` is recommended because fast-boot snapshot restore has not been validated on this path. Stop the environment before closing the server so no untracked QEMU or renderer processes remain.

## Verification

The Linux path was exercised with the validated 24-03 HMI at 1440×540. Verification included a real home-screen framebuffer, map-surface composition and rotor/button input; a running QEMU process alone was not treated as success.

Useful smoke checks after source changes are:

```sh
bash -n tools/qemu/build-arm-linux.sh src/glhost/build.sh
bash src/glhost/build.sh
python3 -m unittest discover -s tests
```
