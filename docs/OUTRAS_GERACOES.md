# CIC, iDrive 5, 7 e 8: o que foi testado (2026-11-07)

Pacotes: `~/Downloads/System files`, cópias da PSdZData. Nenhum deles é alterado.

| Geração | Pacotes | Plataforma | Resultado |
|---|---|---|---|
| CIC | CIC High "BMW L6" 008_090_002 (Harman) | SH7785 (SH-4A), QNX 6.3.2 | **Roda no IDEmu com a interface real** (Hauptmenü) numa placa SH7785 nova do QEMU, ≈ 70 s de boot; **rotor, aperto, inclinação e teclas** por um controlador MOST virtual injetado no HmiMain. Ver `docs/CIC.md` |
| iDrive 5 | NBT Evo 007_051_002, os mesmos do iDrive 6 | OMAP5, QNX 6.5 | **Interface real roda no IDEmu**, com quedas do HMI nos menus de navegação. `HMI_ID_VERSION=id5` |
| iDrive 7 | `HU_MGU_01` 036_010_004 (kernel e sistema) + `RSE_MGU_01` 030_016_002 (**`HmiMain3D`/RAMSES e dados do HMI**) | Intel Apollo Lake, Linux 4.14, x86-64 | **A tela central (HU_HMI) e a do banco traseiro (RSE) desenham e respondem a toque, rotor e botões** (≈ 3,5 min de boot); falta o conteúdo (mídia, telefone, navegação). Ver as seções abaixo |
| iDrive 8 | `MGU_02_*` 007_034_003 e 009_020_028 | Qualcomm SA8155, Linux 5.15, ARM64 | **Roda no IDEmu com interface real, toque e rotor**; sem mapa nem sinais do carro |

## iDrive 5
O SWFL do iDrive 6 já traz o iDrive 5: `opt/hmi/ID5/data/ro/bmw/id5` e `common`. O binário é o mesmo `HmiMain3D`, e a codificação `HMI_ID_VERSION` escolhe a interface
(valores `id4_plus_plus`, `id5`, `id5_plus_plus`, `id6_light`, `id6`). O IDEmu antes deixava `bmw/id5` fora do disco; agora inclui, então **um ambiente antigo precisa ser recompilado** antes de mudar a geração.

Verificado no ambiente `f30-idrive-5` (criado neste teste, pode ser apagado): menu vertical com o controlador desenhado, rotor, submenus de Mídia e de Navegação. Boot rápido também funciona. **Toque** (2026-11-07): tocar em ConnectedDrive abriu o menu; ver `docs/TOQUE.md`. O HMI do iDrive 5 redesenha devagar na emulação: depois do boot os painéis de pré-visualização levam até cerca de 1 minuto e cada entrada (rotor, toque, botão) leva vários segundos para aparecer na tela, embora o HMI a processe na hora.

**Não está estável:** em cerca de 5 minutos de uso nos menus de navegação, o HMI saiu 3 vezes com status 139 (SIGSEGV). A primeira foi ao carregar ícones do menu de destino (`icon_nav_map_cb_content_poi`); depois de reiniciar, ele caiu de novo logo depois de criar o shader `mat_outline_preview`. A causa não foi encontrada. A tela Mapa não chegou a abrir nesse ambiente, então **o mapa não foi verificado no iDrive 5**. Os avisos `Failed to retrieve resource` (`CGfxWidgetAsset.cpp:1068`) aparecem nesse modo, por exemplo em Notificações.

O pacote `001_060_001`, que `System files/ID5` chama de ID5, é outra coisa: um NBT Evo mais antigo com o HMI em `opt/hmi/ID4`. Os endereços fixos do shim não valem para esse binário; não foi testado.

## iDrive 8 (MGU22)

**Cluster e HUD virtuais (CIC, iDrive 7 e 8, 2026-11-10):** `Runtime._start_sim()` liga os simuladores de CAN e GPS do IDEmu (portas `can_port`/`gps_port`) nesses ambientes e as abas **CAN** e **Cluster e HUD** passam a existir. Eles alimentam só o painel virtual (`GET /api/cluster`, velocidade, rotação, luzes, GPS): o HMI dessas gerações **não** recebe esses sinais, então a matriz continua marcando "CAN" como não funcionando. Verificado nos três: `can.set_signal('vehicle_speed', 88)` aparece no `cluster.snapshot`.
**SSH (2026-11-10):** o shell do guest (`ttyAMA0`, o stdin do QEMU é o FIFO `console.in` e a saída vai para `logs/console.log`) também fica em `shell.sock` (`runtime.ConsoleMux`, `MguRuntime._con_write`/`_tail_console`) e o `sshd` do IDEmu abre a sessão nele quando o HMI desenha. Testado: `ssh -F <ambiente>/ssh/ssh_config idemu 'uname -sr; id'` → `Linux 5.15.123`, `uid=0(root)`, em 0,2 s por comando (o BusyBox do guest não aceita `head -5`; use `head -n 5`). A aba **SSH** do app aparece também para o iDrive 8.
**Roda dentro do IDEmu, com a interface real e controles funcionando** (captura em `docs/verif_idrive8.png`). Em **Novo ambiente**, escolha **iDrive 8**: ele lê os arquivos direto da PSdZData configurada, monta a imagem (2 min no máximo, 4 GB em `mgu22/`, compartilhada entre ambientes) e aparece como um ambiente comum. O HMI desenha a tela completa cerca de 15 s depois de iniciar.

Fora da interface web:
```bash
python3 tools/mgu/build_image.py
```
```bash
python3 tools/mgu/run.py --debug
```

| O que funciona | Como |
|---|---|
| Tela 2880×960 do `Hmi8` real | ANGLE (Metal) no Mac; `inp.py 'x px py'` lista qual shader pinta um pixel |
| Toque e arraste | Touchscreen `uinput` real (`idemuinput`), o caminho normal do HMI |
| Rotor, push, inclinação e botões | Chamadas a `CHmiCCSDevice` na thread do HMI (`hmihook.c`) |
| Relógio | Hora do Mac em `CDevCarIcTimeDate::onPxyShowTimeDate` |
| Temperatura e botões + e − | Sem a central de clima, o pedido volta como estado para `DevClimateMaster` |
| Tema | `Adaptive` fixo; sem o serviço My Modes o HMI cairia em `Unicorn` ou `Artmode_*` |
| Perfil, privacidade, mídia, contatos, dispositivos, telefone | Daemons do firmware: `persod`, `dataprivacyd`, `mediaapp`, `pim`, `devicemanager`, `telephonymanager`, com D-Bus |

