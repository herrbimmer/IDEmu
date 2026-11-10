"""CIC (High, Harman "BMW L6", SH7785 + QNX 6.3.2) no IDEmu.

A imagem (IFS de boot com os patches, flash NOR de 128 MB com IFS2 e EFS_RO) é montada uma vez em <IDEmu>/cic a partir do pacote
swfl_000003a6 (e do 417) e é compartilhada entre os ambientes. O QEMU (placa `cic`, bin/qemu-system-sh4) grava a tela composta em
frame.rgb (CIC_FRAME) e recebe rotor/teclas por um socket (CIC_INPUT). Detalhes em docs/CIC.md.
"""
import collections, glob, hashlib, importlib.util, json, os, shutil, socket, subprocess, threading, time
from . import runtime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'cic')
QEMU = os.path.join(ROOT, 'bin', 'qemu-system-sh4')
DEV_QEMU = os.path.expanduser('~/id4-qemu/build/qemu-system-sh4')     # compilado por src/cic/build.sh
VERSION = '008_090_002'
PKGS = ('000003a6', '00000417')
IMAGES = ('ifs.bin', 'flash.img', 'efs.ifs', 'build.json')

# Idioma do HMI: no carro ele vem do lado do veículo (pelo MOST; o Root registra "processVehicleLogDevEvent: Language is %i")
# e chega ao HmiMain como a propriedade MOST HumanMachineInterface.CurrentLanguage (FBlock 0x10, instância 1, FktID 0x200),
# que o próprio HmiMain serve. No emulador ninguém a envia e o HMI fica em alemão; o IDEmu manda um Set com o idioma do
# ambiente (coding.language).
# Códigos medidos na 008_090_002 (Set de 0 a 90): os demais o HMI recusa (status 0x42) e mantém o idioma atual.
LANGUAGES = {'de_DE': 1, 'en_GB': 2, 'es_ES': 4, 'it_IT': 5, 'fr_FR': 6, 'nl_NL': 8, 'ru_RU': 14, 'pt_PT': 17,
             'pl_PL': 18, 'el_GR': 19, 'tr_TR': 20, 'sv_SE': 23}
LANGUAGE_FALLBACK = {'en_US': 'en_GB', 'pt_BR': 'pt_PT'}   # 3 (inglês EUA) não está no banco de textos da ECE


def language_code(lang):
    """coding.language (ex.: 'en_GB') -> código do CurrentLanguage; idioma que o CIC não tem -> inglês (o padrão do HMI)."""
    lang = LANGUAGE_FALLBACK.get(lang, lang)
    return LANGUAGES.get(lang, LANGUAGES['en_GB'])


def _cicrun():
    """tools/cic/run.py como módulo (montagem das imagens e linha de comando do QEMU)."""
    spec = importlib.util.spec_from_file_location('cicrun', os.path.join(ROOT, 'tools', 'cic', 'run.py'))
    m = importlib.util.module_from_spec(spec)
    import sys
    sys.path.insert(0, os.path.join(ROOT, 'tools', 'cic'))
    spec.loader.exec_module(m)
    return m


def find_pkg(psdz=None):
    """Caminho do swfl_000003a6 (o 417 tem de estar na mesma pasta): PSdZData configurada ou ~/Downloads/System files/ID4."""
    dirs = []
    if psdz:
        dirs += [os.path.join(psdz, 'swe', 'swfl'), os.path.join(psdz, 'psdzdata', 'swe', 'swfl'), psdz]
    dirs += [os.path.expanduser('~/Downloads/System files/ID4')]
    for d in dirs:
        ok = all(os.path.isfile(os.path.join(d, 'swfl_%s.bin.%s' % (p, VERSION))) for p in PKGS)
        if ok:
            return os.path.join(d, 'swfl_%s.bin.%s' % (PKGS[0], VERSION))
    return None


def image_ready():
    return all(os.path.isfile(os.path.join(OUT, n)) for n in IMAGES) and os.path.isfile(QEMU)


def _stamp():
    """Hash do que entra no IFS além do pacote (roteiro de boot, patches do HMI e do controlador): mudou -> o ifs.bin é refeito."""
    h = hashlib.sha1()
    for n in ('run.py', 'bootinfo.py', 'hmiinput.py'):
        try:
            with open(os.path.join(ROOT, 'tools', 'cic', n), 'rb') as f: h.update(f.read())
        except OSError: pass
    return h.hexdigest()[:16]


