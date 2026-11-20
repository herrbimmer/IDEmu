"""iDrive 7 (MGU, x86-64 Linux): monta a raiz do RSE a partir da PSdZData e roda QEMU x86-64 (TCG) + glhost7.
O HMI do banco traseiro (HmiMain3D, RSE_HIGH_LEFT) desenha pela ponte GL (ttyS1) e recebe toque pela serial ttyS0 (idemu-wl -> wl_pointer). Detalhes em docs/OUTRAS_GERACOES.md (parte 6)."""
import glob, mmap, os, re, shutil, socket, struct, subprocess, sys, threading, time, zlib
from . import runtime, coding7

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, 'tools', 'mgu')
GUEST = os.path.join(ROOT, 'idemu', 'guest7')
OUT = os.path.join(ROOT, 'mgu7')
APP_IDS = '566c 566d 566e 566f 5670 5671 5672 5673 5675 5678 567a'.split()
DATA_IDS = '566b 567b 567c 567d 567e 5682 5683'.split()
KERNEL_PKG = '00005684'; KERNEL_VER = '036_010_004'; KERNEL_SKIP = 480        # /ias_rsu = 480 B de cabeçalho + bzImage
APP_VER = '030_016_002'                                                       # os offsets de patch_rse.py valem para esta versão
IMG_MB = 4096
# serviços SOME/IP do head unit que o HU_HMI espera (tools/mgu/gen_fakesvc.py -> /etc/idemu/fakesvc.tab; campo=hex troca o valor padrão)
FAKE_SERVICES = ['Lifecycle=powerStateDetailed=63,powerStateDetailedExternal=63ffffffff7fffffffffff,rseLock=03', 'Key', 'VehicleCondition',
                 # dados do carro (valores padrão "sem sinal"): relógio e cluster (KombiIF), veículo, clima, pneus, consumo, comandos do console central...
                 '0xb51b', '0xb011', '0xb510', '0xb519', '0xb511', '0xb516', '0xb508', '0xb50c', '0xb506', '0xb517', '0xb504', '0xb505', '0xb512', '0xb513', '0xb514', '0xb51f', '0xb51e', '0xb50d', '0xb50e']
BOOT_ESTIMATE = 125                                                            # s: medido 110–120 s até o primeiro quadro (era 237 s antes do anel de memória compartilhada e do init em paralelo)
BUILD_STEPS = [('app ', 5, 'Extraindo o sistema do RSE'), ('data ', 45, 'Extraindo os dados do HMI'), ('kernel', 70, 'Extraindo o kernel'),
               ('overlay', 75, 'Aplicando os ajustes do emulador'), ('imagem', 85, 'Gravando a imagem do sistema')]
GUEST_FILES = {'idemu-run': 'usr/bin/idemu-run', 'idemu-wl': 'usr/bin/idemu-wl', 'libGLESv2.so.2': 'usr/lib/libGLESv2.so.2', 'libEGL.so.1': 'usr/lib/libEGL.so.1',
               'libspy.so': 'usr/lib/libspy.so', 'libipc.so.1': 'usr/lib/idemu/libipc.so.1', 'idemu-fakesvc': 'usr/bin/idemu-fakesvc', 'libfastclock.so': 'usr/lib/idemu/libfastclock.so'}

# Botões do controlador -> teclas do Linux que o HMI trata em CHmiWindowInputHandler::keyboardPressed (medido no HU_HMI: o código do controlador que ele gera
# está ao lado). Os códigos de botão são os da interface web (idemu/web/run.js). MAP (5) e NAV (7) não têm tecla nesse mapa.
KEYS = {1: 63,    # MENU     F5  -> controlador 1
        2: 14,    # BACK     Backspace -> 2
        3: 24,    # OPTION   O   -> 3
        4: 59,    # MEDIA    F1  -> 4
        6: 60,    # COM      F2  -> 6
        8: 57,    # PUSH     Espaço -> 8
        9: 103, 10: 108, 11: 105, 12: 106}    # inclinar: setas -> 9..12
KEY_ROTOR_RIGHT, KEY_ROTOR_LEFT = 1000 + 50, 1000 + 49    # M e N -> controlador 13 e 14 (giro à direita e à esquerda)

def guest_stamp():
    """Hash de tudo que entra na imagem além do firmware: scripts de init, overlay, binários do guest, patches, serviços falsos. Mudou algo -> a imagem é refeita."""
    import hashlib
    h = hashlib.sha1(); h.update(repr((FAKE_SERVICES, IMG_MB, APP_VER)).encode())
    files = [os.path.join(GUEST, f) for f in sorted(GUEST_FILES)] + [os.path.join(TOOLS, f) for f in ('idemu-init.sh', 'patch_rse.py', 'gen_fakesvc.py', 'gen_coding7.py')]
    for dp, dn, fn in os.walk(os.path.join(TOOLS, 'rse_overlay')): files += [os.path.join(dp, f) for f in sorted(fn)]
    for f in files:
        h.update(os.path.relpath(f, ROOT).encode())
        try: h.update(open(f, 'rb').read())
        except OSError: h.update(b'-')
    return h.hexdigest()
