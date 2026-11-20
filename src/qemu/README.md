# QEMU próprio do IDEmu (iDrive 7)

Dois arquivos do QEMU 11.1.2 que o IDEmu modifica/acrescenta; `tools/qemu/build.sh` os copia para a árvore do QEMU, compila e instala `bin/qemu-system-x86_64`.

* `idemu-shm.c` (novo): dispositivo PCI `idemu-shm` (1b36:1d3a). Um BAR de memória apoiado num objeto POSIX `shm_open()` que o `glhost7` também mapeia. O guest o mapeia por
  `/sys/bus/pci/devices/.../resource0` (sem driver) e o usa como anel de comandos GL. O `ivshmem` do QEMU só compila no Linux. O dispositivo registra o BAR como RAM nomeada
  (`vmstate_register_ram`) e o PCI no vmstate, para entrar no snapshot (`savevm`).
* `sdhci-pci.c` (alterado): o vmstate do SDHCI não inclui o espaço de configuração PCI; depois de um `loadvm` o controlador sumia do barramento e o guest recebia erro de E/S no cartão
  SD (`mmcblk0: error -123`). O acréscimo grava só o `PCIDevice`.

Sem este binário o iDrive 7 ainda sobe com o QEMU do Homebrew, mas pela serial (≈ 100x mais lenta) e sem boot rápido.

## iDrive 5/6: segundo núcleo do OMAP5 (experimental)

`omap5-uevm.c` liga o CPU1 como a ROM do OMAP5: o startup do QNX grava `AUX_CORE_BOOT_0/1` (0x48281800/0x804) e dá `sev`; o vCPU, que começa desligado, sobe no
endereço gravado e recebe o VBAR dos vetores do `stub.bin` (sem isso o primeiro `smc` do núcleo secundário caía no vetor 0x4 e ele ficava preso em aborts).
Com `IDEMU_SMP=2` (e um `qemu-system-arm` compilado com este arquivo, apontado por `IDEMU_QEMU_ARM`) o QNX sobe com os dois núcleos (`procnto-smp`, MTTCG) e o
`boot.sh` prende o HMI no CPU0 (`on -R 1`). Estado em 2026-11-09: serviços e shell sobem; o HMI ainda sai com 138 (watchdog do SvcDSI) num Mac carregado, então
o padrão continua 1 núcleo. Com o
Mac sem carga (2026-11-09, f30-bmw, boot completo): os serviços chegam antes (3,6 s contra 5,0 s), mas o HMI, preso no CPU0, é o gargalo e o boot até a tela levou 55,6 s
(1 núcleo: 27–37 s) com uma saída 138 no meio; o rotor responde igual (0,086 s). Sem `on -R 1` o HMI sai com 138/139 em laço. Compilação: a árvore do QEMU 11.1.2 com `qemu-v11.1.2-idemu.patch` + este arquivo + os modelos `omap5430_*` (seção abaixo), `--target-list=arm-softmmu`; o `tools/qemu/build-arm-linux.sh` faz tudo isso.

## iDrive 5/6: OMAP5430 DSS and SDMA models (`real_graphics`)

`omap5430_dss.c`/`.h` (DSS/DMM: DISPC registers, vsync, scan-out) and `omap5430_sdma.c`/`.h` (system DMA) come from
[agent00jackson/bimmulator](https://github.com/agent00jackson/bimmulator) (`nix/patches/qemu/0001-omap5-core.patch`,
commit `bf03f2e`), GPL-2.0-or-later. IDEmu added origin lines to all four and, in `omap5430_dss.c`, the `IDEMU_DSS_FRAME`
scan-out to a frame file. `omap5-uevm.c` instantiates them only with `IDEMU_DSS=1`, which the runtime sets for
environments with `"real_graphics": true`; `tools/qemu/build-arm-linux.sh` copies them into the QEMU tree and adds them to
`hw/display/meson.build` and `hw/dma/meson.build`. See [docs/REAL_GRAPHICS.md](../../docs/REAL_GRAPHICS.md).