De onde vêm os dados, todos em versão `007_034_003`:
| Dados | Pacote |
|---|---|
| Kernel e raiz | `swfl_00009ff7` |
| Contêiner IVI com `/usr/bin/Hmi8` | `swfl_00009fc6` |
| `/opt/ext` | `swfl_00009ff9` |
| `/var/begu/hmi-data/bmw` (telas, textos, ícones) | `swfk_0000a6b1` |
| `/var/begu/hmi-data/bmw-shared` | `swfk_0000a6b0` |
| `/var/begu/hmi-vehicles/G70BEV` | `swfk_0000a6a6` |

### Como funciona
* **Codificação:** `libcod.so.0` próprio com `coding.tab`, gerado do `MGU22_Coding.txt` do firmware (G70BEV, BMW, ID8, 2880×960) e do esquema `cafd_mgu_02_a.bin` (`src/mgu22/libcod.c`, `tools/mgu/gencoding.py`).
* **Wayland:** `idemuwl.c` substitui o `winston`: só responde ao protocolo (`wl_compositor`, `ivi_application`, `ivi_controller`, `wl_output`).
* **GPU:** `libEGL.so.1`/`libGLESv2.so.2` (`guest_egl.c`) mandam as chamadas GLES ao host; `mguhost.c` as executa no ANGLE e grava `frame.rgb`, o mesmo formato do `glhost`.
* **Canal:** o kernel não tem virtio, `/dev/mem` nem UIO cacheado. A RAM do guest é um objeto POSIX compartilhado entre o QEMU e o `mguhost`, e `qemushm.c` faz o `memory-backend-shm` do QEMU usá-lo. Cada thread GL cria dois anéis em memória travada, escreve os PFN das páginas (de `/proc/self/pagemap`) num cabeçalho, e o host o acha varrendo a RAM (`chan.h`).
* **Boot:** o initramfs sem compressão vai direto para essa RAM antes do QEMU iniciar. Dois tempos de espera por centrais que não existem são encurtados em memória: 30 s de `earlyhmi` e 30 s do sinal do painel de instrumentos.
* **Correções em memória:** `libidemuhmi.so` (`LD_PRELOAD`) usa os símbolos exportados do `Hmi8`, que tem 211 mil funções na `dynsym`. Comandos chegam por `input.sock` e rodam dentro de `CHmiGraphicsMainloop::onFrameTimer`.

**ANGLE:** vem de um app Chromium instalado em `/Applications` (Spotify, CapCut etc.), ou da pasta em `IDEMU_ANGLE`. Sem nenhum dos dois, o ambiente não inicia. O IDEmu não traz uma cópia.

### Verificado
* Imagem montada do zero com `build_image.py`, ambiente criado e iniciado pelo assistente da interface web; estado `running` em 10 s.
* 10 minutos de uso aleatório pela API: 606 toques, arrastes, passos de rotor e teclas. HMI sem nenhuma queda, 0 erros de GL no host. A memória do HMI subiu de 726 MB para 847 MB nesse tempo.
* Toque em ícones, rotor, push, Menu, Back, Option, Rádio, Mídia, Telefone e Nav; + e − do clima; lista de apps; menu de opções.
* A inclinação do rotor só entrou no teste aleatório: não conferi o efeito de cada direção. Não verifiquei cada tela dos aplicativos. Com o HMI caindo, o guest o reinicia (`IDEMU-HMI-EXIT` no console), mas esse caminho não foi exercitado.

### O que falta
* **Mapa e navegação:** a tela fica em `STARTING NAVIGATION SYSTEM...`, e o fundo da tela inicial é uma imagem fixa, não um mapa. A PSdZData não traz base de mapas NDS. O `nv_main` desenha via compositor embutido do Ramses (`wayland-1`, `hmiec.socket`), que não está implementado.
* **Sinais do carro:** 57 serviços que o `Hmi8` consome vêm de outras centrais do carro (clima completo, carroceria, portas, bateria). Só relógio e temperatura são simulados: `A/C OFF` não muda, e telas de veículo ficam sem dados.
* **Rádio, Bluetooth, câmeras, áudio:** sem hardware virtual. Telas abrem, sem fonte ativa.
* **Na interface web:** sem abas de CAN, GPS, mapa, SSH e V850, sem editor de codificação, sem boot rápido por snapshot e sem escolha de tema na tela (`C <tema>` em `input.sock`).
* **Painel de instrumentos e HUD:** só a tela central é desenhada.
* Os binários estão fixos em `007_034_003`; outra versão de `Hmi8` pode não ter os mesmos símbolos.

## iDrive 7 (MGU, x86-64 Linux) — atualização de 2026-11-07, parte 2
**Correção:** o texto anterior dizia que o HMI do iDrive 7 não estava nos pacotes. Ele está: `HmiMain3D` (ELF x86-64, 170 MB, usa **RAMSES** com a plataforma `wayland-ivi-egl-es-3-0`)
vem nos pacotes **RSE_MGU_01** (`swfl_0000567a`, versão 030_016_002), com os dados `/hmi/*` (`567b`–`567e`, `5682`, `5683`, ≈ 2 GB). O `HU_MGU_01` (os 14 pacotes de `System files/ID7`) é só o resto do sistema
(winston, earlyhmi, mídia, drivers). O `HmiMain3D` aceita as funções `CID_*` (tela central) e `RSE_*` (bancos traseiros); o serviço do RSE o inicia com `-r=RSE_HIGH_LEFT`.

O que passou a funcionar (ferramentas em `tools/mgu/`):
1. **Formato HAR decifrado** (`har.py`): registros `[bloco HAR#$%&@ de 64 B][cabeçalho 92 B][nome][28 B][dados]`; dados = fluxo zlib por arquivo (arquivos grandes em blocos de 50 MiB, vários registros com o mesmo nome),
   symlinks e elos rígidos como registros próprios. `har.py pacote destino` extrai a árvore inteira (verificado: os tamanhos batem com o `ContentSize` do manifesto de cada pacote). `extract_rse.sh` extrai o conjunto RSE (≈ 3,3 GB).
2. **O kernel do MGU (4.14.198/4.14.300-apl) sobe no `qemu-system-x86_64` (q35, TCG) e monta a raiz.** O pânico antigo (`divide error` em `tk_setup_internals`) vem de o kernel usar o relógio do TSC já no
   `timekeeping_init` e só calcular o `mult/shift` quando a frequência do TSC é "conhecida" (CPUID 0x15 do Apollo Lake, que o QEMU/TCG não dá). `tscfix.py` liga-se ao gdbstub (`-gdb tcp::PORTA -S`), para na entrada de
   `tk_setup_internals`, grava `mult=0x1000000, shift=24` e libera; o relógio verdadeiro é registrado depois. O kernel não tem initramfs, virtio nem DRM virtual: a raiz vem de um cartão SD (`-device sdhci-pci`, `root=/dev/mmcblk0`).
