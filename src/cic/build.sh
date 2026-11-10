#!/bin/bash
# Compila o qemu-system-sh4 do IDEmu (placa "cic"): copia src/cic para a árvore do QEMU e roda o ninja.
set -e
Q=${CIC_QEMU:-$HOME/id4-qemu/qemu-11.1.2}
B=${CIC_BUILD:-$HOME/id4-qemu/build}
H=$(cd "$(dirname "$0")" && pwd)
# sed -i portátil (BSD/macOS exige sufixo separado, GNU/Linux não aceita '' separado): grava um .bak e o apaga
sedi() { sed -i.idemu-bak "$@" && rm -f "${@: -1}.idemu-bak"; }
cp "$H"/cic.c "$H"/cic_soc.c "$H"/cic_scif.c "$H"/cic_pci.c "$H"/cic.h "$Q/hw/sh4/"
grep -q CONFIG_CIC "$Q/hw/sh4/meson.build" || sedi "s|^hw_arch += {'sh4': sh4_ss}|sh4_ss.add(when: 'CONFIG_CIC', if_true: files('cic.c', 'cic_soc.c', 'cic_scif.c', 'cic_pci.c'))\nhw_arch += {'sh4': sh4_ss}|" "$Q/hw/sh4/meson.build"
grep -q "config CIC" "$Q/hw/sh4/Kconfig" || cat >> "$Q/hw/sh4/Kconfig" <<'EOK'

config CIC
    bool
    default y
    depends on SH4
    select SH_INTC
    select SH_SCI
    select SH_TIMER
    select UNIMP
    select PCI
EOK
# log de exceções com TEA/TRA/EXPEVT (ajuda a depurar o QNX)
grep -q "tea=%08x" "$Q/target/sh4/helper.c" || python3 - "$Q/target/sh4/helper.c" <<'EOP'
import sys
p = sys.argv[1]; s = open(p).read()
s = s.replace('qemu_log("exception 0x%03x [%s] raised\\n",\n                  irq_vector, expname);',
              'qemu_log("exception 0x%03x [%s] raised tea=%08x tra=%x\\n",\n                  irq_vector, expname, env->tea, env->tra);')
open(p, 'w').write(s)
EOP
# RTE: a busca da instrução do delay slot de um RTE é privilegiada (o SR já voltou ao modo usuário); sem isto o get_physical_address dá
# "Unauthorized access" quando a página do kernel não está no TLB do softmmu e o processo morre com SIGSEGV (ip = o RTE, ref = o delay slot)
grep -q cic_sr_user "$Q/target/sh4/helper.c" || python3 - "$Q/target/sh4/helper.c" <<'EOP'
import sys
p = sys.argv[1]; s = open(p).read()
helper = """/* cic: a busca de instrução do delay slot de um RTE é feita em modo privilegiado mesmo com o SR já restaurado (modo usuário) */
static inline bool cic_sr_user(CPUSH4State *env, MMUAccessType t)
{
    return !(env->sr & (1u << SR_MD)) && !(t == MMU_INST_FETCH && (env->flags & TB_FLAG_DELAY_SLOT_RTE));
}

"""
s = s.replace("/* Find the corresponding entry in the right TLB", helper + "/* Find the corresponding entry in the right TLB", 1)
s = s.replace("use_asid = !(env->mmucr & MMUCR_SV) || !(env->sr & (1u << SR_MD));\n\n    if (access_type", "use_asid = !(env->mmucr & MMUCR_SV) || cic_sr_user(env, access_type);\n\n    if (access_type", 1)
s = s.replace("if (!(env->sr & (1u << SR_MD)) && !(matching->pr & 2)) {", "if (cic_sr_user(env, access_type) && !(matching->pr & 2)) {")
s = s.replace("        if (!(env->sr & (1u << SR_MD))\n                && (address < 0xe0000000 || address >= 0xe4000000)) {", "        if (cic_sr_user(env, access_type)\n                && (address < 0xe0000000 || address >= 0xe4000000)) {")
open(p, 'w').write(s)
EOP
# PREF em modo privilegiado carrega a TLB (no hardware pode gerar TLB miss). O handler de instrução ilegal do procnto faz "pref @spc"
# antes de recarregar SSR/SPC/banco 1 e depois lê a instrução em SPC; sem o pref o TLB miss acontece dentro dessa janela, o handler de TLB
# usa o banco 1 como rascunho, r1 vira lixo e o processo morre com SIGSEGV ip=88009162 (era o crash aleatório do devc-sersci)
grep -q "cic: PREF" "$Q/target/sh4/translate.c" || python3 - "$Q/target/sh4/translate.c" <<'EOP'
import sys
p = sys.argv[1]; s = open(p).read()
s = s.replace("""    case 0x0083: /* pref @Rn */
        return;""", """    case 0x0083: /* pref @Rn */
        /* cic: PREF */
        if (!IS_USER(ctx)) {
            TCGLabel *skip = gen_new_label();
            TCGv t = tcg_temp_new();
            tcg_gen_brcondi_i32(TCG_COND_GEU, REG(B11_8), 0xe0000000, skip);
            tcg_gen_andi_i32(t, REG(B11_8), 0xc0000000);
            tcg_gen_brcondi_i32(TCG_COND_EQ, t, 0x80000000, skip);
            tcg_gen_qemu_ld_i32(t, REG(B11_8), ctx->memidx, MO_UB);
            gen_set_label(skip);
        }
        return;""", 1)
