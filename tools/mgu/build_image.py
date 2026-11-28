#!/usr/bin/env python3
"""Monta o iDrive 8 (MGU22) a partir da PSdZData, sem alterá-la. Saída em <projeto>/mgu22 (cerca de 2,5 GB).
Uso: build_image.py [psdzdata] [--car g70bev]  (o carro precisa bater com SERIES em MGU22_Coding.txt)"""
import gzip, json, os, shutil, stat, struct, subprocess, sys, tarfile, tempfile
import posixpath
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, 'mgu22')
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
from ext4ls import E4
from idemu import catalog

def simg(src, dst):
    subprocess.check_call([sys.executable, os.path.join(HERE, 'simg2raw.py'), src, dst])

def member(tarpath, name, dst):
    with tarfile.open(tarpath) as t:
        src = t.extractfile(name)
        with open(dst, 'wb') as o: shutil.copyfileobj(src, o, 1 << 20)

def ext2cpio(img, cpio, src='/', pfx=''):
    subprocess.check_call([sys.executable, os.path.join(HERE, 'ext2cpio.py'), img, cpio, src, pfx])

def msys_bash():
    """Windows: o bash do MSYS2 (o do System32 é o do WSL e não serve). Procura em IDEMU_MSYS2 e nas pastas usuais."""
    roots = [os.environ.get('IDEMU_MSYS2'), os.path.join(os.environ.get('SystemDrive', 'C:') + os.sep, 'msys64'), os.path.expanduser('~/msys64'), r'C:\msys64']
    for r in roots:
        if r:
            b = os.path.join(r, 'usr', 'bin', 'bash.exe')
            if os.path.isfile(b): return b
    raise RuntimeError('MSYS2 não encontrado (procurei IDEMU_MSYS2 e C:\\msys64): instale o MSYS2 e rode windows\\build-native.sh, ou defina IDEMU_MSYS2')