3. **`mkext2.py`** cria a imagem ext2 da raiz sem e2fsprogs (3,1 GB em ≈ 8 s). `boot_mgu.sh` e `idemu-init.sh` são o roteiro do teste.
4. Com a raiz completa, o userland do MGU (glibc 2.27) roda e o **`HmiMain3D` inicia** (RSS sobe até ≈ 144 MB em ≈ 30 s de TCG e para; nenhuma saída no console, o HMI registra pelo DLT).

O que **não** foi feito: **nenhum pixel**. Falta, em ordem:
* **GPU/EGL**: o guest só tem `libEGL`/`libGLESv2`/`libgbm` do Mesa para GPU Intel (`i965_dri.so`) e o kernel não tem DRM virtual (o `i915.ko` não tem hardware para falar). O RAMSES pede **OpenGL ES 3.0** via Wayland IVI.
  Caminho: bibliotecas EGL/GLES3/wayland-egl substitutas no guest + um canal para o host (o QEMU do brew não tem `ivshmem`; seria preciso um dispositivo PCI novo, como a ponte MMIO do OMAP5) + renderizador no Mac
  (OpenGL 4.1 ou ANGLE) — o `glhost` atual só fala GLES2.
* **Wayland**: o HMI conecta ao compositor (`winston`, do MGU) por `ivi-application`; no guest vai precisar de um compositor mínimo ou do próprio `winston` apontado para a nossa saída.
* **Serviços**: o HMI consome dezenas de interfaces SOME/IP (`vsomeipd`, `NodeStateManager`, `persod`, `codingshm`…). Não se sabe ainda em que ele está parado.
* Rede: o kernel não tem driver para NIC emulada (só `igb_avb` para I210 e USB `asix/smsc95xx`, nenhum emulado pelo QEMU).

Fontes dos testes: `swfl_00005684` (kernel `ias_rsu`, linha de comando do MGU) e `swfl_00005677`/`632c` (kernel 4.14.198 do RSE, em `ias_app`/`ias_rsu`).

## iDrive 7: ponte de vídeo (2026-11-07, parte 3)
Estado: **o caminho de vídeo funciona de ponta a ponta, mas o HMI ainda não desenha nada** (o único quadro entregue é preto).

Peças novas em `src/mgu/` (compilar com `build.sh`; usa clang + ld.lld do Rust, como o shim do NBT):
* `wlstub.c` → `idemu-wl`: compositor Wayland mínimo (protocolo do fio, sem libwayland-server). Globals `wl_compositor`, `wl_output` (1920x1080), `wl_seat`, `ivi_application`, `ivi_controller` (com 1 tela).
  Responde `sync`/`frame`, cria superfícies IVI e camadas. O protocolo IVI foi lido das interfaces de `libivi-*.so` (`tools/mgu/wlif.py`).
* `gles_guest.c` + `gen_gl.py` → `libGLESv2.so.2` (e `libEGL.so.1` vazio que depende dele): substituem o Mesa do guest. EGL local (uma config, `eglCreateWindowSurface` lê `wl_egl_window`) e as 111 funções EGL/GLES3 que o RAMSES importa,
  serializadas por `/dev/ttyS1` (protocolo em `proto.h`; QEMU liga a ttyS1 a um socket unix). Medido: ≈ 0,7 MB/s.
* `glhost7.c` → `glhost7`: renderizador no Mac. Executa o fluxo em **OpenGL 4.1 core** (CGL fora da tela, Apple M1 Max/Metal), traduz shaders GLSL ES 1.00/3.00 → 4.10
  (`sample`/`patch` renomeados, `attribute/varying`, `gl_FragColor`), emula `glTexStorage*`, mapeia formatos L/A de ES para R/RG + swizzle. Grava os quadros em `<pasta>/frame.rgba` (64 B de cabeçalho `w,h,seq` + RGBA, topo primeiro).

Verificado: o `HmiMain3D` conecta ao compositor, cria a superfície 1920x1080, o RAMSES compila shaders (sem erro de compilação nos testes), faz upload dos recursos (530 recursos, vários minutos em TCG), a cena do HMI chega a `Rendered`
com 2693 objetos e o primeiro `eglSwapBuffers` chega ao host. Depois disso o renderizador fica em ≈ 58 FPS com **0 draw calls**: o HMI não mostra nenhuma tela.

Hipótese (não confirmada): é o HMI do banco traseiro (`-r=RSE_HIGH_LEFT`) e ele só ativa a tela por eventos que nós não geramos (toque pelo `tHMI_CTouchD`, ativação pela RSU/HU, estado do `NodeStateManager`, serviços SOME/IP
dos outros processos do RSE). Não há logs do HMI: ele usa DLT, e o `dlt-daemon` do guest não abre TCP (só socket unix/FIFO em `/run/dlt-files/dltpipes`); ler esses logs seria o próximo passo.

Como repetir: `tools/mgu/extract_rse.sh` → montar `/tmp/mgu/rse/root` (app + data) com `idemu-init.sh` na raiz e as `libGLESv2/libEGL` novas em `/usr/lib` → `tools/mgu/go.sh` (grava a imagem ext2, sobe o QEMU com ttyS1/ttyS2 em sockets e o `glhost7`);
`tools/mgu/c.py 'comando'` executa um comando no guest; `tools/mgu/frame2png.py` converte o último quadro.

### Atualização: por que o HMI não desenha (parte 4)
* **Logs do HMI:** o `dlt-daemon` do guest não abre TCP, então o init o troca por um sorvedouro: cria o FIFO `/run/dlt-files/dlt` e grava tudo em `/tmp/dltraw`; `strings /tmp/dltraw` mostra os logs do HMI, vsomeip, persod etc.
* **vsomeip confere uid/gid** (`/etc/vsomeip/vsomeip_security.json`): com tudo como root, o roteador rejeitava as conexões ("routing manager credentials do not match", ≈ 1700 vezes). Agora cada serviço roda como o usuário da unit
  (`tools/mgu/idemu-init.sh`, via `idemu-run` de `src/mgu/idemu_run.c`: vsomeipd=`sin_vsp`, CodingShmApp=`sf_codingshmservice`, persod=`sps_8000`, NodeStateManager_rse=`sin_nsm`, HMI=`hmi_5000`) e as rejeições sumiram.
  O HMI, como não-root, precisa de `chmod 666 /dev/ttyS1` (canal GL).
* Com isso o HMI roda a máquina de estados (estado raiz 20000, widgets de início, mídia, persod, coding falso) e a cena do RAMSES chega a ~3300 objetos, `Rendered`, mas continua com 0 draw calls.
* **Bloqueio identificado:** o HMI usa o serviço SOME/IP **`lifecyclerse.LifecycleRSE`** (e o `rselowpowermodecontroller`, que agora roda, loga "RseLifecycle not available"). Esse serviço é do **head unit** (não existe em nenhum binário dos pacotes RSE; só aparece em
  `etc/oap/someip/someip-interfaces.json`). Sem ele o RSE fica em baixo consumo, sem exibir conteúdo. Oferecê-lo exige um stub SOME/IP/CommonAPI em C++ (as bibliotecas `...lifecyclerse.stub.someip.so` estão no guest, mas não há headers do CommonAPI/vsomeip para compilar um servidor).

