#!/usr/bin/env python3
"""Prepara a imagem de boot do CIC: recorta o IFS (startup + imagefs) do pacote SWFL e escreve, no
cabeçalho (offset 0x40), a lista de parâmetros que o IPL da Harman passaria ao startup.
Cada registro: u16 tag, u16 tamanho, dados...  (lista termina com tamanho 0)."""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import ifsx

ARGS = ['startup-sh7785', '-vvv', '-D0xFFEB0000.115200.1843200.16', '-n84M', '-Nl6target']
ARGS_OFF = 0xc030   # tabela de argumentos embutida do startup (u16 tamanho, u16 argc, u32 ptr, strings)

def patch_image(img, edits):
    """edits: lista de (antigo, novo) de mesmo tamanho aplicadas ao imagefs; refaz a soma de verificação."""
    img = bytearray(img)
    for ed in edits:
        old, new = ed[0], ed[1]
        every = len(ed) > 2 and ed[2] == 'all'
        assert len(old) == len(new)
        i = img.find(old)
        assert i >= 0, old
        while i >= 0:
            img[i:i + len(old)] = new
            i = img.find(old, i + len(old)) if every else -1
    n = len(img) // 4 - 1
    acc = sum(struct.unpack_from('<%dI' % n, img, 0)) & 0xffffffff
    struct.pack_into('<I', img, len(img) - 4, (-acc) & 0xffffffff)
    return bytes(img)


# hash DES tradicional (crypt(3)) de 'root' com sal 'KP': o módulo crypt saiu do Python 3.13, então o valor padrão vem pronto
ROOT_HASH = {'root': b'KPNHwB2guYDys'}


def root_password_edit(pw='root'):
    """Troca o hash da senha do root no /etc/passwd do IFS (mesmo tamanho, mesmo sal 'KP')."""
    if pw in ROOT_HASH:
        return (b'KPcKrCeGUgGeA', ROOT_HASH[pw])
    try:
        import crypt                      # só para outras senhas; não existe no Python 3.13+
    except ImportError:
        raise RuntimeError('senha %r: o módulo crypt não existe neste Python (3.13+); use a senha padrão "root"' % pw)
    return (b'KPcKrCeGUgGeA', crypt.crypt(pw, 'KP').encode())


def add_files(img, adds):
    """Troca o conteúdo de arquivos EXISTENTES do imagefs (não há vão no diretório): os dados novos vão no fim
    e o dirent passa a apontar para eles. adds: lista de (dados, 'caminho/no/ifs')."""
    img = bytearray(img)
    hd, do = struct.unpack_from('<II', img, 12)
    body = bytearray(img[:-4])
    for item in adds:
        data, path = item[0], item[1]
        newname = item[2] if len(item) > 2 else None
        p = do; ok = False
        while p < hd:
            sz, xo, ino, mode = struct.unpack_from('<HHII', img, p)
            if sz == 0:
                break
            if mode & 0o170000 == 0o100000 and img[p + 32:p + sz].split(b'\0')[0].decode('latin1') == path:
                off = (len(body) + 3) & ~3
                body += bytes(off - len(body)); body += data
                struct.pack_into('<II', img, p + 24, off, len(data))
                if newname:
                    slot = sz - 32
                    assert len(newname) < slot
                    img[p + 32:p + sz] = newname.encode().ljust(slot, b'\0')
                ok = True
                break
            p += (sz + 3) & ~3
        assert ok, path
    out = bytearray(bytes(img[:len(img) - 4])[:len(body)] if False else body)
    # os dirents alterados estão em img; copia o diretório atualizado para body
    out[:hd] = img[:hd]
    out += bytes(4)
    struct.pack_into('<I', out, 8, len(out))        # image_size no cabeçalho do imagefs
    n = len(out) // 4 - 1
    acc = sum(struct.unpack_from('<%dI' % n, out, 0)) & 0xffffffff
    struct.pack_into('<I', out, len(out) - 4, (-acc) & 0xffffffff)
    return bytes(out)


def build(src, dst, ram_base=0x08000000, ram_size=0x10000000, extra=(), args=ARGS, edits=None, files=()):
    d = bytearray(open(src, 'rb').read(0x1000000))
    sts = struct.unpack_from('<I', d, 0x1c)[0]            # stored_size
    if edits:
        h = ifsx.parse_header(bytes(d))
        raw = ifsx.decompress(bytes(d), h)
        raw = patch_image(raw, edits)
        if files:
            raw = add_files(raw, files)
        hdr = bytearray(d[:h['ss']])
        hdr[6] &= ~0x1c                                   # sem compressão
        struct.pack_into('<I', hdr, 28, h['ss'] + len(raw))   # ram_size
        struct.pack_into('<I', hdr, 36, h['ss'] + len(raw))   # stored_size (sem compressão)
        struct.pack_into('<I', hdr, 44, len(raw))             # tamanho do imagefs
        full = bytes(hdr) + raw
        img = bytearray(full + bytes(-len(full) % 0x1000))
    else:
        img = bytearray(d[:(sts + 0xfff) & ~0xfff])
    recs = bytearray(img[0x40:0x48])                      # registro 0x8000 original (4 bytes de dados)
    pos = 0x40
    items = [struct.pack('<HHII', 0x8004, 12, ram_base, ram_size)]
    items += list(extra)
    for it in items:
        recs += it
    recs += bytes(8)
    assert 0x40 + len(recs) <= 0x100
    img[0x40:0x40 + len(recs)] = recs
    if args:
        blob = b''.join(a.encode() + b'\0' for a in args)
        assert len(blob) < 0x60
        img[ARGS_OFF + 8:ARGS_OFF + 8 + 0x60] = blob.ljust(0x60, b'\0')
        struct.pack_into('<HH', img, ARGS_OFF, 8 + len(blob), len(args))
    open(dst, 'wb').write(img)
    return len(img)

if __name__ == '__main__':
    print(build(sys.argv[1], sys.argv[2]))
