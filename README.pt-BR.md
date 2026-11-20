# IDEmu — emulador de head unit BMW iDrive 6 (NBT Evo)

Emulador baseado em QEMU (placa OMAP5 personalizada) que roda o software **original** da head unit
(QNX 6.5 + HmiMain3D) a partir dos pacotes SWFL do PSDZData, com interface gráfica própria, rotor iDrive,
barramento CAN virtual, GPS simulado e acesso SSH ao console da head unit virtual.

## Uso rápido

```bash
cd ~/Desktop/IDEmu
./IDEmu.command            # abre o IDEmu numa janela do Electron (precisa de: cd electron && npm install); sem Electron, abre no navegador
python3 -m idemu gui       # só o servidor + navegador (http://127.0.0.1:8765)
```

A interface abre em inglês; o seletor de idioma no topo troca para português do Brasil (os nomes em negrito abaixo são os dessa versão).

Na interface: **Novo ambiente** → versão do iDrive → modelo do carro (série/chassi/marca) → **arquivos necessários**
(a tela mostra o nome exato de cada arquivo SWFL e para que serve; **Procurar pasta…** abre o seletor do macOS, varre a pasta e escolhe sozinho,
ou escolha um por um: não precisa ter a PSdZData inteira) → idioma/país/VIN/display → **Criar** →
**Compilar** (≈ 20 s) → **Iniciar**. O primeiro boot leva ≈ 35–45 s e salva o estado do sistema; os seguintes levam ≈ 1 s.

Linha de comando equivalente: `python3 -m idemu list | build <id> | run <id> | gui`.

## O que é "não modificado"

* `sda.img` (sistema, QNX4) e `sdb.img` (dados do HMI, QNX6) são montados **somente** com arquivos dos SWFL
  (extração byte a byte; o único ajuste é omitir o que não cabe no disco em RAM e nomes > 48 caracteres,
  registrados em `build.json`).
* `boot.ifs` é o `boot1.ifs` do SWFL, reempacotado sem compressão, com o shell de login trocado por `ksh`
  (console serial), 26 ferramentas do próprio sistema acrescentadas e, no script de boot, sem o que só serve ao
  hardware real (driver de eMMC, logger do DSP, `starter`).
* Tudo que o hardware real faria e a VM não tem fica em **`shim.img`** (disco separado) e é aplicado em
  memória na partida: bibliotecas de tradução (EGL/GLES/screen/ILM/OTF → renderizador do Mac), tabela de
  codificação do carro, scripts de init e a lista mínima de serviços. As imagens do sistema nunca são
  alteradas — nem em disco, nem pelo guest (os discos são carregados na RAM).

## Componentes

| Pasta/arquivo | Função |
|---|---|
| `idemu/swfl.py` | leitor/extrator dos pacotes `.bin` do PSDZData |
| `idemu/ifs.py` | descompressão LZO e reempacotamento do IFS de boot |
| `idemu/qnxfs/` | gravadores de disco QNX4 e QNX6 (sem ferramentas da QNX) |
| `idemu/builder.py` | SWFL → `boot.ifs`, `sda.img`, `sdb.img`, `shim.img` |
| `idemu/codegen.py` | perfil de codificação (chassi, marca, idioma...) → tabela do guest |
| `idemu/coding.py`, `idemu/web/coding.js` | editor de coding: parâmetros do CAFD, valores de fábrica, backups e flash |
| `idemu/runtime.py` | sobe renderizador + QEMU, console, canais, CAN/GPS/SSH, boot rápido (snapshot) |
| `idemu/canbus.py` | CAN virtual: sinais, cenários, gravação/replay, servidor TCP |
| `idemu/gps.py` | GPS virtual: NMEA/UBX, rotas GPX, modos, servidor TCP |
| `idemu/sshbridge.py` | `sshd` real do macOS (sem root) → console do guest |
| `idemu/v850.py`, `idemu/most.py`, `src/v850/` | V850 virtual: o `io-ipc` original do SWFL fala com ele por uma UART virtual (ver `docs/V850.md`) |
| `idemu/v850fw.py` | lê o firmware do V850/RH850 e as tabelas de gateway dos pacotes SWFL (ver `docs/V850_FIRMWARE.md`) |
| `idemu/server.py`, `idemu/web/` | API HTTP e interface web (visual macOS com vidro líquido em `web/apple.css`, claro/escuro conforme o sistema) |
| `idemu/stats.py`, `idemu/web/stats.js` | **Estatísticas avançadas**: CPU, RAM (e teto), GPU, FPS, tempo de quadro e armazenamento da VM, com gráficos ao vivo |
| `bin/` | `qemu-system-arm` (QEMU 11.1.2 + placa omap5-uevm), `glhost`, shaders decompilados |
| `src/` | fontes: patch do QEMU, renderizador, shims do guest |

Documentação técnica: `docs/` (API.md, ARQUITETURA.md, V850.md, V850_FIRMWARE.md, CLUSTER_HUD.md).

## Coding

Botão **Coding** no ambiente: 1.333 parâmetros do CAFD lidos do próprio firmware, com grupo e valor de fábrica, mais uma lista "Popular" com nome e descrição. Altere, clique em **Flash to head unit**: o IDEmu faz um backup,
regrava a codificação, reinicia a head unit e confere que o HMI leu a tabela nova. Há backups (restaurar), exportar/importar e voltar ao padrão de fábrica. Exemplo testado: idioma da head unit para inglês.

## Seu carro pelo VIN, tipo de head unit e arquivos do sistema

