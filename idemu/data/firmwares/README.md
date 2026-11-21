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

`006_016_002` também usa o shim **default**, selecionado pelo JSON
`nbtevo-006_016_002.json`. Não exige `lib-006016` nem uma compilação por firmware.
O seu ABI antigo (`runtime.abi: "id5_1803"`) usa dez endereços, nove assinaturas
de quatro instruções e offsets próprios; touch, TPM, Lua e debug ficam desligados.
O builder escreve no mesmo `addr.tab` 29 posições de endereços (19 zeros para
hooks desativados) e 40 campos de layout/assinaturas: 69 registos completos.
O guest valida e aplica o conjunto atomicamente; nunca herda endereços 051 para
os hooks desativados. As tabelas 007 de 29 endereços continuam compatíveis.
Veja [a validação exata e os limites](../../../docs/PROFILE_006016.md).

## Campos do perfil

- `hmi_sha256` — chave de busca (sha256 de opt/hmi/ID5/bin/HmiMain3D).
- `library_sha256` — hashes SHA-256 exatos de `libhmicom.so` e `libhmicoding.so`, extraídos do mesmo conjunto.
- `hmi_addr` — os 29 endereços do ABI default, ou os dez exigidos por `runtime.abi: "id5_1803"`; entradas desativadas não aparecem no JSON. Para o ABI default, os endereços `{nome: {addr, mech, what}}`. Os nomes TÊM de bater com
  `AD_NAME[]` em src/shim/hook.c (e com a ordem da struct `AD`). `mech` é documentação
  (patch/tramp/call/glob); o shim já sabe como usar cada um.
- O builder recusa perfis incompletos, hashes duplicados e endereços inválidos. Um HMI não registado ou um conjunto de bibliotecas diferente é recusado antes de criar o shim; perder um JSON não autoriza o fallback para endereços 051. Esboços com
  `status` começando em `stub` são ignorados. O guest aplica os 29 endereços como um conjunto completo.
- `symbol_hooks` — hooks por símbolo (dlsym): funcionam em qualquer build, NÃO vão para o addr.tab.
- `get_hmi_proc_unit` é mantido no formato de 29 campos por compatibilidade; `getHmiProcUnit` e
  `CHmiProcUnit::pushEvent` agora são resolvidos por `dlsym`, como no upstream.
- `runtime` — contrato executável do ABI antigo: `abi`, `home_power_flag`, `home_aux_flag`, `main_home_offset` e `signatures` (nove nomes de função, quatro palavras ARM por nome). Todos os campos são obrigatórios. Nove assinaturas e dez exports das bibliotecas são verificados antes de instalar qualquer hook. O power-on exige o thread do proc unit da aplicação.
- `libc_sha256` — fingerprint do IFS libc usado na compilação comum validada; obrigatório para o ABI antigo.
- `struct_off`, `scope_table`, `blobb_offset_in_nbtcarhu`, `display`, `hu_variant` — doc/outros.

## Perfis

| Perfil | Estado |
|---|---|
| `nbtevo-006_016_002.json` | Perfil completo do ABI antigo para o shim comum; [cold boot, aplicações e limites](../../../docs/PROFILE_006016.md) |
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
2. Criar `<nome>.json` com o `hmi_sha256`, os dois `library_sha256` e o conjunto completo de `hmi_addr` do ABI. Para o ABI antigo, incluir também todos os campos `runtime` e `libc_sha256`.
   Confirmar também que os offsets de estruturas e as features do shim `default` servem para esse build.
3. Criar o ambiente com esse SWFL e subir: o builder escolhe o perfil pelo sha e gera o addr.tab.
   Confirmar no slog do guest a linha `addr.tab: overrides carregados 29`; o ABI antigo também informa ABI 1 e 69 registos. Uma nova firmware de ABI suportado requer apenas JSON e validação, sem recompilar o shim.

## Atualizações e codificação

O manifesto `build.json` guarda o HMI e os hashes das bibliotecas. A atualização automática do shim
e a gravação da codificação reutilizam essa identidade, para não perder `addr.tab` numa reconstrução.
Ambientes criados antes desses campos precisam de um novo `python3 -m idemu build <id>` a partir
dos SWFL originais. Isso recompõe as imagens: faça backup das alterações locais antes.
