# NBT Evo HMI shim profiles

NBT Evo `HmiMain3D` builds do not share a stable address layout. A fixed-address shim built for one firmware release must not be installed on another release.

IDEmu keeps the original 24-03 profile as the default and supports a separate 18-03 profile. Profile library directories are independent: `idemu/shim/lib` for the default and `idemu/shim/lib-1803` for 18-03.

## Validated binaries

| Profile | Firmware package | `HmiMain3D` SHA-256 | Validated scope |
|---|---|---|---|
| default | `swfl_00002720.bin.007_051_002` (24-03) | `fe770d1957fdfcd250d1f8cf7fba0e9a7c25e8c053e59f04f3274055fedda935` | Existing IDEmu functionality |
| `1803` | `swfl_00002720.bin.006_017_006` (18-03) | `2c906b5c6799a37a17b0ed51c37f67e0c1a2bc0edfb87596008f075062e9e6bf` | Home screen, surface-`0x501` map redirection, rotor and buttons |

For 18-03, touch, TPM, Lua/debug-only hooks and fast-boot snapshot restore are not validated. The profile uses the host-rendered Screen/EGL/GLES/ILM path; it does not provide native PowerVR SGX rasterization or native QNX Screen/DISPC composition.

## Fail-closed profile selection

`idemu/data/known_hmi.json` carries the exact firmware set for each profile. Set `shim_profile: "1803"` in the environment only when its extracted `HmiMain3D` has the exact hash above. The builder rejects unknown profile names, unsafe directory names and hash mismatches before packaging the selected shim. Explicit profiles also validate the exact `libhmicom.so` and `libhmicoding.so` companions; selecting the 18-03 HMI with the default shim is rejected.

Every enabled fixed code address in the 18-03 `HmiMain3D` profile also has a four-word ARM instruction signature. Installation skips and logs a mismatch rather than patching an unidentified location. `getHmiProcUnit` and `CHmiProcUnit::pushEvent` are resolved dynamically from `libhmicom.so` instead of using fixed PLT or vtable addresses.

Surface-`0x501` redirection is part of the minimal 18-03 profile. Disabling it leaves the home screen effectively black even when the HMI has initialized and rendered other content.

Older 18-03 IFS images already start `ksh -li`; image creation requires the IFS console handling that preserves this record.

## Build the 18-03 shim

Use the `libc.so.3` from the same 18-03 boot image and a separate output directory:

```sh
SHIM_PROFILE=1803 bash src/shim/build.sh /path/to/18-03/boot/lib/libc.so.3
```

The default profile can be compiled independently with `SHIM_PROFILE=default`. `IDEMU_SHIM_OUT` can direct review builds to a separate artifact directory. Do not copy generated DSOs between profiles; generated profile DSOs are not included with the source change.

No firmware, generated disk images or guest libraries are included with the profile source.
