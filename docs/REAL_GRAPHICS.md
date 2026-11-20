# Real graphics (iDrive 5/6, experimental)

An iDrive 5/6 environment with `"real_graphics": true` also runs the firmware's own graphics stack: the QNX **Screen**
server with the real OMAP5430 WFD display driver, and BMW's **LayerManagerService**. QEMU gets a model of the OMAP5430
display controller (DSS) for them, and the display you see in IDEmu's page is what that controller scans out.

It is meant for work that needs the real window system: programs that create their own Screen windows, the
LayerManager scene (`LayerManagerControl`, layer and surface ids), and how they compose with the HMI.

What stays as before:

- **The HMI is still drawn by IDEmu.** HmiMain3D keeps using IDEmu's Screen/EGL/GLES/ILM shims and `glhost`. Its frame is
  mirrored into a real Screen window with the id `256`, the HMI's surface on the car, so it takes part in the real scene.
- **No GPU is emulated.** The PowerVR SGX540 and the Vivante GC320 are not modelled. Screen composes in software; EGL/GLES
  cannot be initialised by guest programs.
- Environments without the flag are unchanged, and so are all other generations: the flag is ignored outside iDrive 5/6.

## Using it

1. Build `bin/qemu-system-arm` with [tools/qemu/build-arm-linux.sh](../tools/qemu/build-arm-linux.sh). It now also compiles
   the DSS and SDMA models, which stay off unless QEMU runs with `IDEMU_DSS=1`. On macOS run it with a Homebrew Python of
   3.10 or later first in `PATH` (QEMU's configure does not accept Apple's 3.9), for example
   `PATH=/opt/homebrew/bin:$PATH bash tools/qemu/build-arm-linux.sh`.
2. Turn it on for an environment: `POST /api/env/<id>/update {"real_graphics": true}` (this rewrites the shim disk), or set
   `"real_graphics": true` in its `env.json` and rebuild. `false` turns it off again.
3. Start the environment. It always does a full boot: fast boot is off for these environments (snapshot restore with the
   file-backed guest RAM has not been validated).
4. Once the HMI is running, the head-unit page shows the real display. **Real graphics / IDEmu render** next to the display
   switches back to IDEmu's own renderer. The API is `POST /api/run/view {"view": "real" | "idemu"}`; `GET /api/run/frame`
   and `/api/run/screen.png` follow the choice, and `/api/run/status` has `real_graphics` and `view`. During the boot the
   page shows IDEmu's renderer, which the boot progress follows.

Controller, keys and touch work in both views: input still goes to the HMI through IDEmu.

With a `qemu-system-arm` built before this change (no DSS model) such an environment still boots, with the real Screen and
LayerManagerService, but the display stays on IDEmu's renderer and the page's guest log says to rebuild QEMU.

In the guest, the real libraries stay under `/fs/sda0/repository/istep/lib` (IDEmu's shims take `/lib/libscreen.so.1`,
`libEGL.so.1` and `libGLESv2.so.1`). A program that should use the real Screen server needs, for example:

```sh
R=/fs/sda0/repository/istep
export GRAPHICS_ROOT=/dev/shmem
export LD_LIBRARY_PATH=$R/lib:/dev/shmem:$R/lib/graphics/omap5430_ES2_0:/opt/sys/lib:/opt/hmi/lib:/opt/car/lib:/usr/lib
```

Logs in the guest: `/dev/shmem/realgfx.log`, `/dev/shmem/lms.log`, `/dev/shmem/hmimirror.log`; `sloginfo` has the
`[LMGR]` lines. On the host, the page's guest log has the `hmimirror:` lines of the mirror thread.

## How it works

