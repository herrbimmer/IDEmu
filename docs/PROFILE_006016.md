# Exact 006_016_002 JSON registry profile

The common/default shim selects `NBTevo_N18032I`,
`ID5_1803-510-1749I Build 66` from
[`nbtevo-006_016_002.json`](../idemu/data/firmwares/nbtevo-006_016_002.json).
Addresses, object offsets and instruction signatures now live in that JSON;
there is no firmware-specific `HMI_PROFILE_006016` build.
The neighbouring fixed `1803` shim still targets `006_017_006` / Build 71.

Use the three matching `006_016_002` SWFL packages: OS `0000271a`, HMI
`00002720`, BMW brand `00002719`. Leave `shim_profile` unset or choose
`"default"`. The builder checks the exact HMI and both companion libraries and refuses
unregistered sets before creating a shim image;
the guest checks all nine instruction signatures and ten required exports
before changing HMI code. Selecting the legacy `1803` shim is rejected.
The old `"006016"` environment spelling selects the common shim as a
compatibility alias and still rejects any other firmware.

| Input | SHA-256 |
| --- | --- |
| HmiMain3D | `084d0d3236d69bcfbacb2cb73827e2e88c7559e1eca5c1c03ab952805f2b0748` |
| libhmicom.so | `5539c1b0c3f0c2a62d39e159be7ca7f8ea65f38c66472b786d0a937e45bdf7c7` |
| libhmicoding.so | `836aa54d86d90b03d213603477e1c4c5fe9142c2c5c1450b76c4381e026e273c` |
| IFS libc.so.3 used to link the shim | `7d1199d75bd1187dc3e1842fa89320e9eb82d7215ccf4ce251edcf033cf46baf` |

Build the common guest libraries once with the original matching IFS libc:

```sh
SHIM_PROFILE=default bash src/shim/build.sh /path/to/boot/lib/libc.so.3
```

The output is `idemu/shim/lib/`, shared with all four supported `007` builds.
The old `SHIM_PROFILE=006016` command is an alias for this implementation and
checks the libc SHA-256 from the JSON before compiling. No `lib-006016` DSOs
are needed. Existing environments need a shim refresh to package the new table.

The builder writes a single complete `addr.tab`: 29 address fields, four ABI/
layout fields and 36 signature words. Only the ten supported address fields
are nonzero. The guest rejects incomplete/duplicate/invalid records before
publishing addresses or layout; legacy 007 tables still require all 29 nonzero
addresses. ABI 1 disables touch, TPM, Lua and debug hooks and retains the
application-thread power-on guard.

All nine fixed hook sites have four-word checks, verified against the exact
stock ELF and its unwind function starts. Before patching, this profile checks
all nine sites and resolves all ten required companion exports. A failed check
leaves every HMI hook unapplied. The home flags use offsets `0x576`/`0x577`;
the map-redirection pointer is the target's named symbol at `0x383275c`.

The enabled hooks cover power/home, controller/rotor and map surfaces. Runtime
input checks used direct controller events (command field four set to `1`) and
the rotor. The default combined CCS/controller input route and map rendering
were not exercised; map input was disabled in the test stand. Touch, TPM, Lua
and debug hooks are disabled. Snapshot restore is not validated.

Native Screen window creation (`screen_create_window_type`) returns `-1`,
QNX `ENOSYS` (89) and a null handle because native buffer posting is unsupported.
Android Auto callers can handle this error; it does not confirm video preview.
`tests/test_screen_window_type.py` checks this contract and the existing EGL
window path under AddressSanitizer.

On 2026-11-21 the exact stock set cold-booted locally, rendered the home screen
after about 20 seconds, and kept HmiMain3D alive during a 74-second observation.
An earlier startup crash was traced to auto-power-on running on the Platform
proc-unit thread. The common shim now requires the captured application proc unit
and its own thread before counting startup ticks or calling setPowerMode.
The native stock `tiler` GPU service produced a core file; rendering used the
emulator shim. This is not validation of that native GPU service.

The combined cold boot with the local N57 bundle and CarPlay app reached the
running state in 21.5 seconds. HmiMain3D mapped all six N57 app libraries and
the CarPlay app plugin, and remained healthy in the same process for more than
three minutes while their pages were exercised. No HMI exit occurred during
that combined run.

N57 workers used a synthetic HSFZ fixture on guest loopback:

| App | Observed result |
| --- | --- |
| ShiftDeck | 800 RPM, speed 0, shift target 4,000 RPM. |
| BoostDeck | N57 selected; boost 18.9 psi, 800 RPM, transmission 181.4 °F, coolant 194 °F. |
| Engine Fault Codes | Read the synthetic code `123456`; no clear requested. |
| LaunchDeck | READY at speed 0; no acceleration run. |
| xDrive Control | Page opened; no actuation requested. |
| HUD Gauges | Page opened; overlay remained disabled. |

The CarPlay scanner selected the exact Build 66 table. The plugin installed
7 fullscreen, 19 tilt, 2 touch and 2 knob patch words; a separate read-only
process-memory check matched all 30 words. Its one-minute boot guard passed.
The generated INI contained the 1440/1280 layout configuration and
`NudgeSupport`, and the Connectivity wrapper contained the configured
`LD_PRELOAD`. CarPlay settings, iDrive control and touchpad settings pages
opened and showed their configured checkbox states; HUD stayed unchecked.

These checks cover emulator startup, app pages, synthetic worker data and
patch/configuration installation. They do not test an iPhone/iAP2 session,
CarPlay video, real ECU readings or a physical HUD. They also do not validate
the native `tiler` service, touchscreen injection or snapshot restore.
Those earlier observations used the separately built shim. The new common-registry
rerun is recorded below; the historical results do not substitute for it.