### Atualização: o LifecycleRSE não era o bloqueio (parte 5)
* **Protocolo local do vsomeip decifrado** capturando o tráfego dos próprios serviços (`src/mgu/spy.c`, um `LD_PRELOAD` que registra os bytes dos sockets unix): quadros `67 37 6d 07 | cmd u8 | cliente u16 | tamanho u32 | payload | 07 6d 37 67`;
  `ASSIGN_CLIENT`=0, `REGISTER_APPLICATION`=2, `REGISTERED_ACK`=6, `OFFER_SERVICE`=0x10, `SUBSCRIBE`=0x12, `REQUEST_SERVICE`=0x14, `SUBSCRIBE_ACK`=0x17, `SEND`=0x18, `REGISTER_EVENT`=0x1b; cada app escuta em `/tmp/vsomeip-<id hex>` e os pares falam direto.
  `src/mgu/lifecycle.c` (`idemu-lifecycle`) usa isso para oferecer o `LifecycleRSE` (0xB016, instância 1; campos e ids vêm de `etc/oap/someip/someip-interfaces.json`). **Funciona**: o `vsomeipd` aceita a oferta, o `rselowpowermodecontroller` loga "RseLifecycle AVAILABLE" e recebe `FULL_ON_USER_ON (99)`.
* **Mas o HMI continua sem desenhar**, e o motivo é outro: o `LifecycleRSE` é oferecido pelo próprio `NodeStateManager_rse` (o stub `LifecycleRSEStubImpl` está nele). A máquina de estados dele entra em `NormalMode`/`Network Active` e logo em **`ShutdownActive`**
  ("transition isNMsleepmode_CAN = TRUE && isNMsleepmode_Eth = TRUE && isShutdownActive_LCMG = TRUE"; "PowerCtrlProxy not available or value invalid for more than 3 seconds"), e anuncia `SHUTDOWN_MODE_USER_OFF (34)`.
  As entradas são o gerenciamento de rede (CAN/Ethernet NM) e os `mal_cb_lcm_*`, que chegam do **controlador de E/S pelo IPC4/HDLC em `/dev/ttyS0`** (`hdlc_ipc4`, `ioclcproxy`). Sem esse controlador emulado, o RSE se desliga sozinho.
  Por isso o init **não** inicia o `idemu-lifecycle` (ficaria duplicado com o do NSM); ele fica como ferramenta/documentação do protocolo.
* Próximo passo real: emular o controlador de E/S (o equivalente ao V850 do NBT, ver `docs/V850.md`) e o gerenciamento de rede para o NSM manter o nó ativo.

### iDrive 7 — parte 6: vídeo (o HMI do RSE desenha)

![HMI do RSE no emulador](id7_frame.png)

O HmiMain3D (RSE_HIGH_LEFT) agora entrega quadros reais pela ponte GL (menu lateral, "Individual entertainment", "Theatre mode"). Foram três bloqueios em sequência:

1. **Controlador de E/S falso** (`src/mgu/fakeipc.c`, vira `/usr/lib/idemu/libipc.so.1`): o `ioclcproxy` fala com o IOC por `libipc` (`/dev/ipc/ipc2`), mensagens de 40 bytes (`A5, wake-up, ?, PWF, seq16, estado de comunicação, comando, tamanho, payload`). O falso responde `DATAFLASH_READ` (byte 7 = RSE low power mode inativo), dá `ACK` aos demais e manda STATUS com máscaras de rede parcial. Sequência que mantém o modo de entretenimento: PWF = WOHNEN, wake-up CAN primeiro e depois `RSE_ON_BUTTON_LEFT` (com PWF mudando depois, a máquina de estados sai do modo). Controle ao vivo por `/tmp/ioc.ctl` ("wur pwf com").
2. **NM acordada** (`tools/mgu/patch_rse.py`): o `ioclcproxy` e o `udpnm` (Ethernet) voltavam a `busSleepState`; com os dois NM dormindo e o LCM em USER_OFF o NodeStateManager entrava em `ShutdownActive`. Os slots de sono viram `ret`. `udpnm` entra no init.
3. **Quadros do Ramses**: o Ramses diz `will skip frames because window is not ready`. A janela Wayland só renderiza de novo depois do callback do `wl_surface.frame`, mas esse pedido ficava no buffer do cliente: o EGL do Mesa descarrega o `wl_display` em cada `eglSwapBuffers`, o shim não. `eglSwapBuffers` e `eglMakeCurrent` do shim agora chamam `wl_display_flush`.

Diagnóstico que levou até aí: contadores de desenho no `glhost7` (`comandos, quadros, desenhos, clears`), log de cada requisição Wayland no `idemu-wl`, e a leitura da vtable do `Window_Wayland_IVI` (slot `canRenderNewFrame` = flag em +0xa8).

### iDrive 7 — integrado ao app (2026-11-07)

O iDrive 7 agora é uma geração do assistente **Novo ambiente** (como o iDrive 8): escolha **iDrive 7** → **Criar e compilar** → **Iniciar**. A tela mostrada é a do banco traseiro (RSE, 1920×1080).

* `idemu/mgu7.py`: `build()` extrai da PSdZData os 11 pacotes `RSE_MGU_01` de aplicação e os 7 de dados (versão 030_016_002, via `tools/mgu/har.py`), o kernel (`ias_rsu` do pacote `00005684`, versão 036_010_004, sem os 480 bytes de cabeçalho),
  aplica `tools/mgu/rse_overlay/` (fstab, units do systemd, `nsm_fake_coding_rse`), `tools/mgu/idemu-init.sh`, os binários do guest de `idemu/guest7/` (shim EGL/GLES, `idemu-wl`, `idemu-run`, `libipc` falso, `libspy`) e `patch_rse.py`, e grava `mgu7/root.img` (ext2, 4 GiB) e `mgu7/bzImage`. Leva ≈ 25 s e usa ≈ 3,3 GB temporários.
* `Mgu7Runtime`: sobe `bin/glhost7` e o `qemu-system-x86_64` (do Homebrew; `IDEMU_QEMU_X86` troca) com a imagem em modo `snapshot=on` (o disco nunca é alterado), libera o kernel com `tscfix.py`, acompanha o console (`logs/console.log`, etapas do init na barra de boot) e converte o `frame.rgba` do glhost7 para os quadros da interface.
* (Histórico: o boot levava ≈ 4–5 minutos até o primeiro quadro, 243 s; hoje ≈ 2 minutos e 1 s com o snapshot.) Toque, rotor e teclas ainda não chegam ao HMI do RSE (no-op); só há aba de logs e telefone, como no iDrive 8.
* Rebuild dos binários do guest: `src/mgu/build.sh` e copiar para `idemu/guest7/`; `glhost7` vai em `bin/`.

