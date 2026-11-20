# Câmera de ré com a webcam

O IDEmu mostra a webcam do computador sobre o display do carro quando a marcha ré está engatada, como numa câmera de ré real.

## Como usar

1. Inicie um ambiente e abra a aba **Câmera de ré** na tela de execução.
2. Permita o acesso à câmera quando o navegador (ou o macOS, no app Electron) perguntar.
3. Engate a ré: pelo botão **Engatar a ré** da própria aba, pela aba CAN (`gear_position = 1`) ou por um cenário de CAN com marcha à ré. A imagem da webcam aparece sobre o display com as linhas-guia.

Opções da aba:

| Opção | Efeito |
|---|---|
| Quando mostrar | Automática (só na ré), sempre ligada ou desligada |
| Webcam | Escolhe entre várias câmeras; a escolha fica salva neste navegador |
| Linhas-guia | Sem linhas, fixas, ou curvas conforme `steering_angle` do CAN |
| Espelhar a imagem | Inverte a imagem na horizontal, como no retrovisor |

## O que ela faz e não faz

- A captura é feita no navegador (`getUserMedia`) e o quadro nunca sai dele: não vai ao servidor do IDEmu nem ao sistema convidado.
- A webcam só liga enquanto a imagem está visível ou a aba está aberta; ~1,5 s depois de sair da ré ela é desligada.
- O gatilho é o `gear_position` do CAN virtual (via `/api/cluster`). Funciona nos ambientes que têm CAN virtual, inclusive iDrive 7 e 8.
- É um overlay do lado do computador. O HMI emulado **não** recebe vídeo: a câmera real do NBT Evo (iCAM2, H.264 por Ethernet/AVTP na vlan86, decodificado no IVA-HD) não tem decoder no QEMU. Os scripts de `tools/camera/` servem para diagnosticar isso numa head unit real.
- O CIC também recebe a marcha por MOST (`CReverseGear`), então o HMI sabe que a ré está engatada.

## Requisitos

`getUserMedia` exige `http://127.0.0.1` ou `localhost` (já é o endereço padrão do IDEmu). No Electron a permissão é concedida só para vídeo e só para a própria interface.