open(p, 'w').write(s)
EOP
# gdbstub: blocos já traduzidos e encadeados (goto_tb) pulam a checagem de breakpoint; ao inserir um breakpoint o cache de
# tradução é esvaziado (sem isso breakpoints reinseridos depois de um passo simples eram perdidos; só afeta depuração)
grep -q "cic: blocos" "$Q/accel/tcg/tcg-accel-ops.c" || python3 - "$Q/accel/tcg/tcg-accel-ops.c" <<'EOP'
import sys
p = sys.argv[1]; s = open(p).read()
old = """            err = cpu_breakpoint_insert(cpu, addr, BP_GDB, NULL);
            if (err) {
                break;
            }
        }
        return err;"""
s = s.replace(old, old.replace("        return err;", "        /* cic: blocos já traduzidos e encadeados (goto_tb) pulam a checagem de breakpoint */\n        tb_flush__exclusive_or_serial();\n        return err;"), 1)
open(p, 'w').write(s)
EOP
# hypercall do IDEmu: "trapa #0xC3" com r0 = 0x1DE3xxxx é tratado pela placa (entrada do controlador, ver cic.c) e segue na instrução seguinte
grep -q "sh4_cic_hypercall" "$Q/target/sh4/op_helper.c" || python3 - "$Q/target/sh4/op_helper.c" "$Q/target/sh4/cpu.h" <<'EOP'
import sys
p = sys.argv[1]; s = open(p).read()
s = s.replace("""void helper_trapa(CPUSH4State *env, uint32_t tra)
{
""", """/* cic: hypercall do IDEmu (a placa instala o tratador) */
bool (*sh4_cic_hypercall)(CPUSH4State *env);

void helper_trapa(CPUSH4State *env, uint32_t tra)
{
    if (tra == 0xc3 && sh4_cic_hypercall && sh4_cic_hypercall(env)) {
        env->pc += 2;
        cpu_loop_exit(env_cpu(env));
    }
""", 1)
open(p, 'w').write(s)
h = sys.argv[2]; s = open(h).read()
i = s.rindex('#endif')
s = s[:i] + "/* cic: hypercall do IDEmu (trapa #0xC3) */\nextern bool (*sh4_cic_hypercall)(CPUSH4State *env);\n\n" + s[i:]
open(h, 'w').write(s)
EOP
# SH-4A tem movua.l (acesso desalinhado, pode cruzar páginas): wrap 32 bits em vez de abort
grep -q "pointer_wrap = cpu_pointer_wrap_uint32" "$Q/target/sh4/cpu.c" || sedi 's/\.pointer_wrap = cpu_pointer_wrap_notreached/.pointer_wrap = cpu_pointer_wrap_uint32/' "$Q/target/sh4/cpu.c"
# URC (contador aleatório da UTLB) nunca deve alcançar URB: as entradas URB..63 são "fixas" (wired)
grep -q "urc >= urb" "$Q/target/sh4/helper.c" || python3 - "$Q/target/sh4/helper.c" <<'EOP'
import sys
p = sys.argv[1]; s = open(p).read()
s = s.replace('if ((urb > 0 && urc > urb) || urc > (UTLB_SIZE - 1))', 'if ((urb > 0 && urc >= urb) || urc > (UTLB_SIZE - 1))')
open(p, 'w').write(s)
EOP
# SH7785 no modo de endereçamento de 32 bits: o PPN da UTLB vai até o bit 31 (o QEMU corta em 29 bits e joga a janela PCI em 0x1bxxxxxx)
grep -q "cic: PPN32" "$Q/target/sh4/helper.c" || { sedi 's/(mem_value \& 0x1ffffc00) >> 10/(mem_value \& 0xfffffc00) >> 10; \/* cic: PPN32 *\//' "$Q/target/sh4/helper.c"; sedi 's/#define PTEL_PPN_BITS (19)/#define PTEL_PPN_BITS (22)/' "$Q/target/sh4/cpu.h"; }
# interrupções IRL (INTEVT 0x200..0x3e0) têm nível fixo codificado no vetor: nível = (0xf0 - (vetor-0x200)/2) >> 4;
# o sh_intc ignora prioridade (FIXME deles), o que gera tempestade quando o ISR roda com IMASK == nível
grep -q "cic: IRL" "$Q/hw/intc/sh_intc.c" || python3 - "$Q/hw/intc/sh_intc.c" <<'EOP'
import sys
p = sys.argv[1]; s = open(p).read()
s = s.replace("        if (source->pending) {\n            trace_sh_intc_pending(desc->pending, source->vect);",
"        if (source->pending) {\n            /* cic: IRL */\n            if (source->vect >= 0x200 && source->vect <= 0x3e0 &&\n                ((0xf0 - ((source->vect - 0x200) >> 1)) >> 4) <= imask) {\n                continue;\n            }\n            trace_sh_intc_pending(desc->pending, source->vect);")
s = s.replace("    g_assert_not_reached();\n}\n\ntypedef enum", "    return -1;\n}\n\ntypedef enum",1)
open(p, 'w').write(s)
EOP
# flash S29GL: o devf-generic usa o conjunto de comandos de proteção de setor (PPB, entrada AA 55 C0, saída 90 00) para checar/liberar setores;
# o QEMU não o conhece, e o FFS3 monta a partição como somente leitura. Aqui todos os setores ficam sempre desprotegidos.
grep -q "cic: PPB" "$Q/hw/block/pflash_cfi02.c" || python3 - "$Q/hw/block/pflash_cfi02.c" <<'EOP'
import sys
p = sys.argv[1]; s = open(p).read()
s = s.replace("    uint8_t cmd;\n", "    uint8_t cmd;\n    uint8_t ppb_exit;   /* cic: PPB */\n", 1)
s = s.replace("    switch (pfl->cmd) {\n    default:\n        /* This should never happen",
              "    switch (pfl->cmd) {\n    case 0xC0: /* cic: PPB: setores sempre desprotegidos */\n        ret = 1;\n        break;\n    default:\n        /* This should never happen", 1)