def image_ready():
    if not (os.path.isfile(OUT + '/root.img') and os.path.isfile(OUT + '/bzImage')): return False
    try: return open(OUT + '/stamp').read().strip() == guest_stamp()
    except OSError: return False
def glhost_path(): return os.path.join(ROOT, 'bin', 'glhost7')

def swfl_dir(psdz): return os.path.join(psdz, 'swe', 'swfl')
def pick(psdz, sid, ver=None):
    fs = sorted(glob.glob(os.path.join(swfl_dir(psdz), 'swfl_%s.bin.*' % sid)))
    if not fs: raise RuntimeError('pacote swfl_%s não encontrado em %s' % (sid, swfl_dir(psdz)))
    if ver:
        for f in fs:
            if f.endswith('.' + ver): return f
    return fs[-1]
def required_packages(psdz):
    return [pick(psdz, '0000' + i, APP_VER) for i in APP_IDS + DATA_IDS] + [pick(psdz, KERNEL_PKG, KERNEL_VER)]

def build(psdz, log=print, progress=lambda p, s: None):
    """Extrai app + data (HAR) para uma pasta de trabalho, aplica o overlay do IDEmu, os patches e grava mgu7/root.img + mgu7/bzImage (≈ 3,3 GB temporários)."""
    if not psdz: raise RuntimeError('escolha a pasta da PSdZData nas configurações')
    work = os.path.join(OUT, 'work'); root = os.path.join(work, 'root')
    shutil.rmtree(work, ignore_errors=True); os.makedirs(root)
    try:
        har = [sys.executable, '-I', TOOLS + '/har.py']
        n = len(APP_IDS) + len(DATA_IDS)
        for i, sid in enumerate(APP_IDS + DATA_IDS):
            kind = 'app' if sid in APP_IDS else 'data'
            progress(5 + int(40 * i / n), 'Extraindo o sistema do RSE' if kind == 'app' else 'Extraindo os dados do HMI')
            f = pick(psdz, '0000' + sid, APP_VER); log('%s %s' % (kind, os.path.basename(f)))
            r = subprocess.run(har + [f, root], capture_output=True, text=True)
            if r.returncode: raise RuntimeError('falha ao extrair %s: %s' % (os.path.basename(f), (r.stderr or r.stdout)[-200:]))
        progress(70, 'Extraindo o kernel')
        k = pick(psdz, KERNEL_PKG, KERNEL_VER); log('kernel ' + os.path.basename(k))
        r = subprocess.run(har + [k, os.path.join(work, 'k'), r'^/ias_rsu$'], capture_output=True, text=True)
        ias = os.path.join(work, 'k', 'ias_rsu')
        if r.returncode or not os.path.isfile(ias): raise RuntimeError('kernel (ias_rsu) não encontrado no pacote do RSU')
        with open(ias, 'rb') as f: f.seek(KERNEL_SKIP); kb = f.read()
        if kb[0x202:0x206] != b'HdrS': raise RuntimeError('o kernel extraído não é um bzImage')
        progress(75, 'Aplicando os ajustes do emulador'); log('overlay')
        shutil.copytree(TOOLS + '/rse_overlay', root, symlinks=True, dirs_exist_ok=True)
        ld = os.path.join(root, 'lib', 'libdl-2.27.so')        # libdl do firmware, copiada para a pasta do IDEmu (não vai no repositório)
        if os.path.isfile(ld):
            os.makedirs(root + '/usr/lib/idemu', exist_ok=True); shutil.copy(ld, root + '/usr/lib/idemu/libdl.so.2')
        shutil.copy(TOOLS + '/idemu-init.sh', root + '/idemu-init'); os.chmod(root + '/idemu-init', 0o755)
        for src, dst in GUEST_FILES.items():
            d = os.path.join(root, dst); os.makedirs(os.path.dirname(d), exist_ok=True); shutil.copy(os.path.join(GUEST, src), d); os.chmod(d, 0o755)
        os.makedirs(root + '/etc/idemu', exist_ok=True)
        r = subprocess.run([sys.executable, '-I', TOOLS + '/gen_fakesvc.py', root + '/etc/oap/someip/someip-interfaces.json', root + '/etc/idemu/fakesvc.tab'] + FAKE_SERVICES, capture_output=True, text=True)
        if r.returncode: raise RuntimeError('gen_fakesvc: ' + (r.stderr or r.stdout)[-300:])
        allow_fake_offers(root, 10007)
        r = subprocess.run([sys.executable, '-I', TOOLS + '/patch_rse.py', root], capture_output=True, text=True); log(r.stdout.strip())
        if r.returncode: raise RuntimeError('patch do RSE: ' + (r.stderr or r.stdout)[-300:])
        r = subprocess.run([sys.executable, '-I', TOOLS + '/gen_coding7.py', root + '/usr/bin/HmiMain3D', OUT + '/coding7.json'], capture_output=True, text=True); log(r.stdout.strip())
        if r.returncode: log('codificação: ' + (r.stderr or r.stdout)[-200:])         # sem o dicionário o editor de codificação não abre, o resto funciona
        progress(85, 'Gravando a imagem do sistema'); log('imagem')
        tmp = OUT + '/root.img.tmp'
        r = subprocess.run([sys.executable, '-I', TOOLS + '/mkext2.py', root, tmp, str(IMG_MB)], capture_output=True, text=True); log(r.stdout.strip()[-200:])
        if r.returncode: raise RuntimeError('mkext2: ' + (r.stderr or r.stdout)[-300:])
        os.replace(tmp, OUT + '/root.img'); open(OUT + '/bzImage', 'wb').write(kb); open(OUT + '/stamp', 'w').write(guest_stamp())
    finally:
        shutil.rmtree(work, ignore_errors=True)