### iDrive 7: toque no HMI do RSE (2026-11-08)

O toque (clique e arraste na imagem, ou pelo celular) agora chega ao HMI do RSE: tocar na aba do carro na barra lateral troca a aba selecionada. Verificado com o ambiente `idrive-7-rse`: o destaque saiu de "mídia" e foi para o "carro" (a área central continua com os blocos vazios: os aplicativos não têm dados).

Caminho de ponta a ponta:

1. **Mac → guest.** `Mgu7Runtime.touch` (`idemu/mgu7.py`) escreve linhas `d X Y` (desce), `m X Y` (move) e `u` (sobe) num socket que o QEMU liga à **primeira porta serial** (`ttyS0`; antes era `-serial null`). Coordenadas em pixels da tela (1920×1080).
2. **Compositor.** `idemu-wl` (`src/mgu/wlstub.c`) abre `/dev/ttyS0` em modo cru, lê as linhas e envia ao HMI `wl_pointer.enter` / `motion` / `button` (BTN_LEFT) na superfície IVI dele. O RAMSES do RSE só trata ponteiro (não há `wl_touch`); ele anuncia "Pointer available" ao registrar o `wl_seat`.
3. **HMI.** `CHmiWindowInputHandler::mouseButtonDown/Up` (o caminho de simulação em mesa) vira `CTouchData` (`src=1`) e entra em `CTouchDataClient::forwardTouchData`. Daí em diante é o mesmo código do iDrive 5 e 6 (`docs/TOQUE.md`).

Três coisas impediam o toque de chegar aos widgets, nesta ordem. As três viram **patches binários do `HmiMain3D`** (`tools/mgu/patch_rse.py`, `HMI_PATCHES`, offsets válidos para a versão 030_016_002; o script confere os bytes antes de gravar):

| # | Onde | O que acontecia | Patch |
|---|---|---|---|
| 1 | `0x6e8777b`, em `CTouchDataClient::forwardTouchDataSync` | Log "forwardTDSync: not forwarding data (false)": o serviço de toque não achava o dispositivo habilitado e não encaminhava aos ouvintes | `jne` sempre salta para o encaminhamento |
| 2 | mesmo trecho | O `CTouchData` vindo do mouse tem o byte `send` (`+0x20`) em 1; o reconhecedor de gestos trata todo evento como início (mesma causa do iDrive 6, `docs/TOQUE.md`) | zera o byte antes de encaminhar |
| 3 | `0x653b4d0`, `IHmiTouchService::isEnabled(bool)` | `CGestureRecognizer2` (`0x659a6d0`) descartava todo evento porque `isEnabled(1)` dava falso (o byte `+0x49` do serviço fica em 0) | a função devolve 1 |

Como isso foi achado (útil para o próximo passo):

* **Binário completo.** O leitor de ext4 do projeto (`tools/mgu/ext4ls.py`) devolve **zeros** nos arquivos grandes (extents com índice): o `HmiMain3D` extraído por ele tinha só 5 MB úteis. Use `tools/mgu/har.py pacote destino '^/usr/bin/HmiMain3D$'` (pacote `swfl_0000567a`).
* **Depurador pelo gdbstub do QEMU.** O QEMU roda com `-gdb tcp:127.0.0.1:PORTA` (a PORTA está na linha de comando do `qemu-system-x86_64`). Um cliente RSP mínimo (`m`, `M`, `g`, `Z0`/`z0`, `s`, `c`) basta para pôr breakpoints por endereço virtual do processo (base = primeira linha de `/proc/PID/maps`), ler registradores e memória e **gravar código** (`M endereço,tamanho:hex`) com a VM rodando. Para testar um patch ao vivo, grave com `M` e só depois leve para o `patch_rse.py`. Cuidado: ao retomar de um breakpoint é preciso remover o breakpoint, dar um `s` (passo), reinserir e só então `c`; e deixar sempre a VM em `c` ao sair (VM parada trava o console do guest).
* **Log do HMI.** O `HmiMain3D` tem opções próprias `-Lo console` (log em stdout, vai para `/tmp/hmi.log`), `-Ldl=verbose` (nível; só minúsculas) e `-Ls nível escopos`. Com `-Ldl=...` sem `-Lo` o log do DLT some. O nível `verbose` mostra a travessia de widgets (`CWidgetIntersector`), mas deixa o boot bem mais lento.
* **`POST /api/guest/run {"cmd":"..."}`** (só iDrive 7, depuração): roda um comando no shell do guest e devolve a saída.

### iDrive 7: a tela central (HU_HMI) desenha (2026-11-08)

Sem `-r=`, o `HmiMain3D` sobe como **HU_HMI**, a tela central de 1920×720. Cada ambiente iDrive 7 emula uma das duas telas (`role` no `env.json`: `hu`, o padrão, ou `rse`; `Mgu7Runtime.role`, argumento `idemu.role=hu` na linha de comando do kernel, `IDEMU_MGU7_ROLE` força um papel). Verificado no ambiente `idrive-7-rse`: o menu inicial aparece com Mídia/Rádio ("No active entertainment source"), relógio com a hora do Mac, "Communication", a barra lateral (mídia, comunicação, carro, ConnectedDrive) e, tocando no carro, a página "Driving information / Vehicle status / Settings" com o modelo 3D.

O que foi preciso (nesta ordem):