s = s.replace("    cmd = value;\n    if (pfl->cmd != 0xA0) {",
              "    cmd = value;\n    if (pfl->cmd == 0xC0) { /* cic: PPB (saída: 90 e 00) */\n        if (cmd == 0x00 && pfl->ppb_exit) { pfl->ppb_exit = 0; goto reset_flash; }\n        pfl->ppb_exit = (cmd == 0x90);\n        return;\n    }\n    if (pfl->cmd != 0xA0) {", 1)
s = s.replace("        case 0x80: /* Erase */\n        case 0x90: /* Autoselect */\n        case 0xA0: /* Program */\n            pfl->cmd = cmd;\n            trace_pflash_write_start(pfl->name, cmd);\n            break;",
              "        case 0xC0: /* cic: PPB */\n            pfl->cmd = 0xC0; pfl->wcycle = 0; pfl->ppb_exit = 0;\n            return;\n        case 0x80: /* Erase */\n        case 0x90: /* Autoselect */\n        case 0xA0: /* Program */\n            pfl->cmd = cmd;\n            trace_pflash_write_start(pfl->name, cmd);\n            break;", 1)
open(p, 'w').write(s)
EOP
cd "$B" && ninja qemu-system-sh4
cp "$B/qemu-system-sh4" "$H/../../bin/qemu-system-sh4" 2>/dev/null || true
