"""Manipulação de imagens QNX IFS (boot1.ifs do SWFL): descompressão LZO, repacote sem compressão,
edição de string e inclusão de arquivos (porta dos scripts de engenharia reversa do projeto)."""
import struct, hashlib
from .qnxfs import lzo

HFMT = '<IHBBHHIIIIIIIII'   # cabeçalho startup: sig ver f1 f2 hs mach sva pb ip rp rs ss sts ims pre

def _hdr(d):
    v = list(struct.unpack_from(HFMT, d, 8))
    return v, v[11]

def decompress(d, start=None):
    """Descomprime os blocos LZO1X (len BE16 + bloco) do IFS comprimido -> imagefs bruto."""
    v, ss = _hdr(d)
    p = start if start is not None else 8 + ss
    img = bytearray()
    while p + 2 <= len(d):
        ln = (d[p] << 8) | d[p + 1]; p += 2
        if ln == 0:
            break
        blk = bytes(d[p:p + ln]); p += ln
        o, ip = lzo.lzo1x_decompress(blk + b'\x11\x00\x00')   # marcador de fim: alguns blocos vêm sem ele
        img += o
    return bytes(img)

def make_uncompressed(d, img, align=16):
    v, ss = _hdr(d)
    ss2 = ((8 + ss + align - 1) // align) * align - 8
    out = bytearray(d[:8 + ss]) + bytes(ss2 - ss) + img
    v[2] &= ~0x1c
    v[10] = ss2 + len(img); v[11] = ss2; v[12] = ss2 + len(img)
    struct.pack_into(HFMT, out, 8, *v)
    return out

def fix_checksum(buf, base):
    """Ajusta a última palavra do imagefs (a partir de `base`) para que a soma das palavras LE seja 0."""
    n = (len(buf) - base) // 4 - 1
    acc = sum(struct.unpack_from('<%dI' % n, buf, base)) & 0xffffffff
    struct.pack_into('<I', buf, len(buf) - 4, (-acc) & 0xffffffff)

def replace_bytes(buf, old, new, count=1):
    if len(old) != len(new):
        raise ValueError('troca precisa manter o tamanho')
    n = 0; i = 0
    while True:
        i = buf.find(old, i)
        if i < 0: break
        buf[i:i + len(old)] = new; i += len(old); n += 1
    if n != count:
        raise ValueError('esperava %d ocorrência(s) de %r, achei %d' % (count, old, n))

def add_files(d, adds):
    """adds: lista de (dados:bytes, caminho_no_ifs). Dirents novos vão para o vão após o diretório; dados no fim."""
    d = bytearray(d)
    v, ss = _hdr(d)
    base = 8 + ss
    img = bytearray(d[base:]); head = bytes(d[:base])
    hd, do = struct.unpack_from('<II', img, 12)
    p = do; first = 1 << 60
    while p < hd:
        sz, xo, ino, mode = struct.unpack_from('<HHII', img, p)
        if sz == 0: break
        if mode & 0o170000 == 0o100000:
            first = min(first, struct.unpack_from('<I', img, p + 24)[0])
        p += (sz + 3) & ~3
    pend = p
    body = bytearray(img[:-4]); tail_off = len(body)
    newdir = bytearray(); ino = 0x100
    for data, ip in adds:
        m = data[:4]
        mode = 0o100755 if (m == b'\x7fELF' or m[:2] == b'#!') else 0o100644
        tail_off = (tail_off + 3) & ~3
        body += b'\0' * (tail_off - len(body)); off = tail_off; body += data; tail_off = len(body)
        n = ip.encode() + b'\0'
        sz = (24 + 8 + len(n) + 3) & ~3
        e = struct.pack('<HHIIIII', sz, 0, ino, mode, 0, 0, 0) + struct.pack('<II', off, len(data)) + n
        e += b'\0' * (sz - len(e)); newdir += e; ino += 1
    if not pend + len(newdir) + 8 <= first:
        raise ValueError('sem espaço no diretório do IFS para %d arquivos' % len(adds))
    body[pend:pend + len(newdir)] = newdir
    struct.pack_into('<I', body, 12, pend + len(newdir) + 8)
    total = ((len(body) + 3) & ~3) + 4
    body += b'\0' * (total - 4 - len(body))
    struct.pack_into('<I', body, 8, total)
    acc = sum(struct.unpack('<%dI' % ((total - 4) // 4), body)) & 0xffffffff
    img2 = bytes(body) + struct.pack('<I', (-acc) & 0xffffffff)
    v[10] = ss + total; v[12] = ss + total; v[14] = total
    h = bytearray(head); struct.pack_into(HFMT, h, 8, *v)
    return bytes(h) + img2

def list_files(d):
    """Lista (caminho, modo, offset, tamanho) das entradas de arquivo do imagefs."""
    v, ss = _hdr(d); base = 8 + ss
    hd, do = struct.unpack_from('<II', d, base + 12)
    p = base + do; out = []
    while p < base + hd:
        sz, xo, ino, mode = struct.unpack_from('<HHII', d, p)
        if sz == 0: break
        if mode & 0o170000 == 0o100000:
            off, fs = struct.unpack_from('<II', d, p + 24)
            out.append((d[p + 32:p + sz].split(b'\0')[0].decode('latin1'), mode, off, fs))
        p += (sz + 3) & ~3
    return out

LOGIN_OLD = b'/boot/bin/login\0login\0'
LOGIN_NEW = b'/boot/bin/////ksh\0ksh\0'

def _script_entries(buf):
    """Comandos do script de boot do IFS: [(offset, tamanho, tipo)]. Tipos: 0 = executa, 1 = waitfor, 2 = reopen, 3 = mensagem, 4 = symlink."""
    i = buf.find(b'/boot/bin/ksh\0/bin/ksh\0')
    if i < 4:
        raise ValueError('script de boot não encontrado no IFS')
    o, out = i - 4, []
    while True:
        n = struct.unpack_from('<H', buf, o)[0]
        if n == 0:
            return out
        if n < 4 or o + n > len(buf):
            raise ValueError('script de boot malformado no IFS')
        out.append((o, n, buf[o + 2]))
        o += n


SKIP_AT_BOOT = (b'devb-sdmmc-omap5evm\0', b'/boot/bin/gs\0', b'/opt/sys/bin/starter\0')


def speed_up_script(buf):
    """Tira do script de boot o que só serve ao hardware real e, na VM, só gasta tempo (o resto do IFS não muda):
    o driver de eMMC + a espera de 5 s por /dev/sda0 (o disco é montado depois, em RAM), o logger do DSP (espera um tempo limite) e o
    starter (o runtime inicia os serviços; ele nem está montado nessa hora). Cada comando vira uma mensagem vazia, sem mudar nenhum offset."""
    n = 0
    for o, size, typ in _script_entries(buf):
        body = bytes(buf[o + 4:o + size])
        if typ == 0 and any(x in body[:64] for x in SKIP_AT_BOOT) and body[0] == 0:
            buf[o + 2] = 3
            n += 1
        elif typ == 1 and b'/dev/sda0\0' in body:
            buf[o + 2] = 3
            buf[o + 4] = 0
            n += 1
    if n != len(SKIP_AT_BOOT) + 1:
        raise ValueError('script de boot diferente do esperado (%d comandos ajustados)' % n)


def make_boot_ifs(boot1_ifs, tools):
    """boot1.ifs original (bytes) + [(dados, caminho_no_ifs)] -> IFS de boot descomprimido,
    com o shell de login trocado por ksh (console serial) e as ferramentas extras."""
    img = decompress(boot1_ifs)
    unc = make_uncompressed(boot1_ifs, img)
    v, ss = _hdr(unc)
    # Older NBT Evo releases already start `ksh -li` on the console and have no login entry to swap.
    if LOGIN_OLD in unc or b'/boot/bin/ksh\0ksh\0' not in unc:
        replace_bytes(unc, LOGIN_OLD, LOGIN_NEW)
    speed_up_script(unc)
    fix_checksum(unc, 8 + ss)
    return add_files(bytes(unc), tools)