def image_stale():
    try:
        with open(os.path.join(OUT, 'build.json')) as f: b = json.load(f)
    except (OSError, ValueError):
        return False
    return b.get('stamp') != _stamp() and _pkg_of(b) is not None


def _pkg_of(b):
    """Pacote que montou a imagem; se a pasta dele sumiu (PSdZData movida), o mesmo pacote em ~/Downloads/System files/ID4."""
    p = b.get('pkg')
    if p and os.path.isfile(p): return p
    return find_pkg(None)


def rebuild_ifs(log=print):
    """Refaz só o IFS de boot (segundos) a partir do pacote que montou a imagem; a flash e o EFS_RO ficam."""
    with open(os.path.join(OUT, 'build.json')) as f: b = json.load(f)
    old = os.environ.get('CIC_NOECURESET'); os.environ['CIC_NOECURESET'] = '1'
    try:
        _cicrun().prepare(OUT, _pkg_of(b), log=log)
    finally:
        if old is None: os.environ.pop('CIC_NOECURESET', None)
        else: os.environ['CIC_NOECURESET'] = old
    b['pkg'] = _pkg_of(b); b['stamp'] = _stamp(); b['built'] = time.time()
    with open(os.path.join(OUT, 'build.json'), 'w') as f: json.dump(b, f)


EFS_ADDR = 0x4d80000          # EFS_RO na flash NOR (tools/cic/run.py)
USERFILES = 'userfiles'       # <ambiente>/userfiles/ -> /mnt/EFS_RO/ no guest


def userfiles_dir(env_dir):
    return os.path.join(env_dir, USERFILES)


def userfiles_list(env_dir):
    """Arquivos do ambiente que vão para /mnt/EFS_RO: [{path, size}] (a pasta é criada vazia se não existir)."""
    d = userfiles_dir(env_dir); out = []
    for root, dirs, files in os.walk(d):
        dirs[:] = sorted(x for x in dirs if not x.startswith('.'))
        for n in sorted(files):
            if n.startswith('.'): continue
            p = os.path.join(root, n)
            try: size = os.path.getsize(p)
            except OSError: continue
            out.append({'path': os.path.relpath(p, d).replace(os.sep, '/'), 'size': size})
    return out


def apply_userfiles(flash, env_dir, log=lambda m: None):
    """Põe os arquivos do usuário no EFS_RO da flash desta execução: refaz o imagefs (pacote + arquivos, sem as imagens de veículo que não
    couberem) e o grava em 0x4d80000 da cópia da flash (a imagem compartilhada em cic/ não muda). Devolve o número de arquivos."""
    d = userfiles_dir(env_dir)
    if not userfiles_list(env_dir): return 0
    with open(os.path.join(OUT, 'build.json')) as f: b = json.load(f)
    sys_path = os.path.join(ROOT, 'tools', 'cic')
    import sys
    if sys_path not in sys.path: sys.path.insert(0, sys_path)
    import efs, mkimagefs
    extra = efs.dir_entries(d)
    img = mkimagefs.build(efs.entries(_pkg_of(b), extra=extra, log=log))
    if len(img) > efs.LIMIT: raise RuntimeError('o EFS_RO com os arquivos do usuário (%d bytes) não cabe na flash livre (%d)' % (len(img), efs.LIMIT))
    old = os.path.getsize(os.path.join(OUT, 'efs.ifs'))
    with open(flash, 'r+b') as f:
        f.seek(EFS_ADDR); f.write(img)
        if len(img) < old: f.write(b'\xff' * (old - len(img)))
    return sum(1 for e in extra if e[1] != 'D')