def allow_fake_offers(root, uid):
    """O vsomeip só deixa um usuário oferecer os serviços da sua política (etc/vsomeip/<uid>_<gid>/vsomeip_security.json). O `idemu-fakesvc` roda como o usuário do
    NodeStateManager (sin_nsm, 10007): acrescenta a ele a oferta dos serviços da tabela falsa (etc/idemu/fakesvc.tab)."""
    import json
    path = '%s/etc/vsomeip/%d_%d/vsomeip_security.json' % (root, uid, uid)
    ids = ['0x%s' % l.split()[1] for l in open(root + '/etc/idemu/fakesvc.tab') if l.startswith('S ')]
    d = json.load(open(path))
    for pol in d['security']['policies']:
        c = pol.get('credentials') or {}
        if str(c.get('uid')) == str(uid) and 'allow' in pol:
            offers = pol['allow'].setdefault('offers', [])
            for i in ids:
                if not any(o.get('service', '').lower() == i for o in offers): offers.append({'instance': 'any', 'service': i})
            break
    else: raise RuntimeError('política do uid %d não encontrada em %s' % (uid, path))
    json.dump(d, open(path, 'w'), indent=4)
    # o roteador (vsomeipd) confere a política do cliente na configuração global: copia para lá a política do usuário já com as ofertas novas
    gpath = root + '/etc/vsomeip/vsomeip_security.json'; g = json.load(open(gpath)); mine = [p for p in d['security']['policies'] if str((p.get('credentials') or {}).get('uid')) == str(uid)][0]
    pols = [p for p in g['security']['policies'] if str((p.get('credentials') or {}).get('uid')) != str(uid)]
    g['security']['policies'] = pols + [mine]
    json.dump(g, open(gpath, 'w'), indent=4)

QEMU_OWN = os.path.join(ROOT, 'bin', 'qemu-system-x86_64')       # QEMU 11.1.2 do IDEmu: igual ao oficial + o dispositivo idemu-shm (src/qemu/idemu-shm.c)
QEMU_SHARE = os.path.join(ROOT, 'bin', 'qemu-share')              # firmware (BIOS, VGA) que o QEMU próprio procura
SHM_BYTES = 128 << 20                                              # SHM_SIZE de src/mgu/proto.h
def find_qemu():
    for p in (os.environ.get('IDEMU_QEMU_X86'), QEMU_OWN, shutil.which('qemu-system-x86_64'), '/opt/homebrew/bin/qemu-system-x86_64', '/usr/local/bin/qemu-system-x86_64'):
        if p and os.path.exists(p): return p
    raise RuntimeError('qemu-system-x86_64 não encontrado: instale com "brew install qemu"')
def has_shm(qemu):
    """O QEMU do IDEmu (bin/qemu-system-x86_64) tem o dispositivo idemu-shm: o canal gráfico vai por memória compartilhada (≈ 100x mais rápido que a serial)."""
    return os.path.realpath(qemu) == os.path.realpath(QEMU_OWN) and os.path.isdir(QEMU_SHARE) and not os.environ.get('IDEMU_NO_SHM')
def shm_unlink(name):
    try:
        import ctypes; ctypes.CDLL(None, use_errno=True).shm_unlink(name.encode())
    except Exception: pass

SNAP_TAG = 'idemu'
def qemu_img():
    for p in (os.environ.get('IDEMU_QEMU_IMG'), os.path.join(ROOT, 'bin', 'qemu-img'), shutil.which('qemu-img'), '/opt/homebrew/bin/qemu-img', '/usr/local/bin/qemu-img'):
        if p and os.path.exists(p): return p

def clone_file(src, dst):
    """Cópia instantânea no APFS (clonefile); cópia comum nos demais sistemas de arquivos."""
    try: os.unlink(dst)
    except OSError: pass
    if subprocess.run(['cp', '-c', src, dst], capture_output=True).returncode: shutil.copyfile(src, dst)