| Part | What it does |
|---|---|
| `src/qemu/omap5430_dss.c`, `omap5430_sdma.c` | OMAP5430 DSS/DMM and SDMA models from bimmulator (see Credits). DISPC registers, vsync on SPI 25, DMM on SPI 113, SDMA on SPI 12-15. IDEmu adds `IDEMU_DSS_FRAME=<file>`: every 33 ms, and only when it changed, the scanned-out GFX plane is written there in IDEmu's frame format. |
| `src/qemu/omap5-uevm.c` | With `IDEMU_DSS=1` the board instantiates both models; without it the board is as before. |
| `idemu/runtime.py` | For `real_graphics` environments: `IDEMU_DSS=1`, `IDEMU_DSS_FRAME=<run>/dss.rgb`, guest RAM in the shared file `<run>/ram.bin`, the mirror thread once the HMI is running, and the view switch. |
| `idemu/builder.py`, `idemu/realgfx/` | The shim disk gets `realgfx/`: `start.sh`, `hmimirror`, and `graphics.conf` and `mode.sh` written for the environment's display. |
| `idemu/guest/boot.sh` → `realgfx/start.sh` | After the services and before the HMI: starts `/bin/screen` with that `graphics.conf` (software composition, the real WFD driver) and `LayerManagerService`, then `hmimirror`, and sets the car's scene: screen 0 → layer `0x80000000` → surface 256, visible. |
| `src/realgfx/hmimirror.c` | Guest helper: owns the Screen window `256`, writes where its buffer lies in physical memory to `/var/hmimirror.map`, and posts the window whenever the host bumps a counter in a shared control page (keepalive once a second). |
| `idemu/hmimirror_host.py` | Host thread: copies each new HMI frame from glhost's frame file into that buffer through `ram.bin`, then bumps the counter. |

On the car the HMI creates window 256 itself and sets its layer through ILM. Here its ILM calls go to IDEmu's ILM shim,
so `start.sh` sets the same scene with `LayerManagerControl`.

`graphics.conf` is the firmware's own `lib/graphics/omap5430_ES2_0/graphics-<width>_<height>.conf` cut down to what runs
without the GPUs; [idemu/realgfx/graphics.conf.in](../idemu/realgfx/graphics.conf.in) says what is kept and what is left
out.

`idemu/realgfx/hmimirror` is built from `src/realgfx/hmimirror.c` by [src/realgfx/build.sh](../src/realgfx/build.sh) with a
QNX 6.5 ARM GCC (by default the Docker image of [luka-dev/qnx65-armv7-toolchain](https://github.com/luka-dev/qnx65-armv7-toolchain));
the build is reproducible byte for byte. It loads the real `libscreen.so.1` with `dlopen`, so no QNX Screen headers are needed.

## Validated

With the 24-03 firmware (`007_051_002`), on macOS (Apple Silicon), in a new environment with default coding:

| | 1440x540 (default) | 1280x480 |
|---|---|---|
| Full boots with `real_graphics` | 4 | 1 |
| Real display = IDEmu's renderer (after two rotor steps) | 0 differing pixels in all 4 | 0 differing pixels |
| Real display frames during six rotor steps in 7 s | 54-61 in 3 boots (the HMI was still starting in the 4th) | 53 |

The same environment without the flag, on the same QEMU binary: four full boots and one fast boot reached `running` with
the same home screen as before (565,230 non-black pixels of 777,600; two rotor steps changed 83,524).

The display rate follows the source: the HMI redraws only when something changes. The DSS model writes at most about
30 frames a second (33 ms timer).

Not validated: the 18-03 profile, 800x480 and other displays, Linux hosts, fast boot.

**HMI exits.** Now and then the first HmiMain3D exits once with status 138 (SIGBUS) during its start, and `boot.sh`
restarts it: in 2 of the 5 `real_graphics` boots, and in 1 of 8 plain full boots on the same QEMU binary (the 4 above and
4 in a second environment). So it is not caused by this mode, though it may be more frequent with it. Not investigated
further.

## Credits

The OMAP5430 DSS/DMM and SDMA models are taken from [agent00jackson/bimmulator](https://github.com/agent00jackson/bimmulator)
(`nix/patches/qemu/0001-omap5-core.patch`, commit `bf03f2e`), GPL-2.0-or-later like the rest of `src/qemu`. Each file
says where it comes from and what IDEmu changed. bimmulator also showed that the firmware's Screen server runs on QEMU
with software composition, which this mode builds on.