1. **Serviços SOME/IP do head unit que não existem no RSE.** O `CDevCarPowerMode` do HMI esperava `Lifecycle`, `VehicleCondition` e `Key` (`available: false`, `sendStatusInfotainment ... NOT_AVAILABLE`). `src/mgu/fakesvc.c` (`idemu-fakesvc`) os oferece ao `vsomeipd` pelo mesmo protocolo local de `src/mgu/lifecycle.c`, mas **dirigido por tabela**: `tools/mgu/gen_fakesvc.py` lê `someip-interfaces.json` e gera `/etc/idemu/fakesvc.tab` (serviço, instância, e para cada campo getter/setter/notificador, grupo e valor serializado: enum com `enumWidth` bytes, struct sem campo de tamanho, `bitWidth` empacotado). Os valores vêm do `defaultValue` do JSON; `campo=hex` troca um deles (`mgu7.FAKE_SERVICES`: `powerStateDetailed=63` = FULL_ON_USER_ON, `rseLock=03` = FULL_ACCESS). Setters do HMI gravam o valor e notificam os assinantes; chamadas e assinaturas ficam em `/tmp/fakesvc.log` do guest. Linhas `set <campo> <hex>` no FIFO `/run/fakesvc.ctl` mudam um valor ao vivo.
2. **Política de segurança do vsomeip.** O roteador recusava a oferta ("vSomeIP Security: Client ... UID/GID=10007/10007 isn't allowed to offer service/instance b015/1 ~> Skip offer!", visível no DLT do guest: `strings /tmp/dltraw | grep vSomeIP`). Não basta a política do usuário em `etc/vsomeip/10007_10007/vsomeip_security.json`: a política também tem de estar no arquivo **global** `etc/vsomeip/vsomeip_security.json`. `mgu7.allow_fake_offers` acrescenta as ofertas nos dois (o `idemu-fakesvc` roda como `sin_nsm`, uid 10007).
3. **Relógio.** O HMI lê a hora do `KombiIF` (serviço `0xb51b`, campo `statusShowTimeDate`: hora, minuto, segundo, dia, dia da semana 1 a 7, mês, ano em 2 bytes, status). O init manda `set statusShowTimeDate ...` a cada 5 s com a hora do guest, que é a do Mac (`-rtc base=localtime`).
4. **Tamanho da tela.** `idemu-wl` lê `IDEMU_WL_SIZE=1920x720` (o init o define para o papel `hu`).

Hoje o `idemu-fakesvc` oferece 22 serviços (Lifecycle, Key, VehicleCondition, KombiIF e KombiInterface_2, Vehicle, Climate, FrontCCU, TPMS, Efficiencytainment, CenterStack, MDrive, Charging... com valores "sem sinal"). O HU_HMI pede cerca de **165** serviços (`strings /tmp/dltraw | grep 'REQUEST('` dá a lista com id e instância; `someip-interfaces.json` dá o nome): os que faltam são os de mídia (`MediaPlayer`, `MediaBrowser`, `TunerFmAmDab`...), telefone (`VoiceCall`, `ContactBook`, `CallList`), navegação (`MapControl`, `GPSData`), `HMIControl`, `PrivacySettings`, `CarPlayManager` etc. Para acrescentar um: pôr o nome (ou o id `0x...` quando o nome se repete) em `mgu7.FAKE_SERVICES` e reconstruir a imagem (≈ 25 s); não precisa recompilar o C.

**O `KombiIF` é o canal do cluster e do HUD no iDrive 7.** Os setters que o HMI chama nele (`extendedCCMessage`, `standardCCMessage`, `kombiSelection`, `hudSelection`, `operationBordcomputer`, `statusWelcomeAnimation`...) aparecem no `/tmp/fakesvc.log`: é onde um painel de instrumentos virtual do iDrive 7 poderia ler o que o HMI manda (como na aba "Cluster e HUD" do iDrive 5 e 6).

Limites atuais: o HU_HMI mostra o menu inicial e as páginas do carro, mas mídia, telefone, navegação e ConnectedDrive não têm serviço por trás; no momento em que isto foi escrito cada transição de página levava uns 10 s; hoje leva menos de 2 s (ver "iDrive 7: velocidade, boot rápido e editor de codificação", no fim).

**Rotor e botões.** O `idemu-wl` também entrega teclas (`k CÓDIGO 0|1` na mesma serial → `wl_keyboard`; o RAMSES converte o código do Linux sem precisar de keymap). O HMI trata o teclado em `CHmiWindowInputHandler::keyboardPressed` e gera o mesmo evento de controlador que o hardware (`CHmiHomeApplication::controllerEvent: KeyCode=N`). Mapa medido (varrendo os códigos de tecla e lendo o log): F5 = 1 (MENU), Backspace = 2 (BACK), O = 3 (OPTION), F1 = 4 (MEDIA), F2 = 6 (COM), Espaço = 8 (PUSH), setas e WASD = 9 a 12 (inclinar), M = 13 e N = 14 (girar à direita e à esquerda). Outras teclas dão 17 (F4), 52 a 56 (I, U, P, J, ...). Não há tecla para MAP (5) nem NAV (7). Em `Mgu7Runtime.key` e `rotor` (`KEYS`); tocar com a seta à direita levou o foco para o bloco Mídia/Rádio (moldura laranja). O código da interface web é o mesmo do iDrive 5 e 6 (`idemu/web/run.js`).

Reproduzir o experimento no ambiente em execução (guest): matar o HMI e subir `idemu-run hmi_5000 /usr/bin/HmiMain3D -ro=/mnt/dataro/data/hmi -ibaroot=/mnt/iba/ibaroot -nfsrw=/mnt/share/hmi -bsc -lm=ramses_thread` com `LD_LIBRARY_PATH=/usr/lib/hmi:/usr/lib` e `XDG_RUNTIME_DIR=/run/wayland`.

## iDrive 7: velocidade, boot rápido e editor de codificação (2026-11-08)

Medido no mesmo Mac (Apple M1 Max), antes e depois:

| | antes | depois |
|---|---|---|
| Primeiro boot até o menu | 237 s | ≈ 113 s |
| Boot seguinte (snapshot) | 237 s | **1,2 s** |
| Trocar de página (a que carrega recursos) | 30 a 45 s | menos de 2 s |
| Quadros na interação contínua (setas, 20 s) | < 1 por segundo | 17,7 por segundo em média, pico de 29 a 45 |
| Relógio (`clock_gettime`) no guest | 15 µs | ≈ 0,1 µs |

### Onde o tempo ia

Observando o guest (amostrador de RIP pelo gdbstub do QEMU, `top`, estados das threads do HMI) e o `glhost7` (`GLHOST7_PROF=1` imprime por operação: quantidade, bytes, tempo no GL e chamadas síncronas): durante uma troca de página **tudo ficava ocioso**, guest a 95% e host a 0%. Três causas:

1. **O canal gráfico era a serial `ttyS1`.** 806 KB/s de vazão (o 8250 emulado move 1 byte por acesso a porta de E/S) e 1,4 ms por ida e volta. O boot manda **49,6 MB** (30 MB de texturas, 19 MB de buffers) e 1742 chamadas síncronas: ≈ 65 s só nisso, e a thread de renderização gastava 145 s de CPU de sistema em `write`. O GL no Mac somava 0,27 s: não era o gargalo.
2. **O relógio do guest é o HPET** (o kernel 4.14 do MGU não registra o TSC sob TCG): cada `clock_gettime` vira um syscall e um acesso MMIO ao QEMU, 15 µs. `read_hpet` era metade do tempo ocupado do guest. `clocksource=tsc tsc=reliable` trava o boot.
3. **O init esperava com `sleep` fixos** (35 s) e só então iniciava o HMI, que sozinho leva ≈ 45 s para carregar o binário de 170 MB.

