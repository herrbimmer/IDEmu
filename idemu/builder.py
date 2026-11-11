"""Construtor de ambientes: SWFL (PSDZData) -> imagens de disco do guest, sem tocar nos SWFL originais.

Saída em <env>/images/:  boot.ifs  sda.img (QNX4, SO)  sdb.img (QNX6, dados do HMI)  shim.img (QNX4, camada de tradução)
O conteúdo de sda/sdb vem exclusivamente dos pacotes SWFL; a camada de tradução (bibliotecas do guest, scripts de init,
tabela de codificação) fica em shim.img e é aplicada na inicialização em memória."""
import struct, os, re, sys, json, time, hashlib, shutil, stat as st, zlib
from . import swfl, ifs, codegen
from .qnxfs import mkdisk, mkq6

HERE = os.path.dirname(os.path.abspath(__file__))
ISTEP = 'fs/sda0/repository/istep/'
RO = 'opt/hmi/ID5/data/ro/'

# Sobe o que cabe nos discos em RAM (sda = 480 MB). Estes diretórios não são usados pelos serviços que o IDEmu inicia.
OS_EXCLUDE = ('opt/nav/', 'opt/conn/', 'opt/sys/rpm/', 'opt/car/data/', 'lib/graphics/tools/')
# serviços mínimos que o IDEmu inicia (nome do executável, trecho dos argumentos, segundo plano). Resolvidos pelo starter.cfg do SWFL.
SERVICES = [('random', '', 1), ('mqueue', '', 1), ('io-pkt-v6-hc', '', 0), ('sysctl', '', 0), ('start_net.sh', '', 0),
            ('servicebroker', '', 0), ('dev-sysregs2', 'sysregs_asic_d1', 0), ('io-ipc', 'io-ipc-o5', 1), ('watchdog5-omap', '=-s smon=HBWATCHDOG2 -p v850channel=/dev/ipc/ipc26,v850cycle=8000', 1), ('tiler', '', 1),
            ('someip_sddaemon', '', 1), ('sysetpageproxy', '', 1), ('most', 'MOSTSubSystemServer', 1)]
# o que cada serviço cria quando está pronto (waitfor em vez de pausas fixas); sem entrada = nenhuma espera
READY = {'random': '/dev/random', 'io-pkt-v6-hc': '/dev/socket', 'dev-sysregs2': '/dev/sysregs', 'io-ipc': '/dev/ipc/ipc26',
         'watchdog5-omap': '/dev/hbwatchdog', 'servicebroker': '/srv/servicebroker'}
# start_net.sh do SWFL sem o que depende da Ethernet real (dwc0 não existe na VM): `if_up -r 10` + `waitfor /net/hu-jacinto... 3` só gastavam 17 s para falhar
# shim: 15 MB em 0x7f000000-0x7ff00000. Os primeiros 16 MB da janela de 32 MB do QEMU (0x7e000000) são o buffer da ponte GL, e 0x7ff00000 os registradores dela:
# com o shim ali, os comandos GL sobrescreviam o sistema de arquivos depois do boot (arquivos lidos tarde chegavam corrompidos)
SDA_SECTORS, SDB_SECTORS, SHIM_SECTORS = 983040, 2064384, 30720

ROLE_TOKEN = b'MOSTSrvSystem'      # nome-base do papel servidor (13 bytes, o mesmo tamanho de "MOSTSubSystem")


def _sub(buf, old, new):
    n = 0
    i = buf.find(old)
    while i >= 0:
        buf[i:i + len(old)] = new + b'\0' * (len(old) - len(new)); n += 1
        i = buf.find(old, i + len(old))
    return n