def build(psdz=None, log=print, progress=lambda p, s: None):
    pkg = find_pkg(psdz)
    if not pkg:
        raise RuntimeError('pacotes do CIC não encontrados (swfl_000003a6 e swfl_00000417 versão %s) na PSdZData nem em '
                           '~/Downloads/System files/ID4' % VERSION)
    os.makedirs(OUT, exist_ok=True)
    if os.path.isfile(DEV_QEMU) and (not os.path.isfile(QEMU) or os.path.getmtime(DEV_QEMU) > os.path.getmtime(QEMU)):
        shutil.copy2(DEV_QEMU, QEMU)
        log('QEMU atualizado a partir de %s' % DEV_QEMU)
    if not os.path.isfile(QEMU):
        raise RuntimeError('bin/qemu-system-sh4 não existe: rode src/cic/build.sh')
    progress(5, 'Lendo o pacote %s' % os.path.basename(pkg))
    old = {k: os.environ.get(k) for k in ('CIC_NOECURESET',)}
    os.environ['CIC_NOECURESET'] = '1'           # se o Root pedir reset ele segue vivo (o HMI não some da tela)
    steps = {'EFS_RO (FFS3 original + conteúdo do HD)': (10, 'Montando o EFS_RO (dados do HMI)'), 'IFS de boot': (70, 'Montando o IFS de boot'),
             'flash NOR de 128 MB': (85, 'Gravando a flash NOR')}
    def lg(s):
        log(s)
        if s in steps: progress(*steps[s])
    try:
        _cicrun().prepare(OUT, pkg, log=lg)
    finally:
        for k, v in old.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
    json.dump({'pkg': pkg, 'version': VERSION, 'built': time.time(), 'stamp': _stamp()}, open(os.path.join(OUT, 'build.json'), 'w'))
    progress(100, 'Pronto')


# marcos do boot no slog (ser0) -> (porcentagem, texto)
MARKS = [('Starting CicHighEceUsaRoot', 10, 'Iniciando o aplicativo principal (Root)'),
         ('Starting CicHighEceUsaSecond', 25, 'Montando o IFS2 e iniciando os serviços'),
         ('PApplicationWrapper::HMIApps', 45, 'Iniciando o HMI'),
         ('MtpHmi::Registration complete', 65, 'Carregando a interface'),
         ('PHMIWrapper::HMIReady', 90, 'Interface pronta')]