### O que mudou

* **Anel em memória compartilhada** no lugar da serial. O Homebrew não tem `ivshmem` no macOS e o kernel do guest não tem virtio, `/dev/mem` nem driver para nada que sirva, então o IDEmu leva o **QEMU 11.1.2 com um dispositivo novo**, `idemu-shm` (`src/qemu/idemu-shm.c`, receita em `tools/qemu/build.sh`): um BAR PCI apoiado num `shm_open()`. O guest o mapeia por `/sys/bus/pci/devices/0000:00:03.0/resource0` (o init dá `chmod 666`, o HMI não é root) e o `glhost7` mapeia o mesmo objeto (`shm:/idemu-gl-PID-N`). Protocolo: o mesmo fluxo de bytes da serial (`src/mgu/proto.h`) em dois anéis, comandos guest→host de 64 MB e respostas host→guest de 4 MB, índices de 64 bits donos de um lado só, cercas de memória explícitas (o x86 é TSO e o host é ARM). Sem o dispositivo a `libGLESv2` do guest cai sozinha na serial. O guest gira (`pause`) esperando respostas em vez de dormir: `usleep(100)` dura 1,3 ms no guest.
* **`libfastclock.so`** (`src/mgu/fastclock.c`, `LD_PRELOAD` no HMI e nos serviços): `clock_gettime` e `gettimeofday` pelo `rdtsc`, recalibrados contra o relógio real a cada 500 ms, nunca andam para trás.
* **Init em paralelo** (`tools/mgu/idemu-init.sh`): `waitf`/`waitclients` no lugar dos `sleep`. O HMI começa em 6 s em vez de 42 s. `echo 1 > /proc/sys/kernel/printk`: o 8250 do console imprimia "too much work for irq" sem parar.
* **Quadro RGBA direto**: `GET /api/run/frame?fmt=rgba` entrega o que o `glhost7` grava (alfa já opaco), sem converter para RGB no servidor e de volta no navegador. O estado passa a `running` no primeiro quadro (antes esperava o segundo, que só vinha no próximo tique do relógio).
* **A imagem se refaz sozinha** quando o init, o overlay, os binários do guest ou os patches mudam (`mgu7/stamp`, `guest_stamp()`): antes o `build` só conferia se `root.img` existia.

### Boot rápido (snapshot)

Depois do primeiro boot, com a tela parada há 4 s (e ao menos 15 s de `running`), o IDEmu pausa a VM por alguns segundos e grava `<ambiente>/snapshot/`:

* `disk.qcow2`: o disco de escrita (agora um qcow2 sobre `mgu7/root.img`, no lugar de `snapshot=on`) já com o estado da VM dentro (`savevm idemu`, pelo monitor HMP em `run/mon.sock`).
* `gl.rec`: todo o fluxo GL que o `glhost7` recebeu desde o início do boot (≈ 57 MB), gravado com `GLHOST7_REC`. É o jeito de recriar no Mac os objetos do OpenGL, que não fazem parte da VM.
* `meta.json`: carimbo da imagem, do QEMU, do papel e da codificação. Qualquer diferença invalida o snapshot.

Ao iniciar: `qemu -S -loadvm idemu` sobre uma cópia (APFS clone) do `disk.qcow2`, `glhost7 --replay gl.rec` reexecuta o fluxo (sem ler quadros, só o último) e adota o anel nos índices que a VM salvou, e então `cont`. O relógio do guest é acertado com `date -s`. **Uma nova gravação de codificação apaga o snapshot.** `fast_boot: false` no ambiente (a caixa "Fast boot") e "Full boot" na lista de ambientes funcionam como no iDrive 6; precisa do `qemu-img` (vem com o `brew install qemu`).

O ponto seguro para gravar é uma fronteira de mensagem: o `glhost7` marca `host_idle` no cabeçalho do anel quando espera um comando novo e o Python só salva com o anel vazio e `host_idle = 1`.

Duas correções do QEMU que o snapshot exigiu (ver `src/qemu/README.md`): o bloco de RAM do BAR precisa de nome (`vmstate_register_ram`), senão não entra no `savevm`; e o `sdhci-pci` não grava o espaço de configuração PCI (BARs), então depois do `loadvm` o cartão SD respondia erro de E/S.

Variáveis de ambiente: `IDEMU_NO_SHM=1` (usa a serial), `IDEMU_NO_SNAPSHOT=1` (sem boot rápido), `IDEMU_QEMU_X86` (outro QEMU), `IDEMU_QEMU_IMG`, `IDEMU_PROF=1` (perfil do `glhost7` em `logs/renderer.log`).

Limites: o snapshot é do boot, não de onde você parou; o `qemu-system-x86_64` do IDEmu depende das bibliotecas do Homebrew (glib); sem o dispositivo `idemu-shm` o boot volta aos ≈ 4 minutos.

### Editor de codificação do iDrive 7

A aba Coding, que já existia para o iDrive 5 e 6, agora abre também para o iDrive 7 (1.288 parâmetros editáveis, grupos por área, popular, busca, backups, exportar/importar, redefinir). Gravar reinicia a VM (≈ 2 min, pois apaga o snapshot) e o IDEmu confere no console do guest que o bloco chegou.

Como o HMI guarda a codificação, descoberto lendo o binário (`HmiMain3D` 030_016_002; `tools/mgu/gen_coding7.py`):

* **Memória `rawcodingdata`** (4144 bytes, criada pelo `CodingShmApp` em `/dev/shm`). O byte `0x28` é o estado: bit 3 = bloco presente; bit 0 = dados reais a partir de `+0x2c`; bit 1 ou 2 sem o bit 0 = a codificação padrão compilada no HMI (é o que o `CodingShmApp` deixa sem bloco: `0x0a`). `libcoding.so` só lê: `getBits(byte, máscara, deslocamento)` em `dados[posição da área + byte]`.
* **16 áreas** (`0x3000` a `0x3010`: `HMI_SPEECH`, `CONNECTIVITY_A4A`, `AUDIO_BROADCAST`, `TELEMATICS`, `SYSTEM_CONFIGURATION`, `APIX_CID_UND_ZIN`, `NAVIGATION`, `ENTERTAINMENT`, `FES`, `EFFICIENT_DYNAMICS`, `SARAH`, `PARKEN`, `TOUCH_COMMAND`, `KOMBI_HUD`, `LANGUAGE`, `M_GMBH`), cada uma com posição e tamanho fixos (HU: 0, 151, 301... até 2172 bytes; o RSE tem as mesmas áreas deslocadas de 6 a 7 bytes). Vêm de um `switch` na fábrica de objetos do HMI.
* **Dicionário** (`CVACoding`): 5590 entradas de 56 bytes `[nome, A, B, valor, 0, 0, 0]`, `A` = área | byte inicial << 16 | byte final << 32, `B` = máscara | número do valor << 8. Os valores de fábrica são um vetor de bytes no próprio binário (HU em `0x82d6880`, RSE em `0x82d5d60`).
* **Aplicar**: o Mac manda o bloco pela serial de entrada (linhas `c DESLOCAMENTO HEX`, tratadas pelo `idemu-wl` em `/run/coding.bin`), e o init o escreve em `rawcodingdata` (`dd`, estado `0x09`) **antes** de iniciar o HMI. Só vale para a versão `030_016_002`: `gen_coding7.py` confere a estrutura e falha se ela mudar.