def build_guest(sysroot, gdir):
    """Compila as peças do guest (aarch64) e do host. macOS: src/mgu22/build.sh (zsh). Windows: src/mgu22/build-windows.sh no shell MINGW64 do MSYS2 (clang + ld.lld + gcc)."""
    if os.name != 'nt':
        subprocess.check_call(['zsh', os.path.join(ROOT, 'src/mgu22/build.sh'), sysroot, gdir])
        return
    zig = os.environ.get('IDEMU_MGU_ZIG')
    if zig:
        from build_guest_windows import build
        build(sysroot, gdir, os.path.abspath(zig))
        return
    fw = lambda p: os.path.abspath(p).replace('\\', '/')
    env = dict(os.environ, MSYSTEM='MINGW64', CHERE_INVOKING='1', PYTHON=fw(sys.executable), PYTHONUTF8='1')
    # captura a saída: sem console (CREATE_NO_WINDOW) o bash do MSYS2 não repassa o stderr ao log do IDEmu, e uma falha ficaria sem mensagem
    r = subprocess.run([msys_bash(), '-l', fw(os.path.join(ROOT, 'src/mgu22/build-windows.sh')), fw(sysroot), fw(gdir)], env=env, creationflags=0x08000000,
                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
    print(r.stdout[-3000:], flush=True)
    if r.returncode: raise RuntimeError('a compilação do guest falhou (código %d): %s' % (r.returncode, ' / '.join(r.stdout.strip().splitlines()[-4:])))

def main():
    psdz = next((a for a in sys.argv[1:] if not a.startswith('--')), None)
    if not psdz:
        psdz = json.load(open(os.path.join(ROOT, 'settings.json')))['psdz_path']
    _, version, files = catalog.mgu22_firmware(psdz, include_staged=False)
    missing = [os.path.basename(path) for _, path in files if not os.path.isfile(path)]
    if missing:
        raise RuntimeError('faltam arquivos do iDrive 8: ' + ', '.join(missing))
    packages = {item['id']: path for item, path in files}
    print('Firmware MGU22:', version)
    tmp = tempfile.mkdtemp(prefix='mgu22', dir=os.path.dirname(OUT)); os.makedirs(OUT, exist_ok=True)
    try:
        print('kernel e raiz'); f = packages['00009ff7']
        member(f, 'sa81x5-boot.img.bin.gz', tmp + '/boot.gz')
        b = gzip.open(tmp + '/boot.gz').read()
        assert b[:8] == b'ANDROID!'
        ks, ps = struct.unpack_from('<I', b, 8)[0], struct.unpack_from('<I', b, 36)[0]
        open(OUT + '/Image', 'wb').write(b[ps:ps + ks]); del b
        member(f, 'mgu22-bmw-image-mgu22-sa8155.ext4.simg.bin.gz', tmp + '/root.gz')
        simg(tmp + '/root.gz', tmp + '/root.raw'); os.unlink(tmp + '/root.gz')
        print('IVI e EXT')
        member(packages['00009fc6'], 'mgu22-ivi-sa8155.ext4.simg.bin.gz', tmp + '/ivi.gz')
        simg(tmp + '/ivi.gz', tmp + '/ivi.raw'); os.unlink(tmp + '/ivi.gz')
        member(packages['00009ff9'], 'mgu22-ext-sa8155.ext4.simg.bin.gz', tmp + '/ext.gz')
        simg(tmp + '/ext.gz', tmp + '/ext.raw'); os.unlink(tmp + '/ext.gz')
        # raiz do link das bibliotecas do guest e tabela de codificação
        sysroot = OUT + '/sysroot'; os.makedirs(sysroot + '/lib', exist_ok=True); os.makedirs(sysroot + '/usr/lib', exist_ok=True)
        r = E4(tmp + '/root.raw')
        def grab(e, p, dst):
            t = e.inode(e.lookup(p))
            while stat.S_ISLNK(e.mode(t)):
                p = posixpath.join(posixpath.dirname(p), e.data(t).decode()); t = e.inode(e.lookup(p))      # caminhos do guest: sempre com /
            with open(dst, 'wb') as o: o.write(e.data(t))
        grab(r, '/lib/libc.so.6', sysroot + '/lib/libc.so.6')
        for n in ('libwayland-client.so.0', 'libwayland-server.so.0', 'libivi-application.so.1', 'libivi-controller.so.1', 'libdbus-1.so.3'):
            grab(r, '/usr/lib/' + n, sysroot + '/usr/lib/' + n)
        grab(r, '/usr/share/sysfunc/coding/cafd_mgu_02_a.bin', tmp + '/cafd.bin')
        r.close()                                   # Windows: não apaga arquivo aberto (root.raw é apagado mais adiante)
        iv = E4(tmp + '/ivi.raw')
        grab(iv, '/rootfs/usr/share/hmi/data/ro/MGU22_Coding.txt', tmp + '/coding.txt')
        iv.close()
        gdir = OUT + '/guest'; os.makedirs(gdir, exist_ok=True)
        build_guest(sysroot, gdir)
        subprocess.check_call([sys.executable, os.path.join(HERE, 'gencoding.py'), tmp + '/cafd.bin', tmp + '/coding.txt', gdir + '/coding.tab'])
        import gen_coding8; gen_coding8.write(gen_coding8.build(tmp + '/cafd.bin', tmp + '/coding.txt'), OUT + '/coding8.json')
        print('cpio')
        ext2cpio(tmp + '/root.raw', tmp + '/root.cpio')
        ext2cpio(tmp + '/ivi.raw', tmp + '/ivi.cpio', '/rootfs', '/opt/ivi/rootfs')
        ext2cpio(tmp + '/ext.raw', tmp + '/ext.cpio', '/rootfs', '/opt/ext/rootfs')
        for n in ('root', 'ivi', 'ext'): os.unlink(f'{tmp}/{n}.raw')
        print('dados da marca e do carro (SWFK)')
        pk = [('a6b1', 'hmi-data.bmw', 'var/begu/hmi-data/bmw'), ('a6b0', 'hmi-data.bmw-shared', 'var/begu/hmi-data/bmw-shared'),
              ('a6a6', 'hmi-vehicles.g70bev', 'var/begu/hmi-vehicles/G70BEV')]
        cps = []
        for a, b_, dst in pk:
            n = f'swfk-0000{a}.{b_}.ext4.bin.gz'
            member(packages[f'0000{a}'], n, tmp + '/p.gz')
            with gzip.open(tmp + '/p.gz') as g, open(tmp + '/p.raw', 'wb') as o: shutil.copyfileobj(g, o, 1 << 20)
            c = f'{tmp}/{a}.cpio'; ext2cpio(tmp + '/p.raw', c, '/', dst); cps.append(c)
            os.unlink(tmp + '/p.gz'); os.unlink(tmp + '/p.raw')
        print('juntando')
        # sem compressão: run.py copia isto direto para a RAM do guest e o kernel só desempacota
        with open(OUT + '/base.cpio', 'wb') as o:
            for c in [tmp + '/root.cpio', tmp + '/ivi.cpio', tmp + '/ext.cpio'] + cps:
                with open(c, 'rb') as f: shutil.copyfileobj(f, o, 1 << 20)
                os.unlink(c)
        print('pronto:', OUT)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == '__main__':
    main()
