# Perfis de firmware (registry da multi-firmware)

Cada `<nome>.json` descreve UMA firmware do NBT Evo para o IDEmu. O que varia entre builds e
não pode ficar fixo no shim são ~29 endereços absolutos de funções/objetos internos do
HmiMain3D (binário stripped). Eles vivem aqui, não no código do shim.

## Como o IDEmu usa isto

1. `builder.build()` calcula o `hmi_sha256` do HmiMain3D extraído do SWFL.
2. `builder.profile_for_hmi(sha)` procura neste diretório o perfil completo com esse `hmi_sha256`.
   O builder exige também os hashes exatos de `libhmicom.so` e `libhmicoding.so`; um HMI conhecido
   com bibliotecas diferentes não pode receber a tabela de endereços.
3. Com o conjunto validado, `build_shim()` escreve `/fs/shim/addr.tab`
   ("nome 0xHEX" por linha) dentro de shim.img.
4. No guest, `install_hooks()` chama `addr_load()` (src/shim/hook.c), que lê o addr.tab e
   sobrescreve a struct `AD`. Ficheiro ausente => defaults compilados (= build 007_051_002),
   ou seja o 051 comporta-se exatamente como antes.

Mesma mecânica de `/fs/shim/coding.tab` e `/fs/shim/variants.bin`. As quatro firmwares `007` usam
um único binário do perfil `default`: acrescentar outra firmware com o mesmo ABI/feature set não
exige recompilar o shim. O perfil upstream **18-03 (`1803`, `006_017_006`) continua separado**,
com seus próprios DSOs, offsets, feature gates e assinaturas; ele não lê `addr.tab`.
Veja [NBT_PROFILES.md](../../../docs/NBT_PROFILES.md).

## Campos do perfil

- `hmi_sha256` — chave de busca (sha256 de opt/hmi/ID5/bin/HmiMain3D).
- `library_sha256` — hashes SHA-256 exatos de `libhmicom.so` e `libhmicoding.so`, extraídos do mesmo conjunto.
- `hmi_addr` — os ~29 endereços `{nome: {addr, mech, what}}`. Os nomes TÊM de bater com
  `AD_NAME[]` em src/shim/hook.c (e com a ordem da struct `AD`). `mech` é documentação
  (patch/tramp/call/glob); o shim já sabe como usar cada um.
- O builder recusa perfis incompletos, hashes duplicados e endereços inválidos. Esboços com
  `status` começando em `stub` são ignorados. O guest aplica os 29 endereços como um conjunto completo.
- `symbol_hooks` — hooks por símbolo (dlsym): funcionam em qualquer build, NÃO vão para o addr.tab.
- `get_hmi_proc_unit` é mantido no formato de 29 campos por compatibilidade; `getHmiProcUnit` e
  `CHmiProcUnit::pushEvent` agora são resolvidos por `dlsym`, como no upstream.
- `struct_off`, `scope_table`, `blobb_offset_in_nbtcarhu`, `display`, `hu_variant` — doc/outros.

## Perfis

| Perfil | Estado |
|---|---|
| `nbtevo-007_051_002.json` | ✅ completo — build validado pelos autores; é também o default compilado no shim |
| `nbtevo-007_001_016.json` | ✅ **boot ao vivo comprovado (12.11)** — 29 endereços derivados do 051 (diff de builds irmãos); HMI renderiza, 0 crashes; o shim antigo com os endereços 051 dava segfault (exit 139) neste mesmo binário |
| `nbtevo-007_030_001.json` | ✅ **boot ao vivo comprovado (12.11)** — 29/29 derivados; env `335d-030` sobe: overrides `0x1d`, ready→running, `HMI_EXIT=0` |
| `nbtevo-007_039_008.json` | ✅ **boot ao vivo comprovado (12.11)** — 29/29 derivados; env `335d-039` sobe: overrides `0x1d`, ready→running, `HMI_EXIT=0` |

## Acrescentar uma firmware

1. Extrair os ~29 endereços do HmiMain3D alvo por diff contra o 051 (endereços conhecidos).
   Pipeline comprovado:
   - funções: janela de bytes a partir da entrada, mascarando operandos voláteis (BL/B, ADR
     add/sub pc, MOVW/MOVT, offset de LDR/STR) + pareamento por rank (mesmo nº de cópias nos dois
     builds → par pela ordem de endereço);
   - PLT thunk / global .bss / vtable: pela tabela de símbolos (~13k nomes mangled);
   - cada resultado reconferido com `same_fn` (mesma função nos dois builds) ou pela estrutura da vtable.
   Referência de formato: `nbtevo-007_051_002.json`.
2. Criar `<nome>.json` com o `hmi_sha256`, os dois `library_sha256` e os 29 `hmi_addr` preenchidos.
   Confirmar também que os offsets de estruturas e as features do shim `default` servem para esse build.
3. Criar o ambiente com esse SWFL e subir: o builder escolhe o perfil pelo sha e gera o addr.tab.
   Confirmar no slog do guest a linha `addr.tab: overrides carregados 29`.

## Atualizações e codificação

O manifesto `build.json` guarda o HMI e os hashes das bibliotecas. A atualização automática do shim
e a gravação da codificação reutilizam essa identidade, para não perder `addr.tab` numa reconstrução.
Ambientes criados antes desses campos precisam de um novo `python3 -m idemu build <id>` a partir
dos SWFL originais. Isso recompõe as imagens: faça backup das alterações locais antes.