* **VIN**: no assistente "Novo ambiente" (etapa 1) ou no botão **VIN** de um ambiente pronto. O código do tipo (caracteres 4–7) é lido da base KIS da sua PSdZData
  (`kiswb/*/KIS.data`, ~4.800 tipos, guardados em `cache/vin_types.json`) e vira chassi, carroceria, motor, ano-modelo, mercado e a geração do iDrive; o ambiente sai igual ao carro.
  O VIN não traz a lista de opcionais, então o tipo de head unit é escolhido à parte.
* **Tipo de head unit (iDrive 5/6)**: Navigation Professional (10,25" 1440×540, toque), Navigation Business (8,8" 1280×480) ou EntryNav (6,5" 800×480, só o controlador).
  A PSdZData traz só o firmware do HU_NBTEVO: os três usam esse firmware com a codificação de display, navegação e toque de cada unidade.
* **Arquivos**: o botão **Arquivos** descompacta os pacotes SWFL/HAR (ou a imagem montada do iDrive 8 e do CIC) em arquivos normais, que você navega no app,
  vê (texto, imagem ou hexadecimal), baixa ou abre no Finder.

## Estado e limites (resumo honesto)

Verificado de ponta a ponta neste Mac (F30/BMW, SWFL 007_051_002): criar ambiente → compilar a partir dos SWFL (≈ 20 s)
→ iniciar (≈ 35–45 s no primeiro boot, ≈ 1 s nos seguintes) → tela do iDrive em português com o carro do chassi escolhido → rotor/teclas → SSH (`ssh` com chave, comandos
com código de saída) → velocidade e consumo do CAN virtual aparecendo no tile "Meu Veículo" (via MOST) → posição do GPS virtual chegando ao HMI.

V850 virtual: o `io-ipc` e o `watchdog5-omap` originais já conversam com ele (aba V850; canais 0, 25 e 26). O `most` roda como servidor MOST local e o V850 registra os dispositivos do carro (Kombi, Vehicle); a **velocidade e o consumo médios do CAN virtual já aparecem no tile "Meu Veículo"** (`docs/V850.md`).
Toque na tela (clicar e arrastar) funciona no iDrive 5, 6 e 8 (`docs/TOQUE.md`).
A aba **Cluster e HUD** (iDrive 5 e 6) desenha o painel de instrumentos e o HUD com o CAN e o GPS virtuais (`docs/CLUSTER_HUD.md`). Em Novo ambiente, cada versão do iDrive mostra o seu nível de funcionalidade e você escolhe a pasta onde a VM fica.
Ainda **não** feito: as demais grandezas do carro no HMI (pneus, câmbio, combustível…),
mapa e rota (o PSdZData não traz dados de mapa), áudio, rede no guest, pen drive virtual (`docs/PENDRIVE.md`).
**CIC** (High, SH-4/QNX 6.3) também está no assistente: mostra a interface real do HMI e aceita rotor, aperto, inclinação e as teclas do controlador; o HMI fala o idioma do ambiente (12 idiomas) (`docs/CIC.md`).
**CIC, iDrive 7 e 8** também são gerações do assistente. Para elas o app lista os arquivos SWFL exigidos (com o nome exato): você copia o nome e escolhe o arquivo, escolhe vários de uma vez, ou aponta uma pasta e o app acha sozinho; a PSdZData inteira também serve. Os escolhidos ficam como links em `packages/swe/swfl`. (Elas lêem os arquivos direto da PSdZData; ver `docs/OUTRAS_GERACOES.md`): o iDrive 7 mostra a tela central ou a do banco traseiro, com toque, rotor, botões e editor de codificação (o iDrive 8 também tem o editor, com 1.264 parâmetros); o primeiro boot leva ≈ 2 min e os seguintes ≈ 1 s (snapshot).
Só uma versão do HMI foi validada. Detalhes em `docs/ARQUITETURA.md`.

SSH: o login é o usuário local do Mac (não `root`); a interface mostra o comando pronto (aba SSH).
Compilar as bibliotecas do guest do zero exige `src/shim/build.sh` (clang + `ld.lld` do rustup ou do ziglang); as prontas já vão em `idemu/shim/lib`.

## Mapa
A tela Mapa do HMI mostra um mapa desenhado pelo IDEmu, que segue o GPS virtual. A fonte de blocos vem desligada: ligue na aba **Mapa** (OpenStreetMap ou servidor próprio). Não é o motor de navegação da BMW: sem rotas e sem busca de endereço. Detalhes em `docs/V850.md`.

## Celular
A aba **Celular** (tela Execução) liga uma página para o celular, na mesma rede Wi-Fi: ele vira a tela, o toque, o rotor e os botões da head unit, e o GPS do carro (posição do celular). Protegido por PIN. Bluetooth, CarPlay e Android Auto não existem na head unit emulada. Ver `docs/CELULAR.md`.

## Outras gerações
iDrive 5 roda com os mesmos pacotes do iDrive 6, ainda com quedas do HMI nos menus de navegação: escolha a geração ao criar o ambiente. Ambientes antigos precisam ser recompilados antes. iDrive 8 roda com a interface real, toque e rotor: escolha **iDrive 8** em Novo ambiente (sem mapa nem sinais do carro). iDrive 7 mostra a tela central (HU) ou a do banco traseiro (RSE), com toque, rotor, botões e editor de codificação, sem mapa, mídia nem sinais do carro. CIC (CIC High, SH-4A) mostra a interface real do HMI no app, ainda sem rotor nem teclas (`docs/CIC.md`). O toque funciona no iDrive 5, 6 e 8. Ver `docs/OUTRAS_GERACOES.md`.