class CicRuntime(runtime.Runtime):
    kind = 'cic'; disp = (1280, 480)

    def __init__(self, env_dir, env):
        runtime.Runtime.__init__(self, env_dir, env)
        self.ctl = self.run; self._sock = None; self.zbe = None; self.vehicle = {}

    def snapshot_info(self): return {'valid': False, 'size': 0, 'enabled': False}
    def drop_snapshot(self): pass

    def start(self, cold=False):
        if self.state in ('booting', 'running'): return
        if os.path.isfile(DEV_QEMU) and (not os.path.isfile(QEMU) or os.path.getmtime(DEV_QEMU) > os.path.getmtime(QEMU)):
            shutil.copy2(DEV_QEMU, QEMU)               # QEMU recompilado por src/cic/build.sh
        if not image_ready(): raise RuntimeError('imagem do CIC não montada: compile o ambiente')
        if image_stale():
            self.con.append('[idemu] atualizando o IFS de boot do CIC (roteiro de boot novo)')
            rebuild_ifs(log=lambda m: self.con.append('[idemu] ' + str(m)))
        import sys
        sys.path.insert(0, os.path.join(ROOT, 'tools', 'cic'))
        import hmiinput
        hmiinput.patch_flash_file(os.path.join(OUT, 'flash.img'))      # entrada do controlador (imagens montadas antes dela)
        if self.zbe: self.zbe.close(); self.zbe = None
        shutil.rmtree(self.run, ignore_errors=True); os.makedirs(self.run); os.makedirs(self.logd, exist_ok=True)
        # flash gravável desta execução (clone APFS, instantâneo): o snapshot=on gravava num qcow2 temporário e às vezes travava o QEMU
        # numa gravação da flash (vCPU parado em blk_pwrite)
        fl = os.path.join(self.run, 'flash.img')
        if subprocess.call(['cp', '-c', os.path.join(OUT, 'flash.img'), fl], stderr=subprocess.DEVNULL) != 0:
            shutil.copyfile(os.path.join(OUT, 'flash.img'), fl)
        try:
            n = apply_userfiles(fl, self.env_dir, log=lambda m: self.con.append('[idemu] ' + m))
            if n: self.con.append('[idemu] %d arquivo(s) do usuário em /mnt/EFS_RO (%s)' % (n, userfiles_dir(self.env_dir)))
        except Exception as e:
            self.con.append('[idemu] arquivos do usuário ignorados: %s' % e)
        self.state = 'booting'; self.err = None; self.t0 = time.time(); self.marks = {}; self.step = 'Iniciando o QEMU'; self.pct = 2
        self._fm = None; self._lastseq = None; self.fps_t = collections.deque(maxlen=400); self.boot_kind = 'cold'; self.stop_ev.clear()
        threading.Thread(target=self._boot_thread, daemon=True).start()

    def _links(self):
        for name, target in (('console.log', 'ser1.log'), ('qemu.log', 'qemu.out'), ('renderer.log', 'ser0.txt')):
            p = os.path.join(self.logd, name)
            try:
                if os.path.lexists(p): os.unlink(p)
                os.symlink(os.path.join(self.run, target), p)
            except OSError:
                pass

    def _boot_thread(self):
        try:
            cmd = _cicrun().qemu_cmd(OUT, run=self.run, qemu=QEMU, debug_log='', flash=os.path.join(self.run, 'flash.img'))
            env = dict(os.environ, CIC_FRAME=self.frame_path, CIC_NORESET='1', CIC_INPUT=os.path.join(self.run, 'input.sock'),
                       CIC_OUTPUT=os.path.join(self.run, 'output.sock'))
            self.zbe = VirtualZBE(self.run, self.send_cmd, log=self._most_log)
            self.zbe.language = language_code((self.env.get('coding') or {}).get('language', 'de_DE'))
            env.pop('CIC_DISPLAY', None)
            out = open(os.path.join(self.run, 'qemu.out'), 'wb')
            self._spawn('q', cmd, stdout=out, stderr=subprocess.STDOUT, env=env)
            self._links()
            self._start_gps()
            # console QNX (ksh na SCIF1) para o SSH e o shell.sock; o ShellMux espera o QEMU criar o socket
            self.mux = runtime.ShellMux(os.path.join(self.run, 'ser1.sock'), os.path.join(self.run, 'shell.sock')); self.mux.start()
            slog = os.path.join(self.run, 'ser0.txt'); seen = set(); end = time.time() + 420
            while not self.stop_ev.is_set():
                if self.q.poll() is not None: raise RuntimeError('o QEMU terminou (%s); veja o log do QEMU' % self.q.returncode)
                if self.state == 'booting':
                    txt = b''
                    for fn in (slog, os.path.join(self.run, 'ser1.log')):
                        try:
                            with open(fn, 'rb') as f: txt += f.read()
                        except OSError:
                            pass
                    for key, pct, step in MARKS:
                        if key not in seen and key.encode() in txt:
                            seen.add(key); self.pct = pct; self.step = step; self._mark(key.split('::')[-1])
                    if 'PHMIWrapper::HMIReady' in seen and self.frame_seq() > 0:
                        self.state = 'running'; self.pct = 100; self.step = ''; self._mark('running')
                        self.zbe.register()                 # anuncia o controlador ao HMI (FBlock 0xE5)
                        if 'battery_voltage' in self.vehicle: self.set_vehicle('battery_voltage', self.vehicle['battery_voltage'])
                        self._start_ssh()
                    elif time.time() > end:
                        raise RuntimeError('o HMI não ficou pronto em 7 minutos; veja os logs')
                    elif not seen:
                        self.step = 'Iniciando o QNX'; self.pct = min(9, 2 + int(time.time() - self.t0))
                else:
                    self.frame_seq()
                time.sleep(0.25)
        except Exception as e:
            if not self.stop_ev.is_set():
                self.err = str(e); self.state = 'error'; self._kill_children()

    def _start_gps(self):
        """Simulador de GPS do IDEmu (aba GPS, porta TCP NMEA) -> receptor ANTARIS virtual na SCIF0 (/dev/ser2), de onde o vdev-flexgps do HMI lê."""
        from . import gps, antaris
        self._gps_tx = None; self.antaris = None
        if os.environ.get('IDEMU_CIC_NOGPS'): return           # depuração: quem liga à ser0.sock é um script externo
        self.gps = gps.GpsSim(tcp_port=self.env.get('net', {}).get('gps_port'))
        try: self._gpslog = open(os.path.join(self.logd, 'gps.log'), 'a')
        except OSError: self._gpslog = None
        def log(m):
            if self._gpslog:
                try: self._gpslog.write('%.1f %s\n' % (time.time() - self.t0, m)); self._gpslog.flush()
                except (OSError, ValueError): pass
        self.antaris = antaris.Antaris(self.gps, self._gps_send, log=log)
        self.gps.on_nmea(lambda ln: self.antaris.polled and self._gps_send(ln))      # NMEA só depois que o driver identificou o módulo (MON-VER)
        self.gps.start()
        threading.Thread(target=self._gps_connect, daemon=True).start()

    def _most_log(self, m):
        try:
            with open(os.path.join(self.logd, 'most.log'), 'a') as f: f.write('%.1f %s\n' % (time.time() - self.t0, m))
        except OSError: pass

    def _gps_connect(self):
        try: s = runtime._unix_connect(os.path.join(self.run, 'ser0.sock'), 60)
        except Exception: return
        if self.stop_ev.is_set(): s.close(); return
        self._gps_tx = s; self.antaris.start()
        try:
            while not self.stop_ev.is_set():
                d = s.recv(4096)
                if not d: break
                self.antaris.feed(d)
        except OSError: pass

    def _gps_send(self, line):
        s = getattr(self, '_gps_tx', None)
        if s is None: return
        try: s.sendall(line if isinstance(line, bytes) else line.encode())
        except OSError: self._gps_tx = None

    def _kill_children(self):
        runtime.Runtime._kill_children(self)
        a = getattr(self, 'antaris', None)
        if a: a.stop()
        f = getattr(self, '_gpslog', None); self._gpslog = None
        if f:
            try: f.close()
            except OSError: pass
        s = getattr(self, '_gps_tx', None); self._gps_tx = None
        if s is not None:
            try: s.close()
            except OSError: pass
        if self.zbe: self.zbe.close(); self.zbe = None         # socket output.sock e thread rx: o servidor cria um CicRuntime novo a cada partida
        if self._sock is not None:
            try: self._sock.close()
            except OSError: pass
            self._sock = None
    def status(self):
        s = runtime.Runtime.status(self); s['kind'] = self.kind; s['disp'] = list(self.disp)
        return s

    # ---------- entrada: controlador iDrive virtual ----------
    def send_cmd(self, line):
        with self._cmd_lock:
            if self._sock is None:
                self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                self._sock.sendto(line.encode(), os.path.join(self.run, 'input.sock'))
            except OSError:
                pass

    # ---------- veículo virtual (docs/CIC.md, "Dados do veículo") ----------
    VEHICLE = {'battery_voltage': ('V', 6.0, 16.0)}          # sinal -> (unidade, mínimo, máximo); só o que foi verificado no guest

    def vehicle_state(self):
        return {'signals': dict(self.vehicle), 'supported': {k: {'unit': u, 'min': lo, 'max': hi} for k, (u, lo, hi) in self.VEHICLE.items()}}

    def set_vehicle(self, name, value):
        """battery_voltage: tensão da bateria em V, no byte 5 do status da IOC (canal 2), em décimos de volt; o QEMU a publica a cada 250 ms."""
        if name not in self.VEHICLE: raise ValueError('sinal desconhecido: %s' % name)
        u, lo, hi = self.VEHICLE[name]; v = float(value)
        if not lo <= v <= hi: raise ValueError('%s fora de %g..%g %s' % (name, lo, hi, u))
        self.vehicle[name] = round(v, 1)
        if name == 'battery_voltage': self.send_cmd('v %d' % round(v * 10))

    def most_send(self, hexstr):
        """Telegrama MTP/MOST cru para o HMI (como o controlador virtual faz): [0..1] tamanho, [2]=2, [4..5] origem, [6] FBlock, [7] instância,
        [8..9] FktID, [10] OpType, [11]=1, dados. O tamanho (bytes 0..1) é preenchido se vier 0000."""
        b = bytes.fromhex(''.join(hexstr.split()))
        if len(b) < 12: raise ValueError('telegrama curto demais (mínimo 12 bytes)')
        if b[:2] == b'\0\0': b = bytes([len(b) >> 8, len(b) & 0xff]) + b[2:]
        self.send_cmd('t ' + b.hex())

    def most_seen(self):
        """O que o HMI pediu a outros FBlocks: [{fblock, inst, subscribes:[FktID], telegrams:[{fkt, op, n, last}]}]."""
        z = self.zbe
        if not z: return []
        out = {}
        for (fb, inst), fk in z.subs.items(): out[(fb, inst)] = {'fblock': fb, 'inst': inst, 'subscribes': sorted(fk), 'telegrams': []}
        for (fb, inst, fkt, op), (n, last) in sorted(z.seen.items()):
            e = out.setdefault((fb, inst), {'fblock': fb, 'inst': inst, 'subscribes': [], 'telegrams': []})
            e['telegrams'].append({'fkt': fkt, 'op': VirtualZBE.OPS.get(op, op), 'n': n, 'last': last})
        return [out[k] for k in sorted(out)]

    def key(self, code, val):
        if self.zbe: self.zbe.key(int(code), bool(val))
    def rotor(self, delta):
        if delta and self.zbe: self.zbe.rotate(int(delta))
    def touch(self, x, y, down, move=False):
        pass                                       # o CIC não tem tela de toque


