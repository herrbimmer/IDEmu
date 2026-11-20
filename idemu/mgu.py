"""iDrive 8 (MGU22): monta a imagem a partir da PSdZData e roda QEMU `virt` + mguhost. Detalhes em docs/OUTRAS_GERACOES.md."""
import _posixshmem, glob, json, mmap, os, shutil, struct, subprocess, sys, threading, time
from . import runtime, coding8

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, 'tools', 'mgu')
OUT = os.path.join(ROOT, 'mgu22')
MB = 12288
USBFAKE = ('libusb-1.0.so.0', 'libudev.so.1')
GUEST_BASE = 0x40000000; INITRD_AT = 0x240000000
SHM = '/idemu_ram'
GUEST_FILES = ('libcod.so.0', 'coding.tab', 'libEGL.so.1', 'libGLESv2.so.2', 'idemuwl', 'idemuinput', 'idemuusb', 'libusb-1.0.so.0', 'libudev.so.1', 'libidemuhmi.so')
BUILD_STEPS = [('kernel e raiz', 10, 'Lendo o kernel e o sistema'), ('IVI e EXT', 25, 'Lendo o contêiner IVI com o HMI'), ('cpio', 55, 'Preparando os arquivos'),
               ('dados da marca', 75, 'Lendo os dados da marca e do carro'), ('juntando', 90, 'Juntando a imagem')]

def image_ready():
    return os.path.isfile(OUT + '/base.cpio') and os.path.isfile(OUT + '/Image') and all(os.path.isfile(f'{OUT}/guest/{f}') for f in GUEST_FILES)

def build(psdz=None, log=print, progress=lambda p, s: None):
    """Monta mgu22/ com tools/mgu/build_image.py. A imagem é compartilhada por todos os ambientes iDrive 8."""
    cmd = [sys.executable, '-u', TOOLS + '/build_image.py'] + ([psdz] if psdz else [])
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail = []
    for line in p.stdout:
        line = line.rstrip(); log(line); tail = (tail + [line])[-5:]
        for key, pct, step in BUILD_STEPS:
            if line.startswith(key): progress(pct, step)
    if p.wait() != 0: raise RuntimeError('falha ao montar a imagem do iDrive 8: ' + ' / '.join(tail)[-300:])

def find_angle():
    env = os.environ.get('IDEMU_ANGLE')
    if env: return env
    pats = ['/Applications/*/Contents/Frameworks/Chromium Embedded Framework.framework/Versions/A/Libraries',
            '/Applications/*/Contents/Frameworks/*Framework.framework/Versions/*/Libraries', '/Applications/*/Contents/Frameworks']
    for pat in pats:
        for d in sorted(glob.glob(pat)):
            if os.path.exists(d + '/libGLESv2.dylib') and os.path.exists(d + '/libEGL.dylib'):
                arch = subprocess.run(['lipo', '-archs', d + '/libGLESv2.dylib'], capture_output=True, text=True).stdout
                if 'arm64' in arch: return d
    raise RuntimeError('ANGLE não encontrado: instale um app baseado em Chromium ou defina IDEMU_ANGLE com a pasta de libEGL.dylib e libGLESv2.dylib')

def _cpio(items):
    out = bytearray()
    def ent(name, mode, data, ino):
        nm = name.encode() + b'\0'
        h = '070701' + ''.join('%08X' % v for v in (ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(nm), 0))
        b = h.encode() + nm; b += b'\0' * ((4 - len(b) % 4) % 4)
        out.extend(b); out.extend(data); out.extend(b'\0' * ((4 - len(data) % 4) % 4))
    for i, (n, m, d) in enumerate(items, 1): ent(n, m, d, i)
    ent('TRAILER!!!', 0, b'', len(items) + 1)
    return bytes(out)

def _prepare_ram(dtb_out, coding_tab=None):
    """Cria a RAM do guest (objeto POSIX compartilhado) já com o initramfs dentro e grava a árvore de dispositivos."""
    items = [('idemu', 0o40755, b''), ('idemu.sh', 0o100755, open(TOOLS + '/guest_boot.sh', 'rb').read())]
    for f in GUEST_FILES:
        if f in USBFAKE: continue
        items.append(('idemu/' + f, 0o100755, coding_tab.encode() if f == 'coding.tab' and coding_tab else open(f'{OUT}/guest/{f}', 'rb').read()))   # coding.tab do ambiente (idemu/coding8.py)
    items.append(('idemu/usbfake', 0o40755, b''))   # libusb e libudev falsas, só para o devicemanager
    for f in USBFAKE: items.append(('idemu/usbfake/' + f, 0o100755, open(f'{OUT}/guest/{f}', 'rb').read()))
    try: _posixshmem.shm_unlink(SHM)
    except OSError: pass
    fd = _posixshmem.shm_open(SHM, os.O_CREAT | os.O_RDWR | os.O_EXCL, 0o600)
    os.ftruncate(fd, MB << 20)
    m = mmap.mmap(fd, MB << 20, mmap.MAP_SHARED); pos = INITRD_AT - GUEST_BASE
    with open(OUT + '/base.cpio', 'rb') as f:
        while True:
            b = f.read(1 << 24)
            if not b: break
            m[pos:pos + len(b)] = b; pos += len(b)
    pos = (pos + 3) & ~3
    ov = _cpio(items); m[pos:pos + len(ov)] = ov; pos += len(ov)
    m.close(); os.close(fd)
    d = open(TOOLS + '/virt_mgu22.dtb', 'rb').read()
    end = GUEST_BASE + pos
    ph = struct.pack('>II', 0xdeadbeef, 0xfeedf00d)
    if end > GUEST_BASE + (MB << 20) or ph not in d: raise RuntimeError('initramfs não cabe na RAM do guest')
    open(dtb_out, 'wb').write(d.replace(ph, struct.pack('>II', end >> 32, end & 0xffffffff)))

