# IDEmu no Windows (nativo) — todas as gerações

O IDEmu roda no Windows **sem WSL**: o servidor é o Python do Windows, o QEMU é um `qemu-system-arm.exe` (QEMU 11.1.2 + a placa `omap5-uevm`, compilado com MSYS2/MinGW-w64) e o renderizador é um `glhost.exe` (OpenGL do Windows via freeglut + GLEW). A interface é a mesma, no navegador. O macOS não muda: tudo que é de Windows está em `windows/`, `IDEmu.bat`, `idemu/ipc.py`, `idemu/hostos.py` e em blocos `#ifdef _WIN32`.

> **Estado testado (Windows 10 LTSC 21H2, Xeon E5-2673 v3, 16 GB, Radeon RX 6650 XT):** foi compilado e executado de ponta a ponta nesta máquina.
>
> | Geração | Resultado |
> |---|---|
> | iDrive 6 (NBT Evo) | **funciona**: criar, compilar (~1 min), boot a frio (~3 min), HMI com os tiles, rotor/botões respondendo |
> | CIC | **funciona**: boot ~2 min, Hauptmenü, rotor respondendo |
> | iDrive 7 | **funciona**: boot a frio ~4 min (TCG), HMI real (Media/Radio, Comunicação) em 1920×720, rotor respondendo |
> | iDrive 8 | **boot a frio, tela 2880×960 e toque verificados em outro PC**, com Windows 10 22H2 x64, Core i9-13900HX, GeForce RTX 4060 Laptop e firmware G70 `007_023_004` |
>
> Se algo falhar, mande a saída do `windows\Build.ps1` e o `renderer.log` / `qemu.log` do ambiente (`environments\<id>\logs`). Rodar a suíte de testes (`python -m unittest discover -s tests`) dá `OK` no Windows (os testes que dependem de `sh`, `openssl` ou symlink são pulados).

| | macOS | Linux | Windows nativo |
|---|---|---|---|
| iDrive 5 / 6 (NBT Evo) | sim | sim | **sim** (foco) |
| iDrive 7 (MGU x86-64) | sim | não | **sim**, sempre boot a frio (~2 min) |
| iDrive 8 (MGU22 aarch64) | sim | não | **sim, mas lento**: em PC x86 o guest roda em TCG (sem HVF) |
| CIC (SH-4A) | sim | não | **sim** (boot ~1 min) |
| Boot rápido (snapshot) | sim | desligado por padrão | desligado por padrão (`IDEMU_FASTBOOT=1` experimenta) |
| SSH na head unit | sim | sim | não: o console do guest fica numa porta TCP local (aparece no log do console) |
| Abrir | `IDEmu.command` | `linux/IDEmu.sh` | `IDEmu.bat` |


## Todas as gerações: o que compilar e o que cada uma exige

`windows\Build.ps1` (padrão `-Step all`) compila tudo; `-Step core|cic|mgu7|mgu8` compila uma geração só (leva 15 a 60 min por QEMU: são quatro, `arm`, `sh4`, `x86_64` e `aarch64`, cada um numa árvore de fonte própria em `~/idemu-qemu`).