class Mgu7Runtime(runtime.Runtime):
    kind = 'mgu7'; disp = (1920, 1080)
    def __init__(self, env_dir, env):
        runtime.Runtime.__init__(self, env_dir, env)
        self.role = env.get('role') or os.environ.get('IDEMU_MGU7_ROLE') or 'hu'      # 'hu' (tela central, 1920x720) ou 'rse' (banco traseiro, 1920x1080)
        if self.role == 'hu': self.disp = (1920, 720)
        self.ctl = self.run; self.frame_path = os.path.join(self.run, 'frame.rgba'); self._lastseq = None
        self.gl = self.q = self.tscfix = None; self.shm = None; self.coding_blob = None; self.wl_ready = threading.Event(); self.snap_dir = os.path.join(env_dir, 'snapshot'); self.snap_state = ''; self._restored = False; self.mon_path = os.path.join(self.run, 'mon.sock'); self.overlay = None; self._con = None; self._con_lock = threading.Lock(); self._inp = None; self._inp_lock = threading.Lock(); self._t_down = 0.0
    def start(self, cold=False):
        self._cold = bool(cold)
        if not image_ready(): raise RuntimeError('imagem do iDrive 7 não montada')
        find_qemu()
        for d in (self.run, self.logd): os.makedirs(d, exist_ok=True)
        for f in ('frame.rgba', 'gl.sock', 'con.sock', 'inp.sock', 'mon.sock', 'gl.ready', 'gl.rec', 'gl.rec.done'):
            try: os.unlink(os.path.join(self.run, f))
            except OSError: pass
        self.state = 'booting'; self.err = None; self.t0 = time.time(); self.boot_kind = 'cold'; self.stop_ev.clear(); self.marks = {}; self._fm = None; self._lastseq = None
        self.wl_ready.clear()
        try: self.coding_blob = coding7.build_blob(self.env) if coding7.available() else None       # codificação alterada pelo usuário (None = a padrão do HMI)
        except Exception as e: self.coding_blob = None; print('codificação do iDrive 7:', e)
        self.step = 'Iniciando o renderizador'; self.pct = 2
        threading.Thread(target=self._boot_thread, daemon=True).start()
    def _mark(self, name): self.marks[name] = round(time.time() - self.t0, 1)
    # ---------- snapshot (boot rápido): estado da VM (savevm do QEMU, dentro do qcow2 de escrita) + o fluxo GL gravado (o glhost7 o reexecuta no Mac) ----------
    def snap_capable(self):
        return has_shm(find_qemu()) and bool(qemu_img()) and not os.environ.get('IDEMU_NO_SNAPSHOT')
    def snap_stamps(self):
        import hashlib, json
        q = find_qemu(); st = os.stat(q)
        return {'image': guest_stamp(), 'qemu': [int(st.st_mtime), st.st_size], 'role': self.role, 'proto': 1,
                'coding': hashlib.sha1(json.dumps((self.env.get('coding') or {}).get('extra') or {}, sort_keys=True).encode()).hexdigest()}
    def snap_valid(self):
        import json
        try:
            if not (self.snap_capable() and self.env.get('fast_boot', True)): return False
            for f in ('disk.qcow2', 'gl.rec', 'meta.json'):
                if not os.path.isfile(os.path.join(self.snap_dir, f)): return False
            return json.load(open(os.path.join(self.snap_dir, 'meta.json'))) == self.snap_stamps()
        except Exception: return False
    def snapshot_info(self):
        try: size = sum(os.path.getsize(os.path.join(self.snap_dir, f)) for f in os.listdir(self.snap_dir))
        except OSError: size = 0
        return {'valid': self.snap_valid(), 'size': size, 'enabled': bool(self.env.get('fast_boot', True)), 'state': self.snap_state}
    def drop_snapshot(self): shutil.rmtree(self.snap_dir, ignore_errors=True)
    def hmp(self, cmd, timeout=60.0):
        """Comando do monitor do QEMU (HMP) pelo socket unix; devolve o texto até o próximo prompt."""
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(timeout)
        try:
            s.connect(self.mon_path); buf = b''
            while not buf.endswith(b'(qemu) '):
                d = s.recv(4096)
                if not d: raise OSError('monitor do QEMU fechou')      # antes: laço infinito a 100% de CPU
                buf += d
            s.sendall((cmd + '\n').encode()); buf = b''; end = time.time() + timeout
            while not buf.endswith(b'(qemu) '):
                if time.time() >= end: raise OSError('monitor do QEMU não respondeu a "%s"' % cmd)
                d = s.recv(65536)
                if not d: raise OSError('monitor do QEMU fechou durante "%s"' % cmd)   # QEMU parado no meio de um savevm: não pode virar snapshot "válido"
                buf += d
            return buf.decode('latin1', 'replace').replace('\r', '')
        finally: s.close()
    def _ring_idle(self):
        """O host consumiu todo o fluxo publicado e espera uma mensagem nova (ponto seguro para o snapshot)? Lê o cabeçalho do anel (proto.h)."""
        import ctypes, mmap
        lib = ctypes.CDLL(None, use_errno=True); fd = lib.shm_open(self.shm.encode(), os.O_RDWR, 0o600)
        if fd < 0: return False
        try:
            m = mmap.mmap(fd, 4096)
            try:
                magic, epoch, g_start, idle = struct.unpack_from('<IIQI', m, 0); g_tail = struct.unpack_from('<Q', m, 56)[0]; g_head = struct.unpack_from('<Q', m, 120)[0]       # offsetof(shm_hdr, g_tail / g_head)
                return magic == 0x49444d47 and idle == 1 and g_tail == g_head
            finally: m.close()
        finally: os.close(fd)
    def _take_snapshot(self):
        import json, signal
        tmp = self.snap_dir + '.tmp'
        try:
            self.snap_state = 'saving'; shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
            if self.role == 'hu':          # o relógio e os serviços do carro vêm do idemu-fakesvc; um snapshot sem ele congelaria o relógio do HMI em todo boot rápido (visto em 2026-11-09)
                alive = self.run_guest('ps | grep -c "[i]demu-fakesvc"', 15).strip().split('\n')[-1].strip()
                if alive != '1': raise RuntimeError('o idemu-fakesvc não está rodando no guest (snapshot adiado para o próximo boot)')
            ok = False
            for _ in range(60):
                self.hmp('stop')
                if self._ring_idle(): ok = True; break
                self.hmp('cont'); time.sleep(0.5)
            if not ok: raise RuntimeError('o canal gráfico não ficou ocioso')
            os.kill(self.gl.pid, signal.SIGUSR1); done = os.path.join(self.run, 'gl.rec.done')
            for _ in range(100):
                if os.path.exists(done): break
                time.sleep(0.1)
            else: raise RuntimeError('o glhost7 não encerrou a gravação')
            out = self.hmp('savevm ' + SNAP_TAG, 600)
            if 'rror' in out or 'annot' in out: raise RuntimeError(out.strip()[-200:])
            if self.stop_ev.is_set() or self.q is None or self.q.poll() is not None: raise RuntimeError('ambiente parado durante a gravação')
            if SNAP_TAG not in self.hmp('info snapshots', 30): raise RuntimeError('o QEMU não registrou o snapshot')
            clone_file(self.overlay, os.path.join(tmp, 'disk.qcow2')); os.replace(os.path.join(self.run, 'gl.rec'), os.path.join(tmp, 'gl.rec'))
            json.dump(self.snap_stamps(), open(os.path.join(tmp, 'meta.json'), 'w'))
            shutil.rmtree(self.snap_dir, ignore_errors=True); os.replace(tmp, self.snap_dir); self.snap_state = 'ok'
            print('iDrive 7: snapshot salvo em %.1f s do boot' % (time.time() - self.t0))
        except Exception as e:
            self.snap_state = 'erro: %s' % e; shutil.rmtree(tmp, ignore_errors=True); print('iDrive 7: snapshot não salvo:', e)
            self._stop_recording()
        finally:
            try: self.hmp('cont')
            except Exception: pass
    def _stop_recording(self):
        """Sem snapshot, a gravação do fluxo GL (texturas inclusive) não pode seguir crescendo pela sessão inteira."""
        import signal
        try:
            if self.gl is not None and self.gl.poll() is None: os.kill(self.gl.pid, signal.SIGUSR1)
        except OSError: pass
        for _ in range(50):
            if os.path.exists(os.path.join(self.run, 'gl.rec.done')): break
            time.sleep(0.1)
        try: os.unlink(os.path.join(self.run, 'gl.rec'))
        except OSError: pass
    def _snapshot_when_settled(self):
        """Depois do primeiro boot, com a tela parada há alguns segundos, grava o snapshot (a VM fica pausada por alguns segundos)."""
        t_run = None; last = self.frame_seq(); t_chg = time.time()
        while not self.stop_ev.is_set() and self.state in ('booting', 'running'):
            time.sleep(0.5); q = self.frame_seq()
            if q != last: last = q; t_chg = time.time()
            if self.state == 'running':
                if t_run is None: t_run = time.time()
                if time.time() - t_run >= 15 and (time.time() - t_chg >= 4 or time.time() - t_run >= 120): self._take_snapshot(); return   # tela sempre animada: tenta assim mesmo (o anel ocioso é o que garante o ponto seguro)
    def _fix_guest_clock(self):
        self.guest('date -s "%s" >/dev/null' % time.strftime('%Y-%m-%d %H:%M:%S'))
    def _boot_thread(self):
        try:
            gsock = os.path.join(self.run, 'gl.sock'); csock = os.path.join(self.run, 'con.sock'); isock = os.path.join(self.run, 'inp.sock')
            hl = open(os.path.join(self.logd, 'renderer.log'), 'wb')
            qemu = find_qemu(); self.shm = ('/idemu-gl-%d-%d' % (os.getpid(), int(time.time()) % 100000)) if has_shm(qemu) else None
            if self.shm: shm_unlink(self.shm)
            capable = self.snap_capable() and bool(self.env.get('fast_boot', True)); restore = capable and not self._cold and self.snap_valid(); self._restored = restore
            self.overlay = os.path.join(self.run, 'disk.qcow2') if capable else None
            if capable:
                if restore: clone_file(os.path.join(self.snap_dir, 'disk.qcow2'), self.overlay)
                else:
                    try: os.unlink(self.overlay)
                    except OSError: pass
                    r = subprocess.run([qemu_img(), 'create', '-q', '-f', 'qcow2', '-b', OUT + '/root.img', '-F', 'raw', self.overlay], capture_output=True, text=True)
                    if r.returncode: raise RuntimeError('qemu-img: ' + (r.stderr or r.stdout)[-200:])
            genv = dict(os.environ)
            if os.environ.get('IDEMU_PROF'): genv['GLHOST7_PROF'] = '1'
            if capable and not restore: genv['GLHOST7_REC'] = os.path.join(self.run, 'gl.rec')            # o fluxo do boot, para o snapshot
            glcmd = [glhost_path(), ('shm:' + self.shm) if self.shm else gsock, self.run] + (['--replay', os.path.join(self.snap_dir, 'gl.rec')] if restore else [])
            port = 20000 + os.getpid() % 20000
            disk = ['-drive', 'if=none,id=sd0,file=%s,format=qcow2,cache=writeback' % self.overlay] if capable else ['-drive', 'if=none,id=sd0,file=%s/root.img,format=raw,snapshot=on' % OUT]
            cmd = [qemu] + (['-L', QEMU_SHARE] if self.shm else []) + ['-M', 'q35', '-cpu', 'Skylake-Client', '-accel', 'tcg,thread=multi', '-smp', '4', '-m', '3G', '-kernel', OUT + '/bzImage',
                   '-append', 'console=ttyS2,115200 root=/dev/mmcblk0 rootfstype=ext4 rw rootwait loglevel=4 nokaslr sdhci_pci.power_default_on=1 init=/idemu-init' + (' idemu.role=hu' if self.role == 'hu' else '') + (' idemu.coding=1' if self.coding_blob else ''),
                   '-device', 'sdhci-pci'] + disk + ['-device', 'sd-card,drive=sd0',
                   '-display', 'none', '-nic', 'none', '-rtc', 'base=localtime',            # o relógio do guest mostra a hora do Mac
                   '-chardev', 'socket,id=inp,path=%s,server=on,wait=off' % isock, '-serial', 'chardev:inp',        # ttyS0: entrada (toque), lida pelo idemu-wl
                   '-chardev', 'socket,id=gl,path=%s,server=on,wait=off' % gsock, '-serial', 'chardev:gl',
                   '-chardev', 'socket,id=con,path=%s,server=on,wait=off' % csock, '-serial', 'chardev:con',
                   '-monitor', 'unix:%s,server,nowait' % self.mon_path, '-S'] + (['-gdb', 'tcp:127.0.0.1:%d' % port] if not restore else ['-loadvm', SNAP_TAG]) + (['-device', 'idemu-shm,shm-name=%s,size=%d' % (self.shm, SHM_BYTES)] if self.shm else [])
            ql = open(os.path.join(self.logd, 'qemu.log'), 'wb')
            if restore:
                self.step = 'Restaurando o estado salvo'; self.pct = 10
                self._spawn('q', cmd, stdout=ql, stderr=subprocess.STDOUT)
                for _ in range(1200):                                          # o monitor só responde depois do -loadvm
                    if self.q.poll() is not None: raise RuntimeError('o QEMU terminou (%s) ao restaurar; veja logs/qemu.log' % self.q.returncode)
                    try:
                        if 'paused' in self.hmp('info status', 5): break
                    except OSError: pass
                    time.sleep(0.1)
                self._spawn('gl', glcmd, stdout=hl, stderr=hl, env=genv); ready = os.path.join(self.run, 'gl.ready')
                for _ in range(1200):
                    if os.path.exists(ready): break
                    if self.gl.poll() is not None: raise RuntimeError('o renderizador terminou (%s) ao reproduzir o fluxo; veja logs/renderer.log' % self.gl.returncode)
                    time.sleep(0.1)
                threading.Thread(target=self._console_thread, args=(csock,), daemon=True).start()
                threading.Thread(target=self._input_thread, args=(isock,), daemon=True).start()
                self.pct = 60; self.step = 'Retomando o sistema'
                self.hmp('cont'); self._fix_guest_clock_later = True
                threading.Thread(target=lambda: (time.sleep(1.5), self._fix_guest_clock()), daemon=True).start()
            else:
                self._spawn('gl', glcmd, stdout=hl, stderr=hl, env=genv)
                self._spawn('q', cmd, stdout=ql, stderr=subprocess.STDOUT)       # parado (-S) até o tscfix liberar
                tl = open(os.path.join(self.logd, 'tscfix.log'), 'wb')
                self._spawn('tscfix', [sys.executable, '-I', TOOLS + '/tscfix.py', str(port)], stdout=tl, stderr=subprocess.STDOUT)
                threading.Thread(target=self._console_thread, args=(csock,), daemon=True).start()
                threading.Thread(target=self._input_thread, args=(isock,), daemon=True).start()
                self.step = 'Iniciando o sistema do carro'; self.pct = 5
            end = time.time() + 1800; snap_started = False
            while not self.stop_ev.is_set():
                if self.q.poll() is not None: raise RuntimeError('o QEMU terminou (%s); veja logs/qemu.log' % self.q.returncode)
                if self.gl.poll() is not None: raise RuntimeError('o renderizador terminou (%s); veja logs/renderer.log' % self.gl.returncode)
                if self.state == 'booting':
                    el = time.time() - self.t0
                    self.pct = min(95, 5 + int(el * 90 / BOOT_ESTIMATE))
                    if self.frame_seq() >= 1:                       # o primeiro quadro já é o menu (o segundo só vem com o próximo tique do relógio)
                        self._mark('running'); self.state = 'running'; self.pct = 100; self.step = ''
                        if restore: self.boot_kind = 'fast'
                    elif time.time() > end: raise RuntimeError('o HMI não desenhou em 30 minutos; veja logs/console.log')
                else: self.frame_seq()
                if capable and not restore and not snap_started and self.state == 'running':
                    snap_started = True     # já existe um snapshot válido (boot completo pedido): só encerra a gravação do fluxo GL, que cresceria pela sessão inteira
                    threading.Thread(target=self._stop_recording if self.snap_valid() else self._snapshot_when_settled, daemon=True).start()
                time.sleep(0.25)
        except runtime.BootStopped: pass
        except Exception as e:
            if self.stop_ev.is_set(): return
            if getattr(self, '_restored', False) and self.state == 'booting' and not getattr(self, '_retried', False):   # snapshot ruim: apaga e faz o boot completo, como o iDrive 5/6
                print('iDrive 7: boot rápido falhou (%s); fazendo boot completo' % e)
                self._retried = True; self._kill_children(); self.drop_snapshot(); self._cold = True; self.boot_kind = 'cold'
                return self._boot_thread()
            self.err = str(e); self.state = 'error'; self._kill_children()
    STEPS = {'vsomeipd': 'Iniciando os serviços SOME/IP', 'codingshm': 'Carregando a codificação', 'persod': 'Iniciando a persistência', 'ioclc': 'Emulando o controlador de E/S',
             'udpnm': 'Acordando a rede do carro', 'nsm': 'Iniciando o gerenciador de estados', 'nsc': 'Iniciando o controlador de partida', 'wl': 'Iniciando o compositor Wayland',
             'hmi': 'Iniciando o HMI do iDrive 7 (leva alguns minutos)'}
    def _console_thread(self, path):
        """Liga ao console serial (ttyS2): grava logs/console.log e acompanha as etapas do init ('== start X')."""
        s = None
        for _ in range(600):
            if self.stop_ev.is_set(): return
            try: s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.connect(path); break
            except OSError: s.close(); s = None; time.sleep(0.1)
        if s is None: return
        self._con = s; log = open(os.path.join(self.logd, 'console.log'), 'wb'); tail = b''
        if self.mux is None:                      # o shell do guest (ttyS2) também fica em shell.sock e no SSH
            self.mux = runtime.ConsoleMux(os.path.join(self.run, 'shell.sock'), self._con_write); self.mux.start(); self._start_ssh(); self._start_sim()
        try:
            while not self.stop_ev.is_set():
                d = s.recv(4096)
                if not d: break
                log.write(d); log.flush(); tail = (tail + d)[-400:]
                if self.mux: self.mux.feed(d)
                for m in re.finditer(rb'== start (\w+)', tail):
                    if self.state == 'booting': self.step = self.STEPS.get(m.group(1).decode(), self.step)
                if b'== wl ready' in tail: self.wl_ready.set()
        except OSError: pass
        finally: log.close()
    def _input_thread(self, path):
        """Liga ao socket da serial de entrada (ttyS0 do guest); só escreve nele (o guest não manda nada de volta)."""
        for _ in range(600):
            if self.stop_ev.is_set(): return
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try: s.connect(path); break
            except OSError: s.close(); time.sleep(0.1)
        else: return
        with self._inp_lock: self._inp = s
        if self.coding_blob:                         # a codificação vai pela mesma serial do toque, quando o compositor do guest já a lê (o init espera por ela antes de iniciar o HMI)
            while not self.stop_ev.is_set() and not self.wl_ready.wait(0.5): pass
            if not self.stop_ev.is_set():
                for line in coding7.serial_lines(self.coding_blob): self.send_cmd(line)
        try:
            while not self.stop_ev.is_set():
                if not s.recv(4096): break
        except OSError: pass
    def send_cmd(self, line):
        """Uma linha para o compositor do guest (idemu-wl): "d X Y", "m X Y" ou "u"."""
        with self._inp_lock:
            if self._inp is None: return
            try: self._inp.sendall((line + '\n').encode())
            except OSError: self._inp = None
    def _con_write(self, d):
        with self._con_lock:
            if self._con: self._con.sendall(d)
    def guest(self, cmd):
        """Comando no shell do guest (depuração); a saída vai para logs/console.log."""
        with self._con_lock:
            if self._con: self._con.sendall((cmd + '\n').encode())
    def run_guest(self, cmd, timeout=20.0):
        """Roda `cmd` no shell do guest e devolve a saída (depuração): lê o que o console.log ganha até o marcador de fim."""
        import random
        mark = 'IDEMU_END_%d' % random.randint(0, 10 ** 9); path = os.path.join(self.logd, 'console.log')
        try: start = os.path.getsize(path)
        except OSError: start = 0
        self.guest('(%s) 2>&1; echo %s' % (cmd, mark))
        t_end = time.time() + timeout
        while time.time() < t_end:
            time.sleep(0.4)
            try:
                with open(path, 'rb') as f: f.seek(start); d = f.read().decode('latin1')
            except OSError: continue
            i = d.find('\n' + mark)
            if i >= 0 or d.count(mark) >= 2:
                j = d.rfind(mark); d = d[:j]
                k = d.find('echo ' + mark); d = d[d.find('\n', k) + 1:] if k >= 0 else d
                return d.replace('\r', '').strip('\n')
        return d.replace('\r', '') if 'd' in dir() else ''
    def _kill_children(self):
        if self._con is not None:
            try: self._con.close()
            except OSError: pass
            self._con = None
        for p in (self.tscfix,):
            try:
                if p: p.kill()
            except Exception: pass
        self.tscfix = None
        runtime.Runtime._kill_children(self)
        if self.shm: shm_unlink(self.shm); self.shm = None
    def status(self):
        s = runtime.Runtime.status(self); s['kind'] = self.kind; s['disp'] = list(self.disp); s['hmi_exits'] = 0; s['role'] = self.role
        return s
    # ---------- quadro: o glhost7 grava <w, h, seq> (3 inteiros) + RGBA a partir do byte 64 ----------
    def _hdr(self, m): return struct.unpack_from('<iii', m, 0)
    def _busy(self, m): return struct.unpack_from('<i', m, 12)[0]      # quadro em escrita (glhost7 novo); 0 nos binários antigos
    def frame_seq(self):
        m = self._map()
        if not m or len(m) < 64: return 0
        w, h, seq = self._hdr(m)
        if seq != self._lastseq:
            now = time.time()
            if self._lastseq is not None and seq > self._lastseq: self.fps_t.extend([now] * min(seq - self._lastseq, 60))
            self._lastseq = seq
        return seq
    def _rgb(self, m, w, h):
        raw = bytes(m[64:64 + w * h * 4]); out = bytearray(w * h * 3)
        out[0::3] = raw[0::4]; out[1::3] = raw[1::4]; out[2::3] = raw[2::4]
        return bytes(out)
    def frame_bytes(self):
        m = self._map()
        if not m or len(m) < 64: return None
        for _ in range(6):
            w, h, seq = self._hdr(m); b = self._busy(m)
            if not seq or w <= 0 or h <= 0 or len(m) < 64 + w * h * 4: return None
            if b and b != seq: time.sleep(0.002); continue          # o glhost7 está escrevendo este quadro
            rgb = self._rgb(m, w, h)
            if self._hdr(m)[2] == seq and self._busy(m) == b: break
        return seq, w, h, rgb
    def frame_rgba(self):
        """O quadro como o glhost7 o grava (RGBA, topo primeiro): o navegador o usa direto, sem converter para RGB e de volta."""
        m = self._map()
        if not m or len(m) < 64: return None
        for _ in range(6):
            w, h, seq = self._hdr(m); b = self._busy(m)
            if not seq or w <= 0 or h <= 0 or len(m) < 64 + w * h * 4: return None
            if b and b != seq: time.sleep(0.002); continue          # o glhost7 está escrevendo este quadro
            raw = bytes(m[64:64 + w * h * 4])
            if self._hdr(m)[2] == seq and self._busy(m) == b: break  # nada começou a ser escrito durante a cópia (quadro inteiro)
        return seq, w, h, raw
    def screen_png(self):
        seq0 = self.frame_seq()
        if seq0 and self._png[0] == seq0: return self._png[1], seq0          # o celular pede a cada 50 ms: não reconverte um quadro que não mudou
        fr = self.frame_bytes()
        if not fr: return None, 0
        seq, w, h, raw = fr
        if self._png[0] == seq: return self._png[1], seq
        rows = b''.join(b'\0' + raw[y * w * 3:(y + 1) * w * 3] for y in range(h))
        def ch(t, d): c = struct.pack('>I', len(d)) + t + d; return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
        png = b'\x89PNG\r\n\x1a\n' + ch(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + ch(b'IDAT', zlib.compress(rows, 1)) + ch(b'IEND', b'')
        self._png = (seq, png)
        return png, seq
    # ---------- entrada: toque vira ponteiro Wayland no idemu-wl (o RAMSES só trata ponteiro) ----------
    def touch(self, x, y, down, move=False):
        w, h = self.disp; x = max(0, min(w - 1, int(x))); y = max(0, min(h - 1, int(y)))
        if move: self.send_cmd('m %d %d' % (x, y)); return
        if down: self._t_down = time.time(); self.send_cmd('d %d %d' % (x, y)); return
        wait = self._t_down + 0.09 - time.time()          # um toque rápido demais o HMI pode ignorar
        if wait > 0: time.sleep(wait)
        self.send_cmd('u')
    def key(self, code, val):
        """Teclas do controlador: viram teclas do Linux no wl_keyboard do idemu-wl ("k CÓDIGO 0|1"); códigos >= 1000 são crus (código - 1000), para testes."""
        lk = code - 1000 if code >= 1000 else KEYS.get(code)
        if lk: self.send_cmd('k %d %d' % (lk, 1 if val else 0))
    def rotor(self, delta):
        for _ in range(min(abs(int(delta)), 20)):
            k = KEY_ROTOR_RIGHT if delta > 0 else KEY_ROTOR_LEFT; self.key(k, 1); self.key(k, 0)