class MguRuntime(runtime.Runtime):
    kind = 'mgu22'; disp = (2880, 960)
    def __init__(self, env_dir, env, debug=False):
        runtime.Runtime.__init__(self, env_dir, env)
        self.debug = debug; self.ctl = self.run; self.console_in = os.path.join(self.run, 'console.in'); self._keep = None; self._sock = None
    def start(self, cold=False):
        if not image_ready(): raise RuntimeError('imagem do iDrive 8 não montada')
        for d in (self.run, self.logd): os.makedirs(d, exist_ok=True)
        for f in ('frame.rgb', 'input.sock', 'console.in'):
            try: os.unlink(os.path.join(self.run, f))
            except OSError: pass
        self._climate_set = False; self._t_clock = 0; self.state = 'booting'; self.err = None; self.t0 = time.time(); self.boot_kind = 'cold'; self.stop_ev.clear(); self.marks = {}; self._fm = None; self._lastseq = None
        self.step = 'Preparando a memória do sistema'; self.pct = 5
        threading.Thread(target=self._boot_thread, daemon=True).start()
    def _car_state(self):
        """Relógio e clima viriam de outras centrais: manda a hora do Mac e a temperatura inicial."""
        now = time.time()
        if now - getattr(self, '_t_clock', 0) >= 15:
            self._t_clock = now; t = time.localtime(now)
            self.send_cmd('T %d %d %d %d %d %d' % (t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_wday))
        if not getattr(self, '_climate_set', False):
            self._climate_set = True; self.send_cmd('c 215 215 1')
    def hmi_exits(self):
        """Quantas vezes o HMI caiu nesta execução (o guest o reinicia sozinho)."""
        try:                                   # lê só o que o console.log ganhou desde a última consulta (o status é pedido 4 vezes por segundo)
            p = os.path.join(self.logd, 'console.log'); off, n, tail = getattr(self, '_exits', (0, 0, b''))
            if os.path.getsize(p) < off: off, n, tail = 0, 0, b''
            with open(p, 'rb') as f: f.seek(off); d = tail + f.read(); off = f.tell()
            n += d.count(b'IDEMU-HMI-EXIT'); self._exits = (off, n, d[-13:])     # 13 = len(marcador) - 1: guarda um marcador partido ao meio, nunca um inteiro (seria contado de novo)
            return n
        except OSError: return 0
    def _mark(self, name): self.marks[name] = round(time.time() - self.t0, 1)
    def _boot_thread(self):
        try:
            angle = find_angle()
            dtb = os.path.join(self.run, 'boot.dtb')
            try: tab = coding8.build_tab(self.env)       # codificação alterada pelo usuário (None = a de fábrica)
            except Exception as e: tab = None; print('codificação do iDrive 8:', e)
            self.coding_rows = len(tab.splitlines()) if tab else 0
            _prepare_ram(dtb, tab); self._mark('ram')
            self.step = 'Iniciando o renderizador'; self.pct = 10
            hl = open(os.path.join(self.logd, 'renderer.log'), 'wb')
            self._spawn('gl', [OUT + '/guest/mguhost', SHM, str(MB), self.run, angle], stdout=hl, stderr=hl)
            time.sleep(0.5)
            os.mkfifo(self.console_in); self._keep = os.open(self.console_in, os.O_RDWR)
            ser = os.path.join(self.logd, 'console.log'); sl = open(ser, 'wb')
            args = 'console=ttyAMA0 loglevel=3 rdinit=/idemu.sh rootfstype=ramfs selinux=0 enforcing=0 panic=0 log_buf_len=2M' + (' idemu.debug' if self.debug else '') + (' idemu.dlt' if os.environ.get('IDEMU_MGU_DLT') else '') + (' idemu.usb' if os.environ.get('IDEMU_MGU_USB') else '') + ' idemu.time=%d' % time.time()
            cmd = ['qemu-system-aarch64', '-M', 'virt,gic-version=3,memory-backend=m0', '-accel', 'hvf', '-cpu', 'host', '-m', str(MB), '-smp', '4', '-nographic', '-serial', 'mon:stdio',
                   '-object', f'memory-backend-shm,id=m0,size={MB}M', '-dtb', dtb, '-kernel', OUT + '/Image', '-append', args]
            env = dict(os.environ, DYLD_INSERT_LIBRARIES=OUT + '/guest/qemushm.dylib', IDEMU_SHM_NAME=SHM)
            self._spawn('q', cmd, stdin=self._keep, stdout=sl, stderr=subprocess.STDOUT, env=env)
            # shell do guest (ttyAMA0): a entrada é o FIFO que o QEMU lê, a saída é o console.log; o ConsoleMux os expõe em shell.sock e no SSH
            self.mux = runtime.ConsoleMux(os.path.join(self.run, 'shell.sock'), self._con_write); self.mux.start()
            threading.Thread(target=self._tail_console, args=(ser,), daemon=True).start()
            self.step = 'Iniciando o sistema do carro'; self.pct = 15
            end = time.time() + 300; unlinked = False
            # o nome do shm sai quando o primeiro quadro prova que QEMU e mguhost já o abriram (antes: 2 s fixos, e um QEMU lento não achava o objeto)
            while not self.stop_ev.is_set():
                if self.q.poll() is not None: raise RuntimeError('o QEMU terminou (%s); veja logs/console.log' % self.q.returncode)
                if self.gl.poll() is not None: raise RuntimeError('o renderizador terminou (%s); veja logs/renderer.log' % self.gl.returncode)
                if not unlinked and self.frame_seq() >= 1:
                    unlinked = True
                    try: _posixshmem.shm_unlink(SHM)       # a memória some junto com os dois processos
                    except OSError: pass
                if self.state == 'booting':
                    el = time.time() - self.t0
                    self.pct = min(95, 15 + int(el * 1.6)); self.step = 'Iniciando o HMI do iDrive 8'
                    if self.frame_seq() >= 2:
                        self._mark('running'); self.state = 'running'; self.pct = 100; self.step = ''
                        self._start_ssh()
                        self._start_sim()
                    elif time.time() > end: raise RuntimeError('o HMI não desenhou em 5 minutos; veja logs/console.log')
                else:
                    self.frame_seq(); self._car_state()
                time.sleep(0.25)
        except Exception as e:
            if not self.stop_ev.is_set(): self.err = str(e); self.state = 'error'; self._kill_children()
            else:                                  # parado durante o preparo: _prepare_ram pode ter criado o shm depois do _kill_children (GBs de RAM presos)
                try: _posixshmem.shm_unlink(SHM)
                except OSError: pass
    def _kill_children(self):
        runtime.Runtime._kill_children(self)
        if self._keep is not None:
            try: os.close(self._keep)
            except OSError: pass
            self._keep = None
        try: _posixshmem.shm_unlink(SHM)
        except OSError: pass
    def status(self):
        s = runtime.Runtime.status(self); s['kind'] = self.kind; s['disp'] = list(self.disp); s['hmi_exits'] = self.hmi_exits()
        return s
    def snapshot_info(self): return {'valid': False, 'size': 0, 'enabled': False}
    def drop_snapshot(self): pass
    # ---------- entrada ----------
    def send_cmd(self, line):
        with self._cmd_lock:
            if self._sock is None:
                import socket
                self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try: self._sock.sendto(line.encode(), os.path.join(self.run, 'input.sock'))
            except OSError as e: print('iDrive 8: entrada não entregue (%s)' % e)   # mguhost reiniciando ou fila cheia: não derruba a VM em execução
    def key(self, code, val): self.send_cmd('k %d %d 0 1' % (code, 1 if val else 0))
    def rotor(self, delta):
        if delta: self.send_cmd('r %d' % delta)
    def touch(self, x, y, down, move=False):
        if move: self.send_cmd('m %d %d' % (x, y)); return
        if down: self._t_down = time.time(); self.send_cmd('d %d %d' % (x, y)); return
        wait = getattr(self, '_t_down', 0) + 0.09 - time.time()   # um toque rápido demais o HMI ignora
        if wait > 0: time.sleep(wait)
        self.send_cmd('u')

    def _con_write(self, d):
        if self._keep is not None:
            try: os.write(self._keep, d)
            except OSError: pass
    def _tail_console(self, path):
        """Entrega ao ConsoleMux o que o QEMU grava em console.log (a partir do início desta execução)."""
        try:
            with open(path, 'rb') as f:
                while not self.stop_ev.is_set():
                    d = f.read(4096)
                    if d:
                        if self.mux: self.mux.feed(d)
                    else: time.sleep(0.1)
        except OSError: pass

    def guest(self, cmd):
        """Comando no console do guest (depuração); a saída vai para logs/console.log."""
        with open(self.console_in, 'w') as f: f.write(cmd + '\n')