| Geração | Binários em `bin\` | Observações |
|---|---|---|
| iDrive 5/6 | `qemu-system-arm.exe`, `glhost.exe` | foco; boot completo ~25–45 s |
| CIC | `qemu-system-sh4.exe` | placa SH7785 própria; CIC_INPUT/CIC_OUTPUT viram UDP em loopback; quadro em `CreateFileMapping`; boot ~1 min. Se `-machine help` não listar `cic`, tire `--without-default-features` do configure em `tools/qemu/build-sh4-windows.sh` |
| iDrive 7 | `qemu-system-x86_64.exe`, `glhost7.exe`, `bin\qemu-share\` | RAM compartilhada guest↔glhost7 por mapeamento nomeado do Windows (`idemu-shm` com `memory_region_init_ram_ptr`); precisa de **OpenGL 4.1 core** (driver da placa); sempre boot a frio (~2 min, a caixa "Fast boot" fica inativa); a imagem usa ~3,3 GB + 4 GB esparsos e é bem mais lenta com o Defender (exclua `mgu7\` e a pasta temp); NTFS não guarda symlink nem modo rwx: o IDEmu os anota em `.idemu-meta.json`. `IDEMU_MGU7_ACCEL=whpx` é experimental (provável pânico do kernel) |
| iDrive 8 | `qemu-system-aarch64.exe` (com `memory-backend-winshm`), `mguhost.exe` | precisa do **ANGLE** (`libEGL.dll`/`libGLESv2.dll`/`d3dcompiler_47.dll` de 64 bits): o IDEmu procura no Edge/Chrome; sem eles, aponte `IDEMU_ANGLE` para a pasta de qualquer app Chromium/Electron/CEF (ex.: `C:\Program Files (x86)\Steam\bin\cef\cef.win64`; é só leitura). Para compilar o guest (ELF aarch64) usa clang do MSYS2 + o `zig ld.lld` (o `ld.lld` do MSYS2 só liga PE): o `Build.ps1` baixa o Zig para `C:\zig` (com checksum). **PSdZData:** use os três `swfl` e os três `swfk` da mesma versão (`007_034_003` ou `007_023_004`). **RAM do guest:** o mapeamento de 12 GiB usa um arquivo temporário no volume de `%TEMP%`. Deixe 12 GiB livres nesse volume. **Desempenho:** em PC x86 o guest aarch64 só roda em TCG: boot de minutos e interface lenta; só Windows on ARM (WHPX, não validado) deve chegar perto do Mac. `IDEMU_MGU_ACCEL` e `IDEMU_MGU_CPU` mudam isso |

Para montar somente o guest do iDrive 8, pode-se definir `IDEMU_MGU_ZIG` com o caminho do `zig.exe` (testado com Zig 0.15.2). Essa opção compila o guest ARM64. O `mguhost.exe` e o QEMU aarch64 devem estar em `bin\`, gerados pelo passo `mgu8`.

O que o primeiro teste real corrigiu (já no código): extração dos QEMU sem symlink (`--exclude` de `roms/` e `tests/lcitool`, `scripts/symlink-install-tree.py` neutralizado), `libfdt` interno (o MSYS2 MINGW64 não tem o pacote `dtc`), `memory-backend-winshm` registrado no esquema QAPI (`qapi/qom.json`, senão `-object` o recusa), `con.sock` renomeado para `cons.sock` (`CON` é dispositivo reservado no Windows e abrir `con.sock.port` lia o teclado), `longjmp` do `glhost7` trocado pelos built-ins do GCC (o do UCRT quebrava com violação de acesso), caminhos do guest sempre com `posixpath`, pasta de trabalho curta `C:\iw\<ambiente>` na compilação do iDrive 5/6 (os SWFL têm caminhos de ~200 caracteres e o limite do Windows é 260), e ponteiros de 64 bits no `glhost`.

Riscos que ainda existem: a detecção de canais do `mguhost` por `QueryWorkingSetEx` (se falhar, ele varre os 12 GiB) nunca foi exercitada com um guest real; ANGLE/D3D11 no lugar do Metal só foi testado até a inicialização; shaders do iDrive 7 em GPUs Intel/NVIDIA (testado só com AMD Radeon); e os patches do CIC dependem do texto exato do QEMU 11.1.2.
## Requisitos

* Windows 10 (build 17134 / versão 1803 ou mais novo, por causa dos sockets) ou Windows 11, 64 bits.
* **Driver OpenGL da placa de vídeo** (NVIDIA/AMD/Intel): o `glhost` precisa de framebuffer objects. Sem driver (VM, Escritório Remoto) o Windows só tem OpenGL 1.1 e o `glhost` avisa e sai; nesse caso instale o Mesa para Windows (opengl32.dll do llvmpipe) ao lado do `glhost.exe`.
* ~10 GB livres para compilar (MSYS2 + QEMU) e 8 GB de RAM ou mais (a VM usa 2 GB).
* Seus **próprios** pacotes SWFL (PSdZData). Para o iDrive 6: `swfl_00002719`, `swfl_0000271a` e `swfl_00002720` (versão 007_051_002) e a pasta `mainseries`.
* Python 3.10+ (só para rodar a partir do código-fonte; o `.zip` pronto já traz o Python).

## Caminho 1 — compilar do código-fonte

PowerShell na pasta do projeto:

```powershell
# uma vez: compila QEMU + glhost (15 a 60 min). -InstallMsys2 instala o MSYS2 se faltar (winget, ou o instalador oficial assinado quando não há winget).
powershell -ExecutionPolicy Bypass -File windows\Build.ps1 -InstallMsys2
# depois, sempre:
.\IDEmu.bat
```

O `Build.ps1` usa o MSYS2 em `C:\msys64` (`-Msys2Root` muda), instala os pacotes (`windows/build-native.sh`), baixa o fonte oficial do QEMU 11.1.2 para `~/idemu-qemu` dentro do MSYS2 (`tools/qemu/build-arm-windows.sh`), compila `src/glhost` (`build.sh`, ramo MinGW) e copia as DLLs necessárias para `bin\`. Partes avulsas: `-Step deps|qemu|glhost|dlls`.

## Caminho 2 — pacote pronto (sem instalar nada)

Depois do Caminho 1, em quem compilou:

```powershell
powershell -ExecutionPolicy Bypass -File windows\Package.ps1     # gera dist\IDEmu-windows-x64.zip (Python embutido + bin + DLLs)
```

Quem recebe o `.zip` descompacta e dá dois cliques em `IDEmu.bat`. O pacote não leva firmware nem imagens: cada pessoa usa os próprios SWFL.

## Usando

`IDEmu.bat` sobe o servidor e abre `http://127.0.0.1:8765`. Na interface: **Novo ambiente → iDrive 6 → modelo → Procurar pasta…** (seletor do Windows; escolha a pasta com os SWFL) → **Criar → Compilar → Iniciar**. Feche a janela do launcher (ou Ctrl+C) para encerrar; o QEMU e o `glhost` morrem junto (ficam num *job object*).