def make_most_pair(most, lib):
    """(experimental, IDEMU_MOST_SERVER=1) Cópias do `most` e da biblioteca MOST para rodar o servidor MSS na própria OMAP.
    Só strings de nomes de papel mudam (mesmo tamanho); nada do SWFL é alterado, as cópias vão para o shim.
      servidor: `--devmode=master`, exporta "MOSTSrvSystem.<iface>" (binário e biblioteca com o nome-base trocado);
      cliente : importa "MOSTSrvSystem.<iface>" em vez de "MOSTSubSystemServer.<iface>"""
    T = ROLE_TOKEN
    srv, cli, slib = bytearray(most), bytearray(most), bytearray(lib)
    ns = _sub(srv, b'MOSTSubSystem.', T + b'.') + _sub(srv, b'MOSTSubSystem\0', T + b'\0') + _sub(slib, b'MOSTSubSystem\0', T + b'\0') \
        + _sub(slib, b"mssrolename 'MOSTSubSystem'", b"mssrolename 'MOSTSrvSystem'")
    nc = 0
    for o in (b'NetworkManagementProvider.MOSTSubSystemServer\0', b'MOSTSubSystemServer.DSYSMOSTServer\0', b'MOSTSubSystemServer.DSYSNetworkManagement\0'):
        nc += _sub(cli, o, o.replace(b'MOSTSubSystemServer', T))
    if ns < 5 or nc < 3:
        raise BuildError('most: nomes de papel não encontrados (SWFL diferente do validado: %d/%d)' % (ns, nc))
    return bytes(srv), bytes(cli), bytes(slib), (ns, nc)


class BuildError(Exception):
    pass


with open(os.path.join(HERE, 'data', 'known_hmi.json')) as _known_hmi_file:
    SHIM_PROFILES = json.load(_known_hmi_file)['profiles']
SHIM_HMI_HASHES = {name: files['hmi'] for name, files in SHIM_PROFILES.items()}


def shim_libdir(env):
    profile = env.get('shim_profile')
    if not profile or profile == 'default':
        return os.path.join(HERE, 'shim', 'lib')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', profile):
        raise BuildError('invalid shim profile name')
    return os.path.join(HERE, 'shim', 'lib-' + profile)


def validate_shim_profile(env, hmi_sha256, library_hashes=None):
    """Return whether the exact firmware/profile set is validated; reject known mismatches."""
    selected = env.get('shim_profile') or 'default'
    expected = SHIM_PROFILES.get(selected)
    if not expected:
        raise BuildError('shim profile %s has no registered HmiMain3D hash' % selected)
    explicit = selected != 'default'
    if hmi_sha256 != expected['hmi']:
        if explicit:
            raise BuildError('shim profile %s requires HmiMain3D %s, got %s' % (selected, expected['hmi'], hmi_sha256))
        for profile, files in SHIM_PROFILES.items():
            if profile != 'default' and hmi_sha256 == files['hmi']:
                raise BuildError('HmiMain3D requires shim profile %s' % profile)
        return False
    libraries = library_hashes or {}
    for name, digest in expected.items():
        if name == 'hmi':
            continue
        actual = libraries.get(name)
        if actual != digest:
            if explicit:
                raise BuildError('shim profile %s requires %s %s, got %s' % (selected, name, digest, actual))
            return False
    return True


def sha256_file(p, limit=None):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        rem = limit
        while True:
            b = f.read(1 << 22 if rem is None else min(1 << 22, rem))
            if not b: break
            h.update(b)
            if rem is not None:
                rem -= len(b)
                if rem <= 0: break
    return h.hexdigest()

def _walk_files(root):
    for dp, dn, fn in os.walk(root):
        dn.sort()
        for f in sorted(fn):
            p = os.path.join(dp, f)
            yield os.path.relpath(p, root), p

