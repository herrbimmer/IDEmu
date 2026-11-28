"""iDrive 8 (MGU22): monta a imagem a partir da PSdZData e roda QEMU `virt` + mguhost. Detalhes em docs/OUTRAS_GERACOES.md.

Windows nativo (ipc.IS_WIN): a RAM do guest é uma seção nomeada (mmap com tagname) aberta pelo QEMU (memory-backend-winshm, src/qemu/hostmem-winshm.c) e pelo
mguhost.exe; o console do guest é um chardev TCP em 127.0.0.1 (no lugar do FIFO no stdin do QEMU); a entrada vai ao mguhost por UDP em 127.0.0.1; o guest aarch64
roda em WHPX (só Windows on ARM) ou em TCG (emulação pura, bem mais lenta que o HVF do Mac)."""
try: import _posixshmem            # iDrive 8 (macOS): memória compartilhada POSIX; não existe no Windows
except ImportError: _posixshmem = None
import glob, json, mmap, os, platform, re, shutil, struct, subprocess, sys, tempfile, threading, time, uuid
from . import runtime, coding8, ipc, hostos

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, 'tools', 'mgu')
OUT = os.path.join(ROOT, 'mgu22')
# 12 GiB: o DTB (tools/mgu/virt_mgu22.dtb) fixa a memória em 0x40000000..0x340000000, o initramfs descomprimido em INITRD_AT (= base + 8 GiB) e os nós reservados em 0x1bff00000;
# mudar MB exigiria refazer o DTB (virt_mgu22.dts + dtc), então não há variável de ambiente para isso (nem no Windows).
MB = 12288
USBFAKE = ('libusb-1.0.so.0', 'libudev.so.1')
GUEST_BASE = 0x40000000; INITRD_AT = 0x240000000
SHM = '/idemu_ram'
GUEST_FILES = ('libcod.so.0', 'coding.tab', 'libEGL.so.1', 'libGLESv2.so.2', 'idemuwl', 'idemuinput', 'idemuusb', 'libusb-1.0.so.0', 'libudev.so.1', 'libidemuhmi.so')
BUILD_STEPS = [('kernel e raiz', 10, 'Lendo o kernel e o sistema'), ('IVI e EXT', 25, 'Lendo o contêiner IVI com o HMI'), ('cpio', 55, 'Preparando os arquivos'),
               ('dados da marca', 75, 'Lendo os dados da marca e do carro'), ('juntando', 90, 'Juntando a imagem')]
IS_WIN = ipc.IS_WIN
EXE = '.exe' if IS_WIN else ''
QEMU = os.environ.get('IDEMU_QEMU_AARCH64') or (os.path.join(runtime.BIN, 'qemu-system-aarch64.exe') if IS_WIN else 'qemu-system-aarch64')   # macOS/Linux: o do PATH, como sempre

def image_ready():
    return os.path.isfile(OUT + '/base.cpio') and os.path.isfile(OUT + '/Image') and all(os.path.isfile(f'{OUT}/guest/{f}') for f in GUEST_FILES)

def build(psdz=None, log=print, progress=lambda p, s: None):
    """Monta mgu22/ com tools/mgu/build_image.py. A imagem é compartilhada por todos os ambientes iDrive 8."""
    cmd = [sys.executable, '-u', TOOLS + '/build_image.py'] + ([psdz] if psdz else [])
    kw = {}
    if IS_WIN:       # o filho escreve em UTF-8 (acentos do log) e não abre janela de console
        kw = dict(encoding='utf-8', errors='replace', env=dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8'), creationflags=hostos.CREATE_NO_WINDOW)
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kw)
    tail = []
    for line in p.stdout:
        line = line.rstrip(); log(line); tail = (tail + [line])[-5:]
        for key, pct, step in BUILD_STEPS:
            if line.startswith(key): progress(pct, step)
    if p.wait() != 0: raise RuntimeError('falha ao montar a imagem do iDrive 8: ' + ' / '.join(tail)[-300:])

def _pe_machine(path):
    """Campo Machine do cabeçalho PE de uma DLL/EXE do Windows (0x8664 = x86-64, 0xAA64 = ARM64); None se não for PE."""
    try:
        with open(path, 'rb') as f:
            h = f.read(64)
            if h[:2] != b'MZ' or len(h) < 64: return None
            f.seek(struct.unpack_from('<I', h, 0x3c)[0]); s = f.read(6)
            if s[:4] != b'PE\0\0' or len(s) < 6: return None
            return struct.unpack_from('<H', s, 4)[0]
    except (OSError, struct.error): return None

