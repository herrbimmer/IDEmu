# Toque na tela: iDrive 5, 6 e 8 (2026-11-07)

Clique, toque e arraste na imagem do display funcionam nas três gerações que o IDEmu roda. A interface web manda `POST /api/input/click` (`x`, `y`, `down`, `move`); cada geração entrega o evento por um caminho diferente.

| Geração | Caminho | Verificado |
|---|---|---|
| iDrive 8 | Touchscreen `uinput` (`idemuinput`) no guest Linux | Toque e arraste (feito antes) |
| iDrive 6 | `CTouchData` sintético entregue ao `CTouchDataClient` do `HmiMain3D`, pelo shim (`src/shim/hook.c`) | Abrir Mídia e FM pelos tiles, botão Início, arrastar o menu principal |
| iDrive 5 | O mesmo `HmiMain3D` e o mesmo caminho | Abrir ConnectedDrive pelo menu vertical |
| iDrive 7 | Serial `ttyS0` → `idemu-wl` → `wl_pointer` → `CHmiWindowInputHandler` → `CTouchDataClient`, com três patches binários no `HmiMain3D` (ver `docs/OUTRAS_GERACOES.md`) | Tocar na aba do carro (RSE e tela central) trocou a página; setas, rotor e botões também chegam (ver `docs/OUTRAS_GERACOES.md`) |

## iDrive 5 e 6: como o evento chega ao HMI

O guest QNX não tem driver de touchscreen. O shim monta o que o driver faria:

1. **O objeto.** `CTouchData` (construtor em `0x2a26914`): `vptr`, `vector<dedo>` em +4, byte em +0x10, tempo em +0x14 (ms), origem em +0x18 (1 = tela do CID). Cada dedo tem 10 bytes: `x`, `y`, `z` (u16), tipo, estado (1 toca, 2 move, 3 solta), id.
2. **A entrega.** Um `shared_ptr` montado à mão (contagem alta, o objeto nunca é liberado) vai para `CTouchDataClient::forwardTouchData` (assíncrono, `0x2a22600`), que enfileira `forwardTouchDataSync` na unidade de processamento certa. Chamar a versão síncrona da thread de entrada derrubava o HMI de vez em quando (status 139).
3. **O cliente.** O shim captura o `CTouchDataClient` nos construtores (`0x2a24660` e `0x2a24e48`; o prólogo usa instruções relativas ao PC, então o trampolim é feito à mão).
4. **As portas que o HMI fecha.** Sem o hardware, três estados impedem o toque; o shim os acerta a cada evento: a fonte 1 precisa estar ligada no mapa do serviço de toque; o serviço de display acha que a tela está apagada e usa o primeiro toque só para "acordá-la" (`+0x3c`, `+0x3d` e `0x2df744`); e o tratador de gestos (`0x3384e8`) só vale com `+0x30 = 1`.
5. **Nada de evento de acordar.** O guest empurrava um evento de controle vazio depois de cada evento de entrada; o HMI tratava isso como entrada do ZBE (rotor) e cancelava o toque ("touch input superseded by zbe input"). Os eventos de toque agora entram direto na thread de entrada, sem esse empurrão.
6. **Hora do Mac.** O laço principal do HMI ocioso roda cerca de 1 vez por segundo e juntaria descida e subida no mesmo instante; o Mac manda o horário do clique no campo de tempo.

### A causa que escondeu tudo por horas

O byte em `+0x10` do `CTouchData` **tem de ser 0**. Com 1, o classificador de eventos do reconhecedor de gestos (`0x19be9a4`) devolve sempre "início" sem olhar o estado do dedo, a máquina de gestos nunca avança, `CGestureRecognizer2` não escolhe alvo e nenhum widget recebe `tap`. Sintoma: o HMI loga `touchEvent`, `notifyTouchDownListeners` e `end touch interaction`, mas nada abre. Com 0, os logs mostram `pass gesture to widget ... (gesture: tap, state: start/end)` e as telas respondem.

### O que não precisa

Nenhuma codificação extra (`CID_TOUCH`, `CID_HMI_TOUCH`, ...) e nenhuma variante forçada: o perfil padrão do IDEmu já basta. (O `TCID:false` do log do `TouchDataClient` é só o tipo de touchscreen que o carro real teria; não impede nada.)

## iDrive Touch Controller: o touchpad do controlador (iDrive 5 e 6)

O mesmo caminho entrega o touchpad da tampa do controlador: o "iDrive Touch Controller" no cartão do controlador da interface web
(`POST /api/input/touchpad`, x e y de 0 a 1; x2 e y2 para um segundo dedo). O shim monta o `CTouchData` como o `CTouchPadService`
monta a partir do `CccsAbsoluteCoordinates`: origem 3, coordenadas 0..511, z 50, ids 0 e 1, sem os acertos da tela (origem 1,
display, gestos). Eventos do guest: 41 (estado, x | y << 16, hora; bit 0x100 no estado = com o segundo dedo), precedido de 42
(estado e posição do segundo dedo). Uso, escrita à mão nos campos de busca e as mensagens MOST: `docs/TOUCH_CONTROLLER.md`.

## Limites

* Tela: um dedo só (sem pinça nem dois dedos). O touchpad do controlador tem dois (acima).
* iDrive 5 e 6: o HMI ocioso desenha poucas vezes por segundo, então a resposta ao toque leva uma fração de segundo a mais que no carro. No iDrive 5 a tela leva vários segundos para refletir cada entrada e os painéis de pré-visualização demoram até cerca de 1 minuto depois do boot.
* O mapa do iDrive 5 continua com as quedas do HMI descritas em `OUTRAS_GERACOES.md`.

## Gancho de diagnóstico de quedas

O shim tem um tratador de SIGSEGV/SIGBUS/SIGILL/SIGFPE que registra registradores no log (`crash_h`). Ligado por padrão, o iDrive 5 não terminava de subir (frame_seq parado em 6 em 5 de 6 boots; sem o tratador, 5 de 5 subiram). Ele só compila com `EXTRA_CF=-DCRASHHK zsh src/shim/build.sh ...`.
