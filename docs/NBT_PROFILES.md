# NBT Evo HMI shim profiles

NBT Evo `HmiMain3D` builds do not share a stable address layout. A fixed-address shim built for one firmware release must not be installed on another release.

The common/default shim selects five firmware sets from the
[JSON registry](../idemu/data/firmwares/README.md): `006_016_002`, `007_001_016`,
`007_030_001`, `007_039_008` and `007_051_002`. Each entry pins the exact HMI
and both hooked companion libraries before the builder writes `addr.tab`.
Build 66 also supplies its older object layout and nine four-word signatures.
The same `idemu/shim/lib` guest libraries serve all five versions.

The upstream `1803` / `006_017_006` profile remains separate, using
`idemu/shim/lib-1803`, its original feature gates, signatures and offsets.

## Validated binaries

| Profile | Firmware package | `HmiMain3D` SHA-256 | Validated scope |
|---|---|---|---|
| default | `swfl_00002720.bin.007_051_002` (24-03) | `fe770d1957fdfcd250d1f8cf7fba0e9a7c25e8c053e59f04f3274055fedda935` | Existing IDEmu functionality |
| `1803` | `swfl_00002720.bin.006_017_006` (18-03) | `2c906b5c6799a37a17b0ed51c37f67e0c1a2bc0edfb87596008f075062e9e6bf` | Home screen, surface-`0x501` map redirection, rotor and buttons |
| default / JSON registry | `swfl_00002720.bin.006_016_002` (Build 66) | `084d0d3236d69bcfbacb2cb73827e2e88c7559e1eca5c1c03ab952805f2b0748` | Cold boot, home, direct controller/rotor input and plugin menus; [exact validation and limits](PROFILE_006016.md) |

For 18-03, touch, TPM, Lua/debug-only hooks and fast-boot snapshot restore are not validated. The profile uses the host-rendered Screen/EGL/GLES/ILM path; it does not provide native PowerVR SGX rasterization or native QNX Screen/DISPC composition.

The `006_016_002` registry entry disables touch, TPM and Lua/debug hooks;
snapshot restore, map rendering and the default CCS input route were not
exercised. It cannot use the neighbouring `1803` profile. The old environment
selector `"shim_profile": "006016"` is retained only as a compatibility alias:
it requires this exact registry firmware and selects the common library folder.
New environments should omit `shim_profile` or use `"default"`.

## Fail-closed profile selection

`idemu/data/known_hmi.json` carries the fixed reference and `1803` hashes; the five JSON registry entries carry their own exact firmware identities. Set `shim_profile: "1803"` in the environment only when its extracted `HmiMain3D` has the exact hash above. The builder rejects unknown profile names, unsafe directory names and hash mismatches before packaging the selected shim. Explicit profiles also validate the exact `libhmicom.so` and `libhmicoding.so` companions; selecting the 18-03 HMI with the default shim is rejected.

Every enabled fixed code address in the 18-03 `HmiMain3D` profile also has a four-word ARM instruction signature. Installation skips and logs a mismatch rather than patching an unidentified location. `getHmiProcUnit` and `CHmiProcUnit::pushEvent` are resolved dynamically from `libhmicom.so` instead of using fixed PLT or vtable addresses.

For the `006_016_002` JSON entry, all nine signatures and ten required companion exports are
checked before any HMI hook is installed. Auto-power-on in every common-registry firmware runs only on the
captured application proc unit's thread, avoiding a startup crash caused by
calling the application power method from the Platform proc unit.

Surface-`0x501` redirection is part of the minimal 18-03 profile. Disabling it leaves the home screen effectively black even when the HMI has initialized and rendered other content.

Older 18-03 IFS images already start `ksh -li`; image creation requires the IFS console handling that preserves this record.

## Build the 18-03 shim

Use the `libc.so.3` from the same 18-03 boot image and a separate output directory:

```sh
SHIM_PROFILE=1803 bash src/shim/build.sh /path/to/18-03/boot/lib/libc.so.3
```

The fixed `1803` output stays separate from the common registry shim. `IDEMU_SHIM_OUT` can direct review builds to a separate artifact directory. The shipped common DSOs are rebuilt with this change.

Build the common shim once against the matching firmware libc:

```sh
SHIM_PROFILE=default bash src/shim/build.sh /path/to/boot/lib/libc.so.3
```

Build 66's linking fingerprint is recorded in its JSON and
[validation document](PROFILE_006016.md). The former `SHIM_PROFILE=006016`
build spelling still checks that libc fingerprint, but now builds the same
common/default implementation. It does not create `lib-006016`.

No firmware, generated disk images or extracted guest libraries are included.