def mguhost_path():
    """Renderizador do host: bin/mguhost.exe (Windows, build-windows.sh) ou mgu22/guest/mguhost (macOS, build.sh)."""
    if not IS_WIN: return OUT + '/guest/mguhost'
    for p in (os.path.join(runtime.BIN, 'mguhost.exe'), os.path.join(OUT, 'guest', 'mguhost.exe')):
        if os.path.isfile(p): return p
    raise RuntimeError('mguhost.exe não encontrado em bin/: compile com "bash src/mgu22/build-windows.sh host" no shell MSYS2 MINGW64')

def _angle_dirs_win():
    """Pastas candidatas a ter libEGL.dll + libGLESv2.dll (ANGLE) no Windows: bin/ do IDEmu, Edge, Chrome e apps Electron instalados por usuário."""
    out = [runtime.BIN, os.path.join(runtime.BIN, 'angle')]
    env = os.environ
    pfs = [env.get(k) for k in ('ProgramFiles(x86)', 'ProgramFiles', 'ProgramW6432')]
    la = env.get('LOCALAPPDATA')
    roots = []
    for pf in pfs:
        if pf: roots += [os.path.join(pf, 'Microsoft', 'Edge', 'Application'), os.path.join(pf, 'Google', 'Chrome', 'Application')]
    if la: roots += [os.path.join(la, 'Google', 'Chrome', 'Application'), os.path.join(la, 'Microsoft', 'Edge', 'Application')]
    seen = set()
    def vkey(d):
        n = os.path.basename(d)
        return tuple(int(x) for x in n.split('.')) if re.fullmatch(r'\d+(\.\d+)+', n) else None
    for r in roots:
        if r.lower() in seen: continue
        seen.add(r.lower())
        vers = [d for d in glob.glob(os.path.join(glob.escape(r), '*')) if os.path.isdir(d) and vkey(d)]
        out += sorted(vers, key=vkey, reverse=True)        # a versão mais nova primeiro
        out.append(r)
    if la: out += sorted(glob.glob(os.path.join(glob.escape(la), 'Programs', '*')))      # Electron (VS Code, Teams...): libEGL.dll fica na pasta do app
    return out

def find_angle():
    env = os.environ.get('IDEMU_ANGLE')
    if env: return env
    if IS_WIN:
        try: want = _pe_machine(mguhost_path()) or 0x8664        # o ANGLE tem de ter a mesma arquitetura do mguhost.exe (x86-64 no MinGW64)
        except RuntimeError: want = 0x8664
        tried = []
        for d in _angle_dirs_win():
            e, g = os.path.join(d, 'libEGL.dll'), os.path.join(d, 'libGLESv2.dll')
            if not (os.path.isfile(e) and os.path.isfile(g)): continue
            if _pe_machine(g) == want and _pe_machine(e) == want: return d
            tried.append(d)
        raise RuntimeError('ANGLE não encontrado: instale o Microsoft Edge ou o Google Chrome (de 64 bits), ou defina IDEMU_ANGLE com a pasta de libEGL.dll e libGLESv2.dll'
                           + (' (achei, mas de outra arquitetura: %s)' % ', '.join(tried) if tried else ''))
    pats = ['/Applications/*/Contents/Frameworks/Chromium Embedded Framework.framework/Versions/A/Libraries',
            '/Applications/*/Contents/Frameworks/*Framework.framework/Versions/*/Libraries', '/Applications/*/Contents/Frameworks']
    for pat in pats:
        for d in sorted(glob.glob(pat)):
            if os.path.exists(d + '/libGLESv2.dylib') and os.path.exists(d + '/libEGL.dylib'):
                arch = subprocess.run(['lipo', '-archs', d + '/libGLESv2.dylib'], capture_output=True, text=True).stdout
                if 'arm64' in arch: return d
    raise RuntimeError('ANGLE não encontrado: instale um app baseado em Chromium ou defina IDEMU_ANGLE com a pasta de libEGL.dylib e libGLESv2.dylib')

def _host_arm64():
    """O Windows é ARM64? (Python x64 emulado enxerga PROCESSOR_ARCHITEW6432.)"""
    a = (os.environ.get('PROCESSOR_ARCHITEW6432') or platform.machine() or '').lower()
    return a in ('arm64', 'aarch64')