def build(env, env_dir, log=print, progress=lambda pct, step: None):
    _last = [None]
    _p = progress
    def progress(pct, step):
        if _last[0] != (pct, step):
            _last[0] = (pct, step); _p(pct, step)
    t0 = time.time()
    img_dir = os.path.join(env_dir, 'images'); work = os.path.join(env_dir, 'work')
    shutil.rmtree(work, ignore_errors=True); os.makedirs(work); os.makedirs(img_dir, exist_ok=True)
    sw = env['swfl']
    for role in ('os', 'brand', 'hmi'):
        if not sw.get(role) or not os.path.isfile(sw[role]):
            raise BuildError('Arquivo SWFL ausente para o papel "%s": %s' % (role, sw.get(role)))
    manifest = {'swfl': {}, 'built_with': 'IDEmu 0.1'}
    # 1) extrair
    progress(2, 'Lendo pacotes SWFL')
    trees = {}
    for i, role in enumerate(('os', 'brand', 'hmi')):
        out = os.path.join(work, role); os.makedirs(out)
        log('Extraindo %s (%s)...' % (role, os.path.basename(sw[role])))
        sel = (lambda tp, n, m: tp.startswith(ISTEP) or (role == 'os' and tp.rstrip('/') == 'fs/sda2' and n == 'boot1.ifs'))
        files = swfl.extract(sw[role], out, sel, progress=lambda f, i=i: progress(2 + int((i + f) * 6), 'Extraindo ' + role))
        trees[role] = out
        manifest['swfl'][role] = {'file': os.path.basename(sw[role]), 'sha256': sha256_file(sw[role], 1 << 26), 'files': len(files)}
        log('  %d arquivos' % len(files))
    istep = {r: os.path.join(trees[r], ISTEP) for r in trees}
    # 2) boot.ifs
    progress(22, 'Montando imagem de boot (IFS)')
    b1 = os.path.join(trees['os'], 'fs/sda2/boot1.ifs')
    if not os.path.isfile(b1):
        raise BuildError('boot1.ifs não encontrado no pacote do sistema (SWFL "os")')
    TOOLS = 'ls cat cp mkdir mount devb-ram pidin sleep mv rm grep sed find dd pipe chmod ln tail uname umount df du sloginfo date wc waitfor'.split()
    tools = []
    for n in TOOLS:
        p = os.path.join(istep['os'], 'bin', n)
        if not os.path.isfile(p): raise BuildError('ferramenta ausente no sistema: bin/' + n)
        tools.append((open(p, 'rb').read(), 'bin/' + n))
    tools.append((open(os.path.join(istep['os'], 'lib/fs-qnx4.so'), 'rb').read(), 'lib/fs-qnx4.so'))
    open(os.path.join(img_dir, 'boot.ifs'), 'wb').write(ifs.make_boot_ifs(open(b1, 'rb').read(), tools))
    log('boot.ifs ok')
    # 3) sda.img
    progress(28, 'Montando disco do sistema (QNX4)')
    tree = {}   # relpath -> srcpath
    for role in ('os', 'brand', 'hmi'):
        for rel, p in _walk_files(istep[role]):
            r = rel.replace(os.sep, '/')
            if r.startswith(RO) or r.lower().startswith(RO.lower()):
                continue
            if any(r.startswith(x) for x in OS_EXCLUDE) or os.path.basename(r).startswith('._'):
                continue
            tree[r] = p
    t = mkdisk.Tree()
    total = 0
    for rel in sorted(tree):
        total += os.path.getsize(tree[rel])
    if total > SDA_SECTORS * 512 * 0.93:
        raise BuildError('conteúdo do sistema (%d MB) não cabe no disco em RAM de 480 MB' % (total >> 20))
    dirs = set()
    base = '/repository/istep/'
    for rel in sorted(tree):
        if len(os.path.basename(rel)) > 48: continue
        parts = rel.split('/')
        for i in range(1, len(parts)):
            d = '/'.join(parts[:i])
            if d not in dirs:
                dirs.add(d)
    t.mkdir('/repository', 0o40775); t.mkdir('/repository/istep', 0o40775)
    for d in sorted(dirs):
        t.mkdir(base + d, 0o40775)
    skipped_long = []
    for rel in sorted(tree):
        p = tree[rel]
        if len(os.path.basename(rel)) > 48:
            skipped_long.append(rel); continue
        with open(p, 'rb') as f:
            m = f.read(4)
        mode = 0o100755 if (m == b'\x7fELF' or m[:2] == b'#!') else 0o100644
        t.add(base + rel, mode, p, os.path.getsize(p))
    if skipped_long:
        log('AVISO: %d arquivo(s) com nome > 48 caracteres não cabem no QNX4 e foram omitidos: %s' % (len(skipped_long), ', '.join(os.path.basename(x) for x in skipped_long[:5])))
    manifest['skipped_long_names'] = skipped_long
    log('sda: %d arquivos, %d MB' % (len(tree) - len(skipped_long), total >> 20))
    mkdisk.write(t, os.path.join(img_dir, 'sda.img'), SDA_SECTORS)
    progress(55, 'Disco do sistema pronto')
    # 4) sdb.img (dados do HMI, QNX6, somente leitura)
    progress(56, 'Montando disco de dados do HMI (QNX6)')
    chassis = env.get('chassis', '')
    root = mkq6.N(b'/', 0o40775); ro = mkq6.N(b'ro', 0o40775); root.kids[b'ro'] = ro
    ro_src = os.path.join(istep['hmi'], RO)
    if not os.path.isdir(ro_src):
        raise BuildError('dados do HMI (data/ro) não estão no pacote "hmi"')
    keep_ego = chassis + '.zip'
    def skip_hmi(p):
        rel = os.path.relpath(p, ro_src)
        if rel == 'bmwm': return True
        if '/ego_model/' in '/' + rel.replace(os.sep, '/') + '/' and os.path.isfile(p) and os.path.basename(p) != keep_ego:
            return True
        return False
    mkq6.from_host(ro, ro_src, skip_hmi)
    brand_ro = os.path.join(istep['brand'], RO)
    if os.path.isdir(brand_ro):
        for b in sorted(os.listdir(brand_ro)):
            bp = os.path.join(brand_ro, b)
            if not os.path.isdir(bp): continue
            n = ro.kids.get(b.encode()) or mkq6.N(b.encode(), 0o40775); ro.kids[b.encode()] = n
            mkq6.from_host(n, bp, lambda p, bp=bp: False)     # inclui id5/ (10 MB): é o que HMI_ID_VERSION=id5 usa
    tpl = os.path.join(work, 'q6_template.img')
    open(tpl, 'wb').write(zlib.decompress(open(os.path.join(HERE, 'qnxfs', 'q6_template.img.z'), 'rb').read()))
    mkq6.build(root, tpl, os.path.join(img_dir, 'sdb.img'))
    os.unlink(tpl)
    progress(80, 'Disco de dados pronto')
    # 5) shim.img — validate the exact HMI and hooked libraries before selecting a fixed-address profile
    progress(82, 'Montando camada de tradução (shim)')
    hm = tree.get('opt/hmi/ID5/bin/HmiMain3D')
    manifest['shim_profile'] = env.get('shim_profile', 'default')
    manifest['hmi_sha256'] = sha256_file(hm) if hm else None
    library_hashes = {}
    for name in ('libhmicom.so', 'libhmicoding.so'):
        path = tree.get('opt/hmi/ID5/lib/' + name)
        library_hashes[name] = sha256_file(path) if path else None
    manifest['shim_library_sha256'] = library_hashes
    manifest['hmi_validated'] = validate_shim_profile(env, manifest['hmi_sha256'], library_hashes)
    build_shim(env, istep['os'], os.path.join(img_dir, 'shim.img'), log)
    # 6) assinatura do HMI + manifesto
    if not manifest['hmi_validated']:
        log('AVISO: este HmiMain3D não é uma das versões validadas; os patches em memória do shim podem falhar.')
    manifest['images'] = {n: os.path.getsize(os.path.join(img_dir, n)) for n in ('boot.ifs', 'sda.img', 'sdb.img', 'shim.img')}
    manifest['seconds'] = round(time.time() - t0, 1)
    json.dump(manifest, open(os.path.join(env_dir, 'build.json'), 'w'), indent=1)
    shutil.rmtree(work, ignore_errors=True)
    progress(100, 'Pronto')
    return manifest

