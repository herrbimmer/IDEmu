# Exact 006_016_002 minimal shim

The explicit `006016` shim targets `NBTevo_N18032I`,
`ID5_1803-510-1749I Build 66`. It is separate from `1803`, which targets
`006_017_006` / Build 71, and from the 29-address default firmware registry.

Select `"shim_profile": "006016"` in the environment and use the three matching
`006_016_002` SWFL packages: OS `0000271a`, HMI `00002720`, BMW brand `00002719`.
The builder rejects a different HMI or either companion library. Selecting the
default or legacy `1803` shim for this HMI is also rejected.

| Input | SHA-256 |
| --- | --- |
| HmiMain3D | `084d0d3236d69bcfbacb2cb73827e2e88c7559e1eca5c1c03ab952805f2b0748` |
| libhmicom.so | `5539c1b0c3f0c2a62d39e159be7ca7f8ea65f38c66472b786d0a937e45bdf7c7` |
| libhmicoding.so | `836aa54d86d90b03d213603477e1c4c5fe9142c2c5c1450b76c4381e026e273c` |
| IFS libc.so.3 used to link the shim | `7d1199d75bd1187dc3e1842fa89320e9eb82d7215ccf4ce251edcf033cf46baf` |

Build the separate guest libraries with the original matching IFS libc:

```sh
SHIM_PROFILE=006016 bash src/shim/build.sh /private/006016/boot/lib/libc.so.3
```

The output is `idemu/shim/lib-006016/`; default and `1803` libraries are not
replaced. The build rejects another libc. The fixed profile ignores `addr.tab`.

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
proc-unit thread. This profile now requires the captured application proc unit
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
The local firmware metadata remains excluded from the default address
registry; select this explicit shim instead.

## Android Auto menu and service checks

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
checkbox is refreshed on entering Settings. Those app changes are maintained
separately from IDEmu. The new Screen error export prevents an unresolved-symbol
crash; it does not implement native window buffers or video composition.

These checks validate menu preferences and process control. No phone pairing,
USB/AOA session, Wi-Fi/Bluetooth connection, projection video/audio, microphone
or physical cluster/HUD was tested. The NBT-AAD version tested explicitly has
no 6WB display driver. The stand also lacked a Connectivity-generated coded
`carplay.ini`, so Auto manufacturer fell back to Toyota unless chosen explicitly;
that is not a finding about the physical BMW unit. No vehicle was accessed.

## Test results

The final local IDEmu suite ran 328 tests: 315 passed, 12 were skipped and one
failed because the unrelated MGU7 host renderer `bin/glhost7` was absent. The
profile/parser, exact hash/libc refusal, App-thread guard and native Screen
AddressSanitizer checks passed. Twelve matched-source NBT-AAD host test programs
and the app-side regression checks also passed. Firmware, private fixtures,
images, captures and generated profile DSOs are not included in this repository.