def _qemu_accels():
    try:
        r = subprocess.run([QEMU, '-accel', 'help'], capture_output=True, text=True, timeout=15, creationflags=hostos.CREATE_NO_WINDOW if IS_WIN else 0)
        return (r.stdout or '') + (r.stderr or '')
    except Exception: return ''

def accel_args():
    """(argumentos de -accel/-cpu, aceleração real: 'hvf' | 'whpx' | 'tcg'). macOS: HVF. Windows: WHPX só se o host é ARM64 e o QEMU o tem; senão TCG (lento)."""
    if not IS_WIN: return ['-accel', 'hvf', '-cpu', 'host'], 'hvf'
    force = (os.environ.get('IDEMU_MGU_ACCEL') or '').lower()
    cpu = os.environ.get('IDEMU_MGU_CPU')
    if force == 'whpx' or (not force and _host_arm64() and 'whpx' in _qemu_accels()):
        return ['-accel', 'whpx', '-cpu', cpu or 'host'], 'whpx'
    # TCG: o guest é aarch64 e o host x86-64 (emulação por software, todos os 4 núcleos do guest em threads). cortex-a76 = o núcleo do SA8155 (Kryo 485)
    return ['-accel', 'tcg,thread=multi', '-cpu', cpu or 'cortex-a76'], 'tcg'

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