**O toque na tela central depende da codificação.** Com a codificação de fábrica do HMI (tudo desligado) o toque chega ao HMI e não faz nada; com `CID_TOUCH`, `ZBE_TOUCH`, `CID_TOUCH_SL`, `CID_HMI_TOUCH` e `CID_TOUCH_PROXIMITY` ligados o menu responde (e aparecem itens como "Screen Mirroring"). Um ambiente novo da tela central já nasce com esses cinco (`coding7.DEFAULT_HU`).

Ferramentas de diagnóstico que ajudaram, para a próxima vez: amostrar o RIP de todas as vCPUs pelo gdbstub (`qfThreadInfo`, `Hg<n>`, `g`) e resolver com `/proc/kallsyms` do guest; ler o log DLT com carimbo de tempo (`/tmp/dltraw`, mensagens `ECU1`, tempo em décimos de milissegundo); `POST /api/guest/run` para comandos no guest.

### iDrive 8: editor de codificação (2026-11-09)

A aba **Coding** agora abre para ambientes iDrive 8, com 1.264 parâmetros do CAF `infotainment` (os que o `Hmi8` pede por `cod_get_flag`).

* **Dicionário** (`tools/mgu/gen_coding8.py` → `mgu22/coding8.json`, ~220 KB): nome, id, opções do enum, valor de fábrica e seção de cada parâmetro. Vem do esquema `cafd_mgu_02_a.bin` (nome, id, enum) e do `MGU22_Coding.txt` (valor do G70BEV e a seção, como `HMI`, `ENTERTAINMENT`, `EXBOX_COMFORT`). `build_image.py` o gera junto com a imagem; `coding8.ensure()` o extrai sozinho em ~6 s (precisa da PSdZData) se faltar. Ficam de fora `IS_CODED` e `CAF_VERSION_*`, e os CAFs `cluster`, `ioc` e `dac`, que repetem os mesmos ids para outras centrais (445 ids em comum; `gencoding.py` já dava prioridade ao infotainment). 983 parâmetros têm opções; os 281 sem opções aceitam qualquer inteiro de 0 a 2³¹−1.
* **Gravar** (`Server.flash`, mesmo caminho do iDrive 7): backup, guarda `coding.extra` no `env.json`, reinicia a VM. A cada partida `mgu._prepare_ram` põe no initramfs uma `coding.tab` do ambiente (a de fábrica, `mgu22/guest/coding.tab`, com os ids alterados). O `libcod.so.0` do guest responde `cod_get_flag` com ela, e o `guest_boot.sh` imprime `== coding applied N` (N = linhas); a gravação confere N (3.845 hoje). Sem mudanças vale a tabela de fábrica da imagem. Não há snapshot no iDrive 8, então o reinício leva só o boot normal (~25 s).
* **Verificado** no ambiente `idrive-8-g70`: `DEVELOPER_MENU=0` + reset → o menu **All apps** perde "Developer Info" e "Color Configuration"; voltar ao padrão traz de volta. `CID_TOUCH=0` **não** desliga o toque no iDrive 8 (o toque entra pelo `uinput` e o HMI não olha esse parâmetro), ao contrário do iDrive 7.
* Os valores de fábrica do dicionário batem com a tabela que o `libcod` já lia (teste `tests/test_idrive8_coding.py`).
* Limite: o efeito de cada parâmetro depende dos serviços que o HMI encontra; muitos parâmetros `EXBOX_*` só aparecem com a central de carroceria, que não existe aqui.

### iDrive 7: SSH (2026-11-10)
O shell do guest (`ttyS2`, o mesmo em que `run_guest` roda comandos) agora também vira `shell.sock` (`runtime.ConsoleMux`: o chardev do QEMU só aceita um cliente, então o `_console_thread` é quem alimenta os clientes) e a aba **SSH** abre uma sessão `root`:
`ssh -F <ambiente>/ssh/ssh_config idemu 'uname -sr'` → `Linux 4.14.300-apl`, 0,2 s por comando, também com o boot rápido (snapshot). Sem rede no guest: nada de scp/sftp (`idemu push/pull` pelo shell).

### iDrive 7: relógio parado no boot rápido (2026-11-10)
Com um snapshot antigo o relógio do HMI aparecia parado (hora do snapshot) e depois como `--:--`: no guest restaurado **não havia o processo `idemu-fakesvc`** (quem alimenta o relógio,
`KombiIF.statusShowTimeDate`, a cada 5 s pelo init, e os serviços do carro). Numa partida a frio o processo vive e o relógio anda; o snapshot de 2026-11-09 foi tirado depois que ele sumiu e congelou o problema
em todo boot rápido. Agora `_take_snapshot` confere (`ps`) se o `idemu-fakesvc` está rodando e, se não estiver, adia o snapshot para o próximo boot (as mensagens vão para o log do app).
Verificado: snapshot novo → boot rápido em 1,6 s, `idemu-fakesvc` vivo, o contador de `set statusShowTimeDate` no `/tmp/fakesvc.log` sobe de 26 para 30 em 20 s e o HMI mostra a hora certa.
Cuidado ao depurar: `echo ... > /run/fakesvc.ctl` **trava o shell** do guest quando o processo não existe (abrir um FIFO só para escrita espera um leitor); use `1<>/run/fakesvc.ctl`.

**Dados do carro (não feito, mas o caminho existe):** o `idemu-fakesvc` aceita `set <campo> <hex>` ao vivo em `/run/fakesvc.ctl` e o pacote traz o `someip-interfaces.json` (689 interfaces, com os
tipos de cada campo). Campos que valem tentar: `TPMS.statusTyrePressure`/`statusTyreTemperature` (4 × UInt16), `CDS.statusGearIndicator`, `statusEngineSpeed2`, `statusHandBrake`,
`statusEngineTemperature`, `KombiIF.timeDateUTC`. Falta saber a escala e em que tela do HMI aparecem (o toque na tela central depende da codificação, e as setas do controlador não
saíram do cartão MEDIA no teste). Obtenha o JSON com `ssh ... cat /etc/oap/someip/someip-interfaces.json` (o leitor `ext4ls.py` devolve zeros no fim desse arquivo).
