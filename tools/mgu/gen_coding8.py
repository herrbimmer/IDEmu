#!/usr/bin/env python3
"""Dicionário de codificação do iDrive 8 (MGU22) -> mgu22/coding8.json, lido pelo editor (idemu/coding8.py).

Fontes, ambas do pacote do firmware: o esquema `cafd_mgu_02_a.bin` (nome, id, valores do enum e valor padrão de cada parâmetro) e `MGU22_Coding.txt`
(valor do carro G70BEV e a seção, ex. infotainment.HMI). Só entram os parâmetros do CAF "infotainment": são os que o Hmi8 pede por `cod_get_flag`
(cluster, ioc e dac repetem os mesmos ids para outras centrais e `gencoding.py` já dá a prioridade ao infotainment).

Uso: gen_coding8.py cafd.bin MGU22_Coding.txt saida.json
     gen_coding8.py --psdz [pasta da PSdZData] [saida.json]   (extrai os dois arquivos dos pacotes swfl_00009ff7 e swfl_00009fc6)"""
import json, os, re, stat, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import gencoding as g

SKIP = re.compile(r'^(IS_CODED|CAF_VERSION_(MAJOR|MINOR|PATCH))$')
MAX_NUM = (1 << 31) - 1


def txt_sections(path):
    """{nome do parâmetro: seção do TXT} (ex. 'CID_TOUCH' -> 'HMI')."""
    out, sec = {}, 'infotainment'
    for line in open(path, encoding='utf-8', errors='replace'):
        m = re.match(r'\s*"([A-Za-z0-9_.]+)"\s*:\s*\{', line)
        if m:
            sec = m.group(1).split('.', 1)[-1]
            continue
        m = re.match(r'\s*"([A-Za-z0-9_]+)"\s*:\s*"', line)
        if m:
            out[m.group(1)] = sec
    return out


def build(cafd, txtpath):
    fb = g.FB(cafd)
    txt = g.parse_txt(txtpath)
    secs = txt_sections(txtpath)
    params, seen = [], {}
    for sec, name, fid, default, enum in g.flags(fb):
        if sec != 'infotainment' or SKIP.match(name):
            continue
        val = g.resolve(txt.get(name), default, enum)
        if val is None:
            val = 0
        opts = sorted(({'value': v, 'raw': n} for n, v in enum.items()), key=lambda o: (o['value'], o['raw']))
        dedup, used = [], set()
        for o in opts:
            if o['value'] not in used:
                used.add(o['value'])
                dedup.append(o)
        p = {'name': name, 'id': fid, 'group': secs.get(name, 'infotainment'), 'default': val, 'options': dedup}
        if name in seen:
            params[seen[name]] = p
        else:
            seen[name] = len(params)
            params.append(p)
    params.sort(key=lambda p: (p['group'], p['name']))
    return {'version': 1, 'ecu': 'MGU22', 'params': params}


def from_psdz(psdz, out):
    import build_image as B
    from ext4ls import E4

    def grab(e, p, dst):
        t = e.inode(e.lookup(p))
        while stat.S_ISLNK(e.mode(t)):
            p = os.path.join(os.path.dirname(p), e.data(t).decode())
            t = e.inode(e.lookup(p))
        with open(dst, 'wb') as f:
            f.write(e.data(t))
    _, _, files = B.catalog.mgu22_firmware(psdz, ids={'00009ff7', '00009fc6'}, include_staged=False)
    packages = {item['id']: path for item, path in files}
    with tempfile.TemporaryDirectory(prefix='coding8', dir=os.path.dirname(B.OUT)) as d:
        for pkg, member, raw, src, dst in (('00009ff7', 'mgu22-bmw-image-mgu22-sa8155.ext4.simg.bin.gz', 'root', '/usr/share/sysfunc/coding/cafd_mgu_02_a.bin', 'cafd.bin'),
                                           ('00009fc6', 'mgu22-ivi-sa8155.ext4.simg.bin.gz', 'ivi', '/rootfs/usr/share/hmi/data/ro/MGU22_Coding.txt', 'coding.txt')):
            B.member(packages[pkg], member, d + '/x.gz')
            B.simg(d + '/x.gz', d + '/%s.raw' % raw)
            os.unlink(d + '/x.gz')
            e4 = E4(d + '/%s.raw' % raw)
            try: grab(e4, src, d + '/' + dst)
            finally: e4.close()                      # Windows: um arquivo aberto não pode ser apagado
            os.unlink(d + '/%s.raw' % raw)
        data = build(d + '/cafd.bin', d + '/coding.txt')
    write(data, out)
    return data


def write(data, out):
    tmp = out + '.new'
    with open(tmp, 'w') as f:
        json.dump(data, f, separators=(',', ':'))
    os.replace(tmp, out)


def main():
    a = sys.argv[1:]
    if a and a[0] == '--psdz':
        rest = a[1:]
        psdz = rest[0] if rest and not rest[0].endswith('.json') else json.load(open(os.path.join(ROOT, 'settings.json')))['psdz_path']
        out = rest[-1] if rest and rest[-1].endswith('.json') else os.path.join(ROOT, 'mgu22', 'coding8.json')
        d = from_psdz(psdz, out)
    elif len(a) == 3:
        d = build(a[0], a[1])
        write(d, a[2])
    else:
        raise SystemExit(__doc__)
    print('parâmetros', len(d['params']), 'com opções', sum(1 for p in d['params'] if p['options']))


if __name__ == '__main__':
    main()
