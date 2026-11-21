# NBT Evo HMI shim profiles

NBT Evo `HmiMain3D` builds do not share a stable address layout. A fixed-address shim built for one firmware release must not be installed on another release.

IDEmu keeps the original 24-03 profile as the default and supports separate
`1803` and `006016` profiles. Their library directories are independent:
`idemu/shim/lib`, `idemu/shim/lib-1803` and `idemu/shim/lib-006016`.

The default shim also supports `007_001_016`, `007_030_001` and `007_039_008` through the
[per-firmware address registry](../idemu/data/firmwares/README.md). Each entry pins the exact HMI
and both hooked companion libraries before the builder writes `addr.tab`. Registry entries do not
override the separate 18-03 profile, its instruction signatures, feature switches or structure offsets.

## Validated binaries

| Profile | Firmware package | `HmiMain3D` SHA-256 | Validated scope |
|---|---|---|---|
| default | `swfl_00002720.bin.007_051_002` (24-03) | `fe770d1957fdfcd250d1f8cf7fba0e9a7c25e8c053e59f04f3274055fedda935` | Existing IDEmu functionality |
| `1803` | `swfl_00002720.bin.006_017_006` (18-03) | `2c906b5c6799a37a17b0ed51c37f67e0c1a2bc0edfb87596008f075062e9e6bf` | Home screen, surface-`0x501` map redirection, rotor and buttons |
| `006016` | `swfl_00002720.bin.006_016_002` (Build 66) | `084d0d3236d69bcfbacb2cb73827e2e88c7559e1eca5c1c03ab952805f2b0748` | Cold boot, home, direct controller/rotor input and plugin menus; [exact validation and limits](PROFILE_006016.md) |

For 18-03, touch, TPM, Lua/debug-only hooks and fast-boot snapshot restore are not validated. The profile uses the host-rendered Screen/EGL/GLES/ILM path; it does not provide native PowerVR SGX rasterization or native QNX Screen/DISPC composition.

The `006016` profile has its own addresses and exact companion hashes. It also
disables touch, TPM and Lua/debug hooks; snapshot restore, map rendering and the
default CCS input route were not exercised. It cannot use the neighbouring
`1803` profile or the default 29-address registry.

## Fail-closed profile selection

`idemu/data/known_hmi.json` carries the exact firmware set for each profile. Set `shim_profile: "1803"` in the environment only when its extracted `HmiMain3D` has the exact hash above. The builder rejects unknown profile names, unsafe directory names and hash mismatches before packaging the selected shim. Explicit profiles also validate the exact `libhmicom.so` and `libhmicoding.so` companions; selecting the 18-03 HMI with the default shim is rejected.

Every enabled fixed code address in the 18-03 `HmiMain3D` profile also has a four-word ARM instruction signature. Installation skips and logs a mismatch rather than patching an unidentified location. `getHmiProcUnit` and `CHmiProcUnit::pushEvent` are resolved dynamically from `libhmicom.so` instead of using fixed PLT or vtable addresses.

For `006016`, all nine signatures and ten required companion exports are
checked before any HMI hook is installed. Auto-power-on runs only on the
captured application proc unit's thread, avoiding a startup crash caused by
calling the application power method from the Platform proc unit.

Surface-`0x501` redirection is part of the minimal 18-03 profile. Disabling it leaves the home screen effectively black even when the HMI has initialized and rendered other content.

Older 18-03 IFS images already start `ksh -li`; image creation requires the IFS console handling that preserves this record.

## Build the 18-03 shim

Use the `libc.so.3` from the same 18-03 boot image and a separate output directory:

```sh
SHIM_PROFILE=1803 bash src/shim/build.sh /path/to/18-03/boot/lib/libc.so.3
```

The default profile can be compiled independently with `SHIM_PROFILE=default`. `IDEMU_SHIM_OUT` can direct review builds to a separate artifact directory. Do not copy generated DSOs between profiles; generated profile DSOs are not included with the source change.

Build the exact Build 66 shim with `SHIM_PROFILE=006016` and the libc fingerprint
listed in [PROFILE_006016.md](PROFILE_006016.md), then set
`"shim_profile": "006016"` in that environment's `env.json`.

No firmware, generated disk images or guest libraries are included with the profile source.