## Earlier separate-shim Android Auto checks

A separate copy of the same stock firmware set was cold-booted with NBT-AAD
`v1.9.116` and a matched local `rhmiapp-93` bundle. It reached the running state
in 21.9 seconds and kept the same HMI process alive throughout a 587-second
observation. All eight N57, CarPlay and NBT-AAD plugin libraries stayed mapped;
the CarPlay settings page still opened.

All 18 NBT-AAD checkboxes changed and restored their own preference files
without changing the other flags. The three cluster choices and five vehicle
manufacturer choices saved correctly. About and Version rendered. Guest-only
PF rule install/check/uninstall returned success; the original configuration
was restored, with the filter disabled after uninstall as the utility intends.

Start kept the daemon alive for about 67 seconds with the default preview
setting; unsupported native Screen window creation returned error 89. Restart
replaced its PID, and Force Stop shut it down cleanly. The Open Android Auto
shortcut also started the daemon. With USB selected, the absent `io-usb`
service timed out after about a minute and the daemon fell back to watching
accessory device nodes; none were available in the VM.

The local Android Auto bundle used two app-side fixes: manufacturer Auto and
HUD Cyrillic have separate actions (421 and 426), and the saved Favorites
checkbox is refreshed on entering Settings. Those app changes are published separately in
[NBT-AAD PR #305](https://github.com/Sq00ky/Supra-iDrive6-Android-Auto/pull/305). The new Screen error export prevents an unresolved-symbol
crash; it does not implement native window buffers or video composition.

These checks validate menu preferences and process control. No phone pairing,
USB/AOA session, Wi-Fi/Bluetooth connection, projection video/audio, microphone
or physical cluster/HUD was tested. The NBT-AAD version tested explicitly has
no 6WB display driver. The stand also lacked a Connectivity-generated coded
`carplay.ini`, so Auto manufacturer fell back to Toyota unless chosen explicitly;
that is not a finding about the physical BMW unit. No vehicle was accessed.

## Common-registry rerun, 2026-11-22

The final common shim cold-booted the exact stock Build 66 set in **19.5 s**
with no firmware-specific selector. The guest logged `addr.tab: overrides
carregados 1d 1 45` (29 address slots, ABI 1, 69 complete records). All eight
N57, CarPlay and NBT-AAD app libraries were loaded. The public JSON, rather than
compiled Build 66 constants, supplied the addresses, layout and signatures.

The same common binary is also checked against the four registered 007 sets;
see the firmware matrix below. Auto-power-on is restricted to the captured
application proc-unit thread for every common-registry ABI. The separate
upstream fixed `1803` implementation is unchanged.

The final Build 66 run kept the same HMI healthy at **466.1 s**, with no HMI
exit or HMI core. It repeated all six N57 pages, selected Diesel/N57 and showed
800 RPM / 18.9 psi; Engine Codes read synthetic `123456`. CarPlay settings,
iDrive and touchpad pages opened; all 30 patch words/jump targets matched an
independent process-memory read. The one-minute boot guard cleared its strike
counter and the generated INI retained the 1440/1280 layouts and NudgeSupport.

NBT-AAD repeated all 18 checkbox toggles/restores independently and all eight
radio choices. The existing Favorites marker was reflected in the UI; Auto
left HUD Cyrillic off. About/Version opened. The default daemon kept the same
PID for 91.9 s of observation, Restart replaced it, and Force Stop removed it.
These remain menu/process checks, with the phone/media limitations above.

| Firmware | Common-shim cold boot | New validation scope |
| --- | --- | --- |
| `006_016_002` | 19.5 s | Six N57 pages/data, CarPlay patch/settings, NBT-AAD preferences/lifecycle; same HMI healthy at 466.1 s |
| `007_001_016` | 26.0 s | Baseline home and rotor; first HMI observed 61.1 s without exit |
| `007_030_001` | 24.5 s | Baseline home and rotor; first HMI observed 61.1 s without exit |
| `007_039_008` | 24.6 s | Baseline home and rotor; first HMI observed 61.1 s without exit |
| `007_051_002` | 20.2 s | Baseline home and rotor; first HMI observed 61.1 s without exit |

All five rows used the same common `libscreen.so.1` SHA-256
`320c152227e479330920f8a64585bd3886bf59aa759c29b94c97738289746e78`
and identical companion shim libraries, two CPUs and no snapshots/NIC or
host SSH/CAN/GPS bridges. The four 007 rows do not claim an app test matrix.
Source images were unchanged and all owned QEMU/renderer processes stopped.

## Test results

The final local IDEmu suite ran **339 tests: 327 passed, 12 skipped, no failures**.
The previously absent, unrelated MGU7 host renderer was built locally before
that run; its binary is not added to Git. Registry/parser tests cover exact
hashes, malformed or incomplete ABI/layout/signature metadata, atomic guest
publication, all nine bad-signature and ten missing-export preflight cases,
legacy 007 tables, missing-registry refusal, 1803 isolation, refresh/coding identity and the old selector
alias. The ARM regression rejects compiler-generated `__aeabi_memclr*` helpers,
which are unavailable in the matching Build 66 libc. App-thread startup checks
exercise both common ABIs. The existing Screen AddressSanitizer contract and
i18n checks pass.

Firmware, extracted libraries, images, private fixtures, captures and local
app-plugin binaries are not included in this repository. The common shim's
own generated DSOs are updated as in the existing multi-firmware implementation.