class VirtualZBE:
    """Controlador iDrive (ZBE) virtual: fala com o HMI como o FBlock MOST CentralControlSystem (0xE5, instância 1 = ZGW_01).

    Os telegramas MTP vão para o QEMU (input.sock, "t <hex>") e o patch do HmiMain (tools/cic/hmiinput.py) os entrega como se viessem do
    Root; o que o HMI manda ao 0xE5 volta pelo output.sock ("x <hex>"). Formato do telegrama MOST: [0..1] tamanho, [2]=2, [3]=0, [4..5]
    endereço de origem, [6] FBlock, [7] instância, [8..9] FktID, [10] OpType (0x0C = Status), [11]=1, dados. Funções (docs/CIC.md):
      0xC10 RotaryEncoder        01 1D cnt pos_hi pos_lo 1E 00   (pos = posição absoluta; o HMI gira pela diferença)
      0xC20 PushButton           01 1D cnt estado dir campo bits (estado 1 = apertado, 0 = solto)
                                   campo 0x1E + bits 1 = aperto do controlador; campo 0x1D + dir (1 cima, 2 direita, 4 baixo, 8 esquerda) = inclinação;
                                   campo 0 + bits = teclas (1 MENU, 2 BACK, 4 OPTION, 8 RADIO, 16 CD, 32 NAV, 64 TEL)
      0xC30 RotaryEncoderConfig  01 1D nn 00 (resposta ao Set do HMI, nn = o contador que ele mandou; só então o rotor é aceito)
    cnt é o contador de mensagens do controlador (o HMI ignora repetição), comum a rotor e botões.
    Quando o HMI configura o controlador (os proxies dele já estão no ar), manda também o idioma (language, ver LANGUAGES)."""
    REGISTRY = '000c0701000100000102e501'          # registry changed: FBlock E5.01 no endereço 0x0102 (ZGW)
    # códigos de tecla do app -> (campo, dir, bits)
    KEYS = {1: (0, 0, 1), 2: (0, 0, 2), 3: (0, 0, 4), 4: (0, 0, 16), 5: (0, 0, 8), 6: (0, 0, 64), 7: (0, 0, 32), 8: (0x1e, 0, 1),
            9: (0x1d, 1, 0), 10: (0x1d, 4, 0), 11: (0x1d, 8, 0), 12: (0x1d, 2, 0)}

    def __init__(self, run_dir, send, log=lambda s: None):
        self.send_cmd = send; self.log = log; self.cnt = 0; self.pos = 0x1000; self.lock = threading.Lock()
        self.out = os.path.join(run_dir, 'output.sock'); self.registered = False; self.configured = False; self.seen = {}; self.subs = {}
        self.language = None                       # código do CurrentLanguage enviado quando o HMI configura o controlador
        try: os.unlink(self.out)
        except OSError: pass
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM); self.sock.bind(self.out); self.sock.settimeout(0.5)
        self.stop = threading.Event()
        threading.Thread(target=self._rx, daemon=True).start()

    def close(self):
        self.stop.set()
        try: self.sock.close()
        except OSError: pass

    def _tel(self, fkt, data, fblock=0xe5, op=0x0c):
        b = bytes([0, 12 + len(data), 2, 0, 0x01, 0x02, fblock, 0x01, fkt >> 8, fkt & 0xff, op, 0x01]) + bytes(data)
        self.send_cmd('t ' + b.hex())

    def set_language(self, code):
        """Set (OpType 0) de HumanMachineInterface.CurrentLanguage (FBlock 0x10, FktID 0x200): o HMI troca de idioma na hora."""
        self._tel(0x200, [code & 0xff], fblock=0x10, op=0x00)

    def _next(self):
        self.cnt = (self.cnt + 1) & 0xff
        if self.cnt == 0xff: self.cnt = 0
        return self.cnt

    def register(self):
        if not self.registered:
            self.registered = True; self.send_cmd('t ' + self.REGISTRY)

    def _rx(self):
        while not self.stop.is_set():
            try:
                d = self.sock.recv(4096).decode(errors='ignore')
            except socket.timeout:
                continue
            except OSError:
                return
            if not d.startswith('x '): continue
            try: h = bytes.fromhex(d[2:].strip())
            except ValueError: continue
            if len(h) < 12: continue
            if h[6] != 0xe5:                                          # outro FBlock (veículo etc.): só registra o que o HMI pediu
                self._other(h); continue
            fkt, op, data = h[8] << 8 | h[9], h[10], h[12:]
            if fkt == 0x001 and op == 0 and len(data) >= 5:          # Notification.Set (controle, DeviceID, FktIDs): manda o status atual
                fkts = [data[i] << 8 | data[i + 1] for i in range(3, len(data) - 1, 2)]
                if 0xc10 in fkts:                                     # o 1º status do rotor faz o HMI mandar o RotaryEncoderConfig.Set
                    with self.lock:
                        self._tel(0xc10, [1, 0x1d, self._next(), self.pos >> 8, self.pos & 0xff, 0x1e, 0])
            if fkt == 0xc30 and op == 0 and len(data) >= 3:          # RotaryEncoderConfig.Set: confirma com o mesmo contador
                with self.lock:
                    self._tel(0xc30, [1, 0x1d, data[2], 0])
                    self._tel(0xc10, [1, 0x1d, self._next(), self.pos >> 8, self.pos & 0xff, 0x1e, 0])   # posição de referência
                if not self.configured:
                    self.log('controlador iDrive configurado pelo HMI')
                    if self.language:
                        self.set_language(self.language)
                self.configured = True

    OPS = {0: 'Set', 1: 'Get', 2: 'SetGet', 3: 'Increment', 4: 'Decrement', 5: 'GetInterface', 6: 'StartResult', 7: 'Abort', 8: 'StartResultAck',
           9: 'AbortAck', 10: 'StartAck', 11: 'ErrorAck', 12: 'Status', 13: 'Interface', 14: 'Result', 15: 'Error'}

    def _other(self, h):
        """Telegrama do HMI para um FBlock que o emulador não serve: guarda (FBlock, instância, FktID, OpType) -> contagem e último dado (docs/CIC.md,
        "Dados do veículo"); com log=..., uma linha por telegrama novo."""
        k = (h[6], h[7], h[8] << 8 | h[9], h[10])
        n = self.seen.get(k, (0, ''))[0] + 1
        self.seen[k] = (n, h[12:].hex())
        if k[2] == 0x001 and k[3] == 0 and len(h) >= 17:             # Notification.Set (controle, DeviceID, FktIDs...): o que o HMI quer receber
            d = h[12:]
            self.subs.setdefault((k[0], k[1]), set()).update(d[3 + i] << 8 | d[4 + i] for i in range(0, len(d) - 4, 2))
        if n == 1:
            self.log('MOST HMI->%02x.%d fkt %03x %s %s' % (k[0], k[1], k[2], self.OPS.get(k[3], k[3]), h[12:].hex()))

    def rotate(self, delta):
        with self.lock:
            for _ in range(min(abs(delta), 20)):       # um passo por mensagem (o HMI anda um item por diferença)
                self.pos = (self.pos + (1 if delta > 0 else -1)) & 0xffff
                self._tel(0xc10, [1, 0x1d, self._next(), self.pos >> 8, self.pos & 0xff, 0x1e, 0])

    def key(self, code, down):
        k = self.KEYS.get(code)
        if not k: return
        field, direction, bits = k
        with self.lock:
            self._tel(0xc20, [1, 0x1d, self._next(), 1 if down else 0, direction if down else 0, field, bits])