def build_shim(env, os_istep, out, log=print):
    t = mkdisk.Tree()
    t.mkdir('/lib', 0o40775)
    libdir = shim_libdir(env)
    if not os.path.isdir(libdir):
        raise BuildError('shim library directory does not exist: %s' % libdir)
    for f in sorted(os.listdir(libdir)):
        p = os.path.join(libdir, f)
        t.add('/lib/' + f, 0o100755, p, os.path.getsize(p))
    # tabela de codificação do carro virtual
    tab, n, warn = codegen.build_table(codegen.profile_for(env))
    for w in warn: log('codificação: ' + w)
    t.add('/coding.tab', 0o100644, tab, len(tab))
    # variantes internas forçadas (id -> 0/1): o shim lê /fs/shim/variants.bin (u32 LE: id | valor << 31)
    vt = b''.join(struct.pack('<I', (int(k, 0) & 0xffff) | (int(bool(v)) << 31)) for k, v in sorted((env.get('variants') or {}).items()))
    if vt: t.add('/variants.bin', 0o100644, vt, len(vt))
    # serviços: números do starter.cfg do próprio SWFL
    cfg = open(os.path.join(os_istep, 'opt/sys/etc/starter.cfg'), errors='replace').read()
    procs = []
    for q in re.findall(r'<Process>(.*?)</Process>', cfg, re.S):
        g = lambda tag: (re.search('<%s>(.*?)</%s>' % (tag, tag), q, re.S) or [None, ''])[1].strip()
        procs.append((g('Name'), g('Args')))
    rc = ['#!/bin/ksh', '# serviços mínimos da head unit virtual (substitui o starter original, que depende do hardware)']
    for nm_, sub, bg in SERVICES:
        hit = [p for p in procs if os.path.basename(p[0]) == nm_ and ((p[1] == sub[1:]) if sub.startswith('=') else (sub in p[1]))]
        if not hit: raise BuildError('serviço "%s" não existe no starter.cfg deste sistema' % nm_)
        nm, ar = hit[0]
        if nm_ == 'servicebroker':
            # no hardware o servicebroker da OMAP é *slave* de um master no outro processador (-m160.48.199.119:3746), onde vive o papel
            # MOSTSubSystemServer; aqui ele roda como master único e o papel é registrado nele (ver idemu/most.py)
            ar = re.sub(r'\s*-m\S+', '', ar)
        if nm_ == 'io-ipc':
            # transporte virtual do V850 (ver src/v850): mesmo io-ipc/decodificador do SWFL, outro "tchannel"
            ar = ar.replace('/etc/io-ipc-o5.cfg', '/fs/shim/io-ipc.cfg')
        pre, lg = '', '/dev/null'
        if nm_ == 'start_net.sh':
            rc += ['/bin/pfctl -f /etc/pf.conf -e > /dev/null 2>&1', 'echo done > /dev/shmem/start_net.done',
                   'sysctl -w net.inet6.ip6.forwarding=1 net.inet.ip.forwarding=1 > /dev/null 2>&1',
                   '[ -n "$IDEMU_TCPDUMP" ] && (tcpdump -i lo0 -s 0 -w /dev/shmem/c.pcap > /dev/null 2>&1 &)   # depuração: captura do loopback']
            continue
        if nm_ == 'most' and os.environ.get('IDEMU_MOST_SERVER'):
            lib_p = os.path.join(os_istep, 'opt/sys/lib/libimp_sys_most_base_nbt.cpp-ne.so.17')
            msrv, mcli, mlib, cnt = make_most_pair(open(os.path.join(os_istep, 'opt/sys/bin/most'), 'rb').read(), open(lib_p, 'rb').read())
            t.add('/most_srv', 0o100755, msrv, len(msrv)); t.add('/most_cli', 0o100755, mcli, len(mcli))
            t.add('/srvlib/libimp_sys_most_base_nbt.cpp-ne.so.17', 0o100755, mlib, len(mlib))
            log('most servidor/cliente: %s nomes de papel trocados' % (cnt,))
            srv_args = re.sub(r'--devmode=client\s*--serverRoleName=\S+', '--devmode=master', ar)
            rc.append('LD_LIBRARY_PATH=/fs/shim/srvlib:$LD_LIBRARY_PATH IPC_IP_ADDRESS=127.0.0.1 /fs/shim/most_srv %s > /var/most_srv.log 2>&1 &' % srv_args)
            rc.append('sleep 3')
            nm = '/fs/shim/most_cli'
            ar = ar.replace('--serverRoleName=MOSTSubSystemServer', '--serverRoleName=' + ROLE_TOKEN.decode())
        if nm_ == 'most' and not os.environ.get('IDEMU_MOST_CLIENT'):
            # um único `most` em modo master = servidor MSS local, no lugar do papel remoto do J5 (que não existe aqui); os FBlocks do carro
            # vêm do V850 virtual pela ponte do canal 25 (idemu/most.py).  IDEMU_MOST_CLIENT=1 volta ao modo cliente original.
            ar = re.sub(r'--devmode=client\s*--serverRoleName=\S+', '--devmode=master', ar)
        if nm_ == 'most':
            # V850_MOSTSUBNET_OMAP_DIRECT_REGISTRATION=1 (definida pelo starter.cfg do SWFL): liga a ponte DSI do `most` em /dev/ipc/ipc25, pela qual
            # o V850 registra sua sub-rede MOST direto na OMAP (é o caminho dos dados do carro); IPC_IP_ADDRESS só aponta o SIPC para o loopback
            pre, lg = 'V850_MOSTSUBNET_OMAP_DIRECT_REGISTRATION=1 IPC_IP_ADDRESS=127.0.0.1 ', '/var/most.log'
            # 0 desliga o watchdog do `most` ("application most started (watchdog is disabled)"): o guest pode passar segundos sem CPU (a VM é mais lenta que o hardware) e o watchdog5-omap o mataria
            # com SIGKILL ("Killed" em /var/most.log). IDEMU_MOST_HEARTBEAT troca o valor.
            ar = re.sub(r'--heartbeat-interval=\d+', '--heartbeat-interval=' + os.environ.get('IDEMU_MOST_HEARTBEAT', '0'), ar)
        if os.environ.get('IDEMU_RC_TRACE'): rc.append('echo "== $(date) %s"' % nm_)
        rc.append('%s%s %s%s' % (pre, nm, ar, (' > %s 2>&1 &' if bg else ' > %s 2>&1') % lg))
        w = READY.get(nm_)
        if w: rc.append('waitfor %s 20' % w)
        if nm_ == 'servicebroker':
            rc.append('[ -n "$IDEMU_SB_VERBOSE" ] && echo verbose=$IDEMU_SB_VERBOSE > /srv/servicebroker   # depuração do servicebroker')
    ioc = open(os.path.join(os_istep, 'etc/io-ipc-o5.cfg'), errors='replace').read()
    ioc, nsub = re.subn(r'^tchannel=.*$', 'tchannel=t_index=0,filename=ioipc-idemu.so,subopts="idemu=1"', ioc, flags=re.M)
    if nsub != 1: raise BuildError('io-ipc-o5.cfg: linha tchannel não encontrada')
    iob = ioc.encode(); t.add('/io-ipc.cfg', 0o100644, iob, len(iob))
    lvl = os.environ.get('IDEMU_MOST_TRACE')      # depuração: liga o trace de todos os escopos do `most` (nível 1..7)
    if lvl:
        pt = bytearray(open(os.path.join(os_istep, 'opt/sys/etc/persistTracemost.bin'), 'rb').read())
        # tabela de escopos: [nível:2][endereço:4][0x2200:2]; só os do MSS/NAL/registry (idemu/data/most_trace_scopes.json, SWFL 007_051_002)
        for k in json.load(open(os.path.join(HERE, 'data', 'most_trace_scopes.json'))):
            pt[8 + 8 * k] = int(lvl)
        lib = pt.find(b'libSysMoCCAFrameworkSharedSo')      # escopos do framework MoCCA (DSI, servicebroker, registry): [contagem:4][ptr:4][0x2200][nível:2]*
        if lib > 0 and os.environ.get('IDEMU_MOCCA_TRACE'):
            q = pt.find(b'\x79\x00\x00\x00', lib)
            for n in range(121):
                pt[q + 4 + 8 * n + 6] = int(os.environ['IDEMU_MOCCA_TRACE'])
        t.add('/persistTracemost.bin', 0o100644, bytes(pt), len(pt))
        rc.insert(2, 'cp /fs/shim/persistTracemost.bin /var/opt/sys/persistTracemost.bin')
    for i, l in enumerate(rc):      # diagnóstico: registra como o `most` terminou (status 128+sinal) em /var/most.exit
        if '/opt/sys/bin/most ' in l and l.rstrip().endswith('&'):
            rc[i] = '( ' + l.rstrip()[:-1].rstrip() + '; echo "most exit status $? $(date)" >> /var/most.exit ) &'
    rcb = ('\n'.join(rc) + '\n').encode()
    t.add('/rc.sh', 0o100755, rcb, len(rcb))
    cd = env.get('coding', {})
    envsh = '\n'.join([
        '# variáveis do carro virtual (geradas pelo IDEmu)',
        'export HMI_BRAND=%s' % {'bmw': '00', 'mini': '02', 'rr': '03', 'mcv': '01'}.get(env.get('brand', 'bmw'), '00'),
        'export IDEMU_CHASSIS=%s IDEMU_VIN=%s' % (env.get('chassis', ''), cd.get('vin', '')),
        # -h do HmiMain3D (boot.sh). Na carga do perfil da chave (Vehicle 0x224 CIgnitionKey, 11-15 s no thread principal) o "SvcDSI watchdog" matava o HMI
        # (saída 138) quando passava de ~13 s, o que acontece com o telefone codificado (PHONE_TYPE). Com 40000 a sonda é criada com 480 s em vez de 120 s e o HMI sobrevive.
        'export IDEMU_HMI_HEARTBEAT=%d' % int(os.environ.get('IDEMU_HMI_HEARTBEAT') or 40000),
    ]) + '\n'
    eb = envsh.encode(); t.add('/env.sh', 0o100755, eb, len(eb))
    # plugins de teste: idemu/plugins/<Nome>/* vira /plug/<Nome>/* (boot.sh liga como .../data/ro/Plugins)
    pdir = os.path.join(HERE, 'plugins')
    if os.path.isdir(pdir):
        t.mkdir('/plug', 0o40775)
        for pn in sorted(os.listdir(pdir)):
            pp = os.path.join(pdir, pn)
            if not os.path.isdir(pp): continue
            t.mkdir('/plug/' + pn, 0o40775)
            for f in sorted(os.listdir(pp)):
                fp = os.path.join(pp, f)
                t.add('/plug/%s/%s' % (pn, f), 0o100755 if f.endswith('.so') else 0o100644, fp, os.path.getsize(fp))
    bs = open(os.path.join(HERE, 'guest', 'boot.sh'), 'rb').read()
    t.add('/boot.sh', 0o100755, bs, len(bs))
    ag = open(os.path.join(HERE, 'guest', 'agent.sh'), 'rb').read()
    t.add('/agent.sh', 0o100755, ag, len(ag))
    mkdisk.write(t, out, SHIM_SECTORS)