Opções do launcher (`windows\IDEmu.ps1`): `-Port 9000`, `-NoBrowser`, `-FastBoot` (experimental), `-ShowWindow` (mostra a janela do renderizador, para diagnóstico).

Os ambientes (VMs) ficam em `environments\` dentro da pasta do IDEmu; o espaço temporário da execução, em `%TEMP%\idemu-<usuário>\<ambiente>`.

## Como o Windows é diferente por dentro

| Assunto | macOS / Linux | Windows nativo |
|---|---|---|
| IPC | sockets unix (`gl.sock`, `input.sock` datagrama, `ser*.sock`, `qmp.sock`) | TCP/UDP em `127.0.0.1`: `idemu/ipc.py` reserva uma porta por ponto (arquivo `<nome>.port`) e o `glhost` avisa que já escuta criando `gl.sock.ready` |
| Serial/QMP do QEMU | `unix:caminho,server,nowait` | `tcp:127.0.0.1:porta,server,nowait` |
| Ponte GL guest↔glhost | `omap5-uevm.c` conecta em `AF_UNIX` | conecta em TCP (`OMAP5_GLSOCK=127.0.0.1:porta`, `TCP_NODELAY`) |
| Quadro compartilhado | `mmap` de `frame.rgb` | `CreateFileMapping` no mesmo arquivo; o Python o mapeia de fora |
| CPU/RAM nas estatísticas | `ps` | `GetProcessTimes` / `GetProcessMemoryInfo` (ctypes) |
| Encerrar tudo | SIGTERM/SIGHUP | job object `KILL_ON_JOB_CLOSE` + SIGBREAK |
| Links de arquivo | `symlink` | `symlink` se permitido; senão junção (pasta) ou hardlink/cópia (arquivo) |
| Texto | UTF-8 | o `idemu` reinicia em `python -X utf8` (o padrão do Windows é cp1252) |

## Limites e pontos de atenção

* **iDrive 5/6 é a geração mais madura**; verifique `hmi_validated: true` no `build.json` do ambiente (HMI de referência 24-03, 1440×540).
* **Desempenho:** o QEMU usa TCG (CPU). O renderizador usa a GPU do Windows (mais rápido que o llvmpipe do Linux), mas o boot completo ainda leva ~25–45 s.
* **Sem SSH** (não há `sshd` sem privilégios no Windows). O console do guest (`shell.sock`) escuta em `127.0.0.1:<porta>` (a porta aparece no log do console): use `ncat`/PuTTY em modo *Raw*.
* **Boot rápido** desligado: restaurar snapshot (`-incoming file:`) ainda não foi validado no Windows.
* **Antivírus/Firewall:** o Windows pode perguntar se `qemu-system-arm.exe`/`glhost.exe` podem usar a rede; é só loopback (127.0.0.1), pode permitir só em redes privadas ou negar.
* **Testes:** `python -m unittest tests.test_ipc tests.test_hostos` valem no Windows; os demais testes de socket (`test_mapsvc`, `test_v850`, `test_ssh`, `test_cic_*`) exercitam o transporte unix e são para macOS/Linux.

## Alternativa: WSL2

Se preferir (ou se o build nativo falhar), o caminho antigo continua: `IDEmu-wsl.bat` roda o IDEmu **dentro do WSL2** (Ubuntu) e usa o navegador do Windows. Instale com `windows\Setup-wsl.ps1` (administrador); a primeira execução instala pacotes e compila dentro do WSL. Detalhes no cabeçalho de `windows\IDEmu-wsl.ps1` e em [LINUX.md](LINUX.md). Lá o SSH funciona (sshd do Ubuntu), a VM fica em `~/IDEmu/environments` e o `glhost` usa Mesa llvmpipe.

## O que mudou no código (para quem mantém o repositório)

| Arquivo | Mudança | Efeito no macOS/Linux |
|---|---|---|
| `idemu/ipc.py` (novo) | endereços/sockets/`chardev` do QEMU conforme o sistema | nenhum: no POSIX o endereço é o mesmo caminho de antes |
| `idemu/runtime.py`, `mapsvc.py`, `v850.py` | usam `ipc` no lugar de `AF_UNIX`/`os.getuid`/`ps`; `.exe` e job object no Windows | nenhum |
| `idemu/hostos.py` | seletor (PowerShell), Explorer, navegador, RAM, `proc_info`, `link_path`, `adopt_child` no Windows; WSL como antes | nenhum |
| `idemu/server.py`, `catalog.py`, `phone.py`, `stats.py`, `mgu.py`, `__main__.py` | links portáveis, `SIGHUP` opcional, `openssl` do PATH, `_posixshmem` opcional, UTF-8 | nenhum |
| `src/glhost/host.c`, `map.c`, `winport.h` | `#ifdef _WIN32`: winsock, `CreateFileMapping`, GLEW, `WSAPoll` | nenhum (blocos só do Windows) |
| `src/qemu/omap5-uevm.c` | `#ifdef _WIN32`: ponte GL por TCP | nenhum |
| `src/glhost/build.sh`, `tools/qemu/build-arm-windows.sh`, `windows/*` | build e launcher do Windows | arquivos novos / ramo novo |