def _windows_ram(name, directory):
    """Cria uma seção nomeada com arquivo temporário como backing da RAM do guest."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    size = MB << 20
    free = shutil.disk_usage(directory).free
    if free < size:
        raise OSError('o iDrive 8 precisa de %s GiB livres para a RAM temporária em %s' % (MB >> 10, directory))
    mark_sparse = ctypes.WinDLL('kernel32', use_last_error=True).DeviceIoControl
    mark_sparse.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                            wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID)
    mark_sparse.restype = wintypes.BOOL
    fsctl_set_sparse = 0x000900C4
    storage = tempfile.TemporaryFile(prefix='idemu-ram-', suffix='.bin', dir=directory)
    try:
        handle = msvcrt.get_osfhandle(storage.fileno())
        mark_sparse(handle, fsctl_set_sparse, None, 0, None, 0, ctypes.byref(wintypes.DWORD()), None)
        mapping = mmap.mmap(storage.fileno(), size, tagname=name)
    except BaseException:
        storage.close()
        raise
    # Keep storage open until both child processes exit. Closing a delete-on-close
    # file while the guest still uses its section can lose nonresident pages.
    return mapping, storage


def _prepare_ram(dtb_out, coding_tab=None):
    """Carrega o initramfs e grava o DTB. No Windows devolve (mmap, nome da seção, arquivo de backing)."""
    with open(TOOLS + '/guest_boot.sh', 'rb') as f: boot = f.read()
    if IS_WIN: boot = boot.replace(b'\r\n', b'\n')      # checkout com CRLF quebraria o "#!/bin/sh" do guest
    items = [('idemu', 0o40755, b''), ('idemu.sh', 0o100755, boot)]
    for f in GUEST_FILES:
        if f in USBFAKE: continue
        items.append(('idemu/' + f, 0o100755, coding_tab.encode() if f == 'coding.tab' and coding_tab else open(f'{OUT}/guest/{f}', 'rb').read()))   # coding.tab do ambiente (idemu/coding8.py)
    items.append(('idemu/usbfake', 0o40755, b''))   # libusb e libudev falsas, só para o devicemanager
    for f in USBFAKE: items.append(('idemu/usbfake/' + f, 0o100755, open(f'{OUT}/guest/{f}', 'rb').read()))
    name = None
    storage = None
    if IS_WIN:
        # nome único por partida: uma seção antiga ainda aberta por um QEMU em encerramento não pode ser reaproveitada (traria canais velhos)
        name = 'idemu_ram_' + uuid.uuid4().hex
        try:
            m, storage = _windows_ram(name, os.path.dirname(dtb_out))
        except OSError as e:
            raise RuntimeError('não consegui mapear a RAM temporária do iDrive 8: %s' % e) from e
    else:
        try: _posixshmem.shm_unlink(SHM)
        except OSError: pass
        fd = _posixshmem.shm_open(SHM, os.O_CREAT | os.O_RDWR | os.O_EXCL, 0o600)
        os.ftruncate(fd, MB << 20)
        m = mmap.mmap(fd, MB << 20, mmap.MAP_SHARED)
    pos = INITRD_AT - GUEST_BASE
    try:
        with open(TOOLS + '/virt_mgu22.dtb', 'rb') as f:
            d = f.read()
        ph = struct.pack('>II', 0xdeadbeef, 0xfeedf00d)
        ov = _cpio(items)
        image = OUT + '/base.cpio'
        end = GUEST_BASE + ((pos + os.path.getsize(image) + 3) & ~3) + len(ov)
        if end > GUEST_BASE + (MB << 20) or ph not in d:
            raise RuntimeError('initramfs não cabe na RAM do guest')
        with open(image, 'rb') as f:
            while True:
                b = f.read(1 << 24)
                if not b: break
                m[pos:pos + len(b)] = b; pos += len(b)
        pos = (pos + 3) & ~3
        m[pos:pos + len(ov)] = ov
        end = GUEST_BASE + pos + len(ov)
        with open(dtb_out, 'wb') as f:
            f.write(d.replace(ph, struct.pack('>II', end >> 32, end & 0xffffffff)))
    except BaseException:
        m.close()
        if storage is not None:
            storage.close()
        else:
            os.close(fd)
            try: _posixshmem.shm_unlink(SHM)
            except OSError: pass
        raise
    if not IS_WIN: m.close(); os.close(fd)
    return (m, name, storage) if IS_WIN else None

class MguRuntime(runtime.Runtime):
    kind = 'mgu22'; disp = (2880, 960)
    def __init__(self, env_dir, env, debug=False):
        runtime.Runtime.__init__(self, env_dir, env)
        self.debug = debug; self.ctl = self.run; self.console_in = os.path.join(self.run, 'console.in'); self._keep = None; self._sock = None
        self._ram = None; self._ram_backing = None; self._ser = None; self._ser_lock = threading.Lock()
        self._render_dir = None
    def start(self, cold=False):
        if not image_ready(): raise RuntimeError('imagem do iDrive 8 não montada')
        for d in (self.run, self.logd): os.makedirs(d, exist_ok=True)
        if IS_WIN:
            # Um leitor do servidor anterior pode manter o frame.rgb mapeado depois da parada.
            self._render_dir = tempfile.TemporaryDirectory(prefix='mgu-render-', dir=self.run, ignore_cleanup_errors=True)
            self.frame_path = os.path.join(self._render_dir.name, 'frame.rgb')
            stale = ('input.sock.port', 'shell.sock.port', 'console.sock.port')
        else:
            stale = ('frame.rgb', 'input.sock', 'console.in')
        for f in stale:
            try: os.unlink(os.path.join(self.run, f))
            except OSError: pass
        self._climate_set = False; self._t_clock = 0; self.state = 'booting'; self.err = None; self.t0 = time.time(); self.boot_kind = 'cold'; self.stop_ev.clear(); self.marks = {}; self._fm = None; self._lastseq = None; self._exits = (0, 0, b'')
        self._png = (None, None)
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
    def _ram_release(self, shm=None):
        """Solta a RAM compartilhada: macOS apaga o nome do objeto POSIX (a memória some junto com os dois processos); Windows fecha o mmap do Python (o QEMU e o
        mguhost já têm a seção aberta; se ainda não tinham, ela some aqui, que é o desejado ao parar)."""
        if IS_WIN:
            m, self._ram = self._ram, None
            if m is not None:
                try: m.close()
                except Exception: pass
            return
        try: _posixshmem.shm_unlink(SHM)
        except OSError: pass
    def _con_connect(self, addr, timeout=180):
        """Windows: liga ao console do guest (chardev TCP do QEMU, que espera o IDEmu conectar antes de iniciar o guest) e entrega a saída ao console.log e ao ConsoleMux."""
        end = time.time() + timeout; s = None
        while time.time() < end and not self.stop_ev.is_set():
            if self.q.poll() is not None: raise RuntimeError('o QEMU terminou (%s); veja logs/qemu.log' % self.q.returncode)
            try: s = ipc.connect_once(addr); break
            except OSError: time.sleep(0.2)
        if s is None:
            if self.stop_ev.is_set(): raise runtime.BootStopped()
            raise RuntimeError('não consegui ligar ao console do QEMU em %s; veja logs/qemu.log' % addr)
        with self._ser_lock: self._ser = s
        lf = open(os.path.join(self.logd, 'console.log'), 'wb')
        threading.Thread(target=self._pump_console, args=(s, lf), daemon=True).start()
    def _pump_console(self, s, lf):
        window = b''
        try:
            while not self.stop_ev.is_set():
                d = s.recv(4096)
                if not d: break
                lf.write(d); lf.flush()
                if self.mux: self.mux.feed(d)
                if b'Kernel panic - not syncing:' in window + d:
                    self._console_panic = True
                window = (window + d)[-32:]
        except (OSError, ValueError): pass
        finally:
            try: lf.close()
            except OSError: pass
    def _boot_thread(self):
        self._console_panic = False
        try:
            angle = find_angle()
            dtb = os.path.join(self.run, 'boot.dtb')
            try: tab = coding8.build_tab(self.env)       # codificação alterada pelo usuário (None = a de fábrica)
            except Exception as e: tab = None; print('codificação do iDrive 8:', e)
            self.coding_rows = len(tab.splitlines()) if tab else 0
            host = mguhost_path(); qargs, accel = accel_args()      # antes de gastar GBs de RAM: falta de mguhost.exe / QEMU aparece logo
            if IS_WIN and not os.path.isfile(QEMU): raise RuntimeError('qemu-system-aarch64.exe não encontrado em bin/: compile com "bash tools/qemu/build-aarch64-windows.sh" no shell MSYS2 MINGW64')
            ram = _prepare_ram(dtb, tab); self._mark('ram')
            shm = SHM
            if IS_WIN:
                with self._life:
                    if self.stop_ev.is_set():
                        mapping, _, storage = ram
                        mapping.close()
                        storage.close()
                        raise runtime.BootStopped()
                    self._ram, shm, self._ram_backing = ram
            self.step = 'Iniciando o renderizador'; self.pct = 10
            hl = open(os.path.join(self.logd, 'renderer.log'), 'wb')
            gkw = {}
            if IS_WIN:       # entrada por UDP em 127.0.0.1; no WHPX o QEMU não aparece no working set com as páginas que o guest usa: varredura completa
                gkw['env'] = dict(os.environ, MGUHOST_INPUT=ipc.addr(self.run, 'input.sock'), **({'MGUHOST_FULLSCAN': '1'} if accel == 'whpx' else {}))
            self._spawn('gl', [host, shm, str(MB), os.path.dirname(self.frame_path), angle], stdout=hl, stderr=hl, **gkw)
            time.sleep(0.5)
            args = 'console=ttyAMA0 loglevel=3 rdinit=/idemu.sh rootfstype=ramfs selinux=0 enforcing=0 panic=0 log_buf_len=2M' + (' idemu.debug' if self.debug else '') + (' idemu.dlt' if os.environ.get('IDEMU_MGU_DLT') else '') + (' idemu.usb' if os.environ.get('IDEMU_MGU_USB') else '') + ' idemu.time=%d' % time.time()
            if IS_WIN:
                args += ' initramfs_async=0'
                # console do guest: chardev TCP (QEMU escuta e espera o IDEmu; ver _con_connect). Mais robusto que o stdio do QEMU no Windows, que quer um console de verdade.
                con = ipc.addr(self.run, 'console.sock')
                cmd = [QEMU, '-M', 'virt,gic-version=3,memory-backend=m0'] + qargs + ['-m', str(MB), '-smp', '4', '-nodefaults', '-display', 'none', '-monitor', 'none',
                       '-chardev', 'socket,id=con0,host=%s,port=%d,server=on,wait=on' % (ipc.LOOPBACK, ipc.port_of(con)), '-serial', 'chardev:con0',
                       '-object', f'memory-backend-winshm,id=m0,size={MB}M,shm-name={shm}', '-dtb', dtb, '-kernel', OUT + '/Image', '-append', args]
                ql = open(os.path.join(self.logd, 'qemu.log'), 'wb')
                self._spawn('q', cmd, stdin=subprocess.DEVNULL, stdout=ql, stderr=subprocess.STDOUT)
                self.mux = runtime.ConsoleMux(ipc.addr(self.run, 'shell.sock'), self._con_write); self.mux.start()
                self._con_connect(con)
            else:
                os.mkfifo(self.console_in); self._keep = os.open(self.console_in, os.O_RDWR)
                ser = os.path.join(self.logd, 'console.log'); sl = open(ser, 'wb')
                cmd = [QEMU, '-M', 'virt,gic-version=3,memory-backend=m0'] + qargs + ['-m', str(MB), '-smp', '4', '-nographic', '-serial', 'mon:stdio',
                       '-object', f'memory-backend-shm,id=m0,size={MB}M', '-dtb', dtb, '-kernel', OUT + '/Image', '-append', args]
                env = dict(os.environ, DYLD_INSERT_LIBRARIES=OUT + '/guest/qemushm.dylib', IDEMU_SHM_NAME=SHM)
                self._spawn('q', cmd, stdin=self._keep, stdout=sl, stderr=subprocess.STDOUT, env=env)
                # shell do guest (ttyAMA0): a entrada é o FIFO que o QEMU lê, a saída é o console.log; o ConsoleMux os expõe em shell.sock e no SSH
                self.mux = runtime.ConsoleMux(ipc.addr(self.run, 'shell.sock'), self._con_write); self.mux.start()
                threading.Thread(target=self._tail_console, args=(ser,), daemon=True).start()
            self.step = 'Iniciando o sistema do carro'; self.pct = 15
            slow = accel == 'tcg'                   # TCG: dezenas de vezes mais lento que HVF/WHPX; o prazo e a barra de progresso acompanham
            end = time.time() + (3600 if slow else 300); unlinked = False
            # o nome do shm sai quando o primeiro quadro prova que QEMU e mguhost já o abriram (antes: 2 s fixos, e um QEMU lento não achava o objeto)
            while not self.stop_ev.is_set():
                if self.q.poll() is not None: raise RuntimeError('o QEMU terminou (%s); veja logs/%s' % (self.q.returncode, 'qemu.log' if IS_WIN else 'console.log'))
                if self.gl.poll() is not None: raise RuntimeError('o renderizador terminou (%s); veja logs/renderer.log' % self.gl.returncode)
                if self._console_panic: raise RuntimeError('o kernel do iDrive 8 parou; veja logs/console.log')
                if not unlinked and self.frame_seq() >= 1:
                    unlinked = True
                    self._ram_release()
                if self.state == 'booting':
                    el = time.time() - self.t0
                    self.pct = min(95, 15 + int(el * (0.12 if slow else 1.6))); self.step = 'Iniciando o HMI do iDrive 8' + (' (emulação TCG: pode levar vários minutos)' if slow else '')
                    if self.frame_seq() >= 2:
                        self._mark('running'); self.state = 'running'; self.pct = 100; self.step = ''
                        self._start_ssh()
                        self._start_sim()
                    elif time.time() > end: raise RuntimeError('o HMI não desenhou em %d minutos; veja logs/console.log' % (60 if slow else 5))
                else:
                    self.frame_seq(); self._car_state()
                time.sleep(0.25)
        except Exception as e:
            if not self.stop_ev.is_set(): self.err = str(e); self.state = 'error'; self._kill_children()
            else:                                  # parado durante o preparo: _prepare_ram pode ter criado o shm depois do _kill_children (GBs de RAM presos)
                self._ram_release()
                self._ram_backing_close()
    def _ram_backing_close(self):
        backing, self._ram_backing = self._ram_backing, None
        if backing is not None:
            backing.close()
    def _kill_children(self):
        runtime.Runtime._kill_children(self)
        with self._cmd_lock:
            sock, self._sock = self._sock, None
            if sock is not None:
                sock.close()
        render_dir, self._render_dir = self._render_dir, None
        if render_dir is not None:
            render_dir.cleanup()
        if self._keep is not None:
            try: os.close(self._keep)
            except OSError: pass
            self._keep = None
        with self._ser_lock: s, self._ser = self._ser, None
        if s is not None: ipc.shutdown_close(s)
        self._ram_release()
        self._ram_backing_close()
    def status(self):
        s = runtime.Runtime.status(self); s['kind'] = self.kind; s['disp'] = list(self.disp); s['hmi_exits'] = self.hmi_exits()
        return s
    def snapshot_info(self): return {'valid': False, 'size': 0, 'enabled': False}
    def drop_snapshot(self): pass
    # ---------- entrada ----------
    def send_cmd(self, line):
        with self._cmd_lock:
            if self._sock is None:
                self._sock = ipc.dgram_socket()       # macOS/Linux: AF_UNIX DGRAM; Windows: UDP em 127.0.0.1
            try: ipc.dgram_send(self._sock, ipc.addr(self.run, 'input.sock'), line.encode())
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
        if IS_WIN:                                 # Windows: o console é o socket do chardev TCP do QEMU
            with self._ser_lock: s = self._ser
            if s is not None:
                try: s.sendall(d)
                except OSError: pass
            return
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
        if IS_WIN: self._con_write((cmd + '\n').encode()); return
        with open(self.console_in, 'w') as f: f.write(cmd + '\n')
