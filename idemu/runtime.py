"""Execução de um ambiente: renderizador (glhost) + QEMU + console serial + canais (shell, dados) + CAN/GPS/SSH."""
import os, sys, time, json, shlex, hashlib, socket, select, subprocess, threading, signal, mmap, struct, zlib, collections
from . import mapsvc, catalog

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, 'bin')

KEYS = {'MENU': 1, 'BACK': 2, 'OPTION': 3, 'CD': 4, 'RADIO': 5, 'TEL': 6, 'NAV': 7, 'PRESS': 8,
        'N': 9, 'S': 10, 'W': 11, 'E': 12, 'RIGHT': 13, 'LEFT': 14}

# CPU do guest. cntfrq: a QNX assume o contador de 6,144 MHz da OMAP5, mas o padrão do QEMU é 62,5 MHz: sem isso o relógio do guest anda 10,17x mais rápido que o real
# (temporizadores 10x mais frequentes, HMI e `most` mortos por watchdog, animações que pulam quadros). has_el3/has_el2=off: o guest roda sem TrustZone, de que não precisa, e o
# snapshot funciona (o QEMU 11.1.2 perde TTBR1_S e DACR_S ao restaurar uma CPU em modo seguro); stub.bin trata o `smc` da inicialização.
CPU = 'cortex-a15,cntfrq=6144000,has_el3=off,has_el2=off'
# bits forçados na leitura do banco de registradores da placa: 0x4a008f00 e 0x4a004400 = CLKACTIVITY (a inicialização esperava 12 milhões de voltas, ~9,5 s, por cada um)
SETBITS = '0x4a096804=2,0x4809a130=0x26,0x4a008f00=0x100,0x4a004400=0x100'
# núcleos do OMAP5 emulados (1 ou 2). Com 2, cada vCPU roda numa thread do Mac (MTTCG) e o QNX (procnto-smp) distribui HMI e serviços entre eles.
SMP = max(1, min(2, int(os.environ.get('IDEMU_SMP', '1') or 1)))
QEMU_ARM = os.environ.get('IDEMU_QEMU_ARM') or os.path.join(BIN, 'qemu-system-arm')

def _unix_connect(path, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        s = socket.socket(socket.AF_UNIX)
        try:
            s.connect(path); return s
        except OSError:
            s.close(); time.sleep(0.2)
    raise RuntimeError('não conectou em ' + path)

class ShellMux:
    """Serve um socket unix (shell.sock) ligado ao console de shell do guest (UART2)."""
    def __init__(self, uart_sock, path):
        self.uart_sock, self.path = uart_sock, path
        self.clients = []; self.lock = threading.Lock(); self.stop = False; self.up = False
        self.tail = collections.deque(maxlen=400)
    def start(self):
        try: os.unlink(self.path)
        except OSError: pass
        self.srv = socket.socket(socket.AF_UNIX); self.srv.bind(self.path); self.srv.listen(8)
        threading.Thread(target=self._accept, daemon=True).start()
        threading.Thread(target=self._pump, daemon=True).start()
    def _accept(self):
        while not self.stop:
            try: c, _ = self.srv.accept()
            except OSError: return
            with self.lock: self.clients.append(c)
            threading.Thread(target=self._client, args=(c,), daemon=True).start()
    def _client(self, c):
        try:
            while not self.stop:
                d = c.recv(4096)
                if not d: break
                if self.up: self.u.sendall(d)
        except OSError: pass
        finally:
            with self.lock:
                if c in self.clients: self.clients.remove(c)
            try: c.close()
            except OSError: pass
    def _pump(self):
        try: self.u = _unix_connect(self.uart_sock, 60)
        except Exception: return
        self.up = True
        while not self.stop:
            try: d = self.u.recv(4096)
            except OSError: break
            if not d: break
            self.tail.append(d.decode('latin1', 'replace'))
            with self.lock:
                for c in list(self.clients):
                    try: c.sendall(d)
                    except OSError: self.clients.remove(c)
    def close(self):
        self.stop = True
        socks = [getattr(self, 'srv', None), getattr(self, 'u', None)]
        with self.lock: socks += self.clients; self.clients = []
        for s in socks:                    # também a UART e os clientes: as sessões SSH abertas terminam em vez de ficarem penduradas
            try:
                if s: s.close()
            except Exception: pass

class ConsoleMux(ShellMux):
    """ShellMux de um console que outra parte do runtime já mantém aberto (o chardev do QEMU aceita um cliente só): `write(bytes)` manda ao guest e
    `feed(bytes)` entrega a saída do guest aos clientes (SSH, shell.sock). Usado pelo CIC e pelo iDrive 7."""
    def __init__(self, path, write):
        ShellMux.__init__(self, None, path); self._write = write; self.up = True
    def start(self):
        try: os.unlink(self.path)
        except OSError: pass
        self.srv = socket.socket(socket.AF_UNIX); self.srv.bind(self.path); self.srv.listen(8)
        threading.Thread(target=self._accept, daemon=True).start()
    def _client(self, c):
        try:
            while not self.stop:
                d = c.recv(4096)
                if not d: break
                self._write(d)
        except OSError: pass
        finally:
            with self.lock:
                if c in self.clients: self.clients.remove(c)
            try: c.close()
            except OSError: pass
    def feed(self, d):
        self.tail.append(d.decode('latin1', 'replace'))
        with self.lock:
            for c in list(self.clients):
                try: c.sendall(d)
                except OSError: self.clients.remove(c)

class Qmp:
    """Cliente mínimo do QMP (monitor do QEMU)."""
    def __init__(self, path, timeout=30):
        self.s = _unix_connect(path, timeout); self.s.settimeout(120); self.f = self.s.makefile('r'); self.lock = threading.Lock()
        self.f.readline(); self.cmd('qmp_capabilities')
    def cmd(self, name, **args):
        with self.lock:
            self.s.sendall((json.dumps({'execute': name, 'arguments': args}) + '\n').encode())
            while True:
                r = json.loads(self.f.readline() or '{"error":{"desc":"QMP fechou"}}')
                if 'error' in r: raise RuntimeError('QMP %s: %s' % (name, r['error'].get('desc')))
                if 'return' in r: return r['return']
    def close(self):
        for o in (self.f, self.s):
            try: o.close()
            except OSError: pass

SNAP_FORMAT = 2

class BootStopped(Exception):
    """O usuário parou o ambiente no meio do boot: o thread de boot só sai, sem marcar erro."""

class Runtime:
    def __init__(self, env_dir, env, run_root=None):
        self.env_dir, self.env = env_dir, env
        self.id = env['id']
        self.run = os.path.join(run_root or '/tmp/idemu-%d' % os.getuid(), self.id)
        self.img = os.path.join(env_dir, 'images'); self.logd = os.path.join(env_dir, 'logs')
        self.ctl = os.path.join(self.run, 'ctl')
        self.state = 'stopped'; self.err = None; self.t0 = None; self.step = ''; self.pct = 0
        self.gl = self.q = None; self.mux = None; self.can = self.gps = self.ssh = None
        self.frame_path = os.path.join(self.run, 'frame.rgb'); self._fm = None
        self._png = (None, None); self.con = collections.deque(maxlen=2000)
        self._cmd_lock = threading.Lock(); self.fps_t = collections.deque(maxlen=400); self._life = threading.Lock()
        self.stop_ev = threading.Event(); self.marks = {}
        self.snap_dir = os.path.join(env_dir, 'snapshot'); self.qmp = None; self.boot_kind = None; self.cpu_pct = 100.0

    # ---------- ciclo de vida ----------
    # ---------- boot rápido (snapshot) ----------
    def snapshot_key(self):
        """Muda quando qualquer coisa que o snapshot embute muda: imagens (inclusive shim.img, onde fica a codificação), binários, CPU."""
        parts = [SNAP_FORMAT, CPU, SETBITS, os.environ.get('IDEMU_CPU'), os.environ.get('IDEMU_QEMU_EXTRA')] + ([SMP] if SMP > 1 else [])
        for p in [os.path.join(self.img, n) for n in ('boot.ifs', 'sda.img', 'sdb.img', 'shim.img')] + [QEMU_ARM, os.path.join(BIN, 'glhost'), os.path.join(HERE, 'data', 'stub.bin')]:
            st = os.stat(p); parts.append((os.path.basename(p), st.st_size, int(st.st_mtime)))
        return hashlib.sha256(repr(parts).encode()).hexdigest()

    def snapshot_valid(self):
        try:
            with open(os.path.join(self.snap_dir, 'key.json')) as f:
                return json.load(f).get('key') == self.snapshot_key()
        except (OSError, ValueError):
            return False

    def snapshot_info(self):
        d = self.snap_dir; size = 0
        try:
            for n in os.listdir(d): size += os.path.getsize(os.path.join(d, n))
        except OSError:
            pass
        return {'valid': self.snapshot_valid(), 'size': size, 'enabled': self.fast_boot_enabled()}

    def fast_boot_enabled(self):
        return self.env.get('fast_boot', True) and not os.environ.get('IDEMU_NO_SNAPSHOT')

    def drop_snapshot(self):
        import shutil
        shutil.rmtree(self.snap_dir, ignore_errors=True)

    def start(self, cold=False):
        if self.state in ('booting', 'running'): return
        self.want_cold = cold
        for n in ('boot.ifs', 'sda.img', 'sdb.img', 'shim.img'):
            if not os.path.isfile(os.path.join(self.img, n)):
                raise RuntimeError('imagem ausente (%s): compile o ambiente primeiro' % n)
        import shutil
        shutil.rmtree(self.run, ignore_errors=True); os.makedirs(self.ctl); os.makedirs(self.logd, exist_ok=True)
        self.state = 'booting'; self.err = None; self.t0 = time.time(); self.marks = {}; self.step = 'Iniciando'; self.pct = 1; self._fm = None; self._lastseq = None; self.fps_t = collections.deque(maxlen=400)
        self.stop_ev.clear()
        threading.Thread(target=self._boot, daemon=True).start()

    def _log(self, name):
        return open(os.path.join(self.logd, name), 'w')

    def _shim_addr(self):
        """(endereço, setores) do disco de shim: 0x7f000000 nos shims de 15 MB (fora do buffer da ponte GL); os de 32 MB, de antes, ficam em 0x7e000000."""
        try: n = os.path.getsize(os.path.join(self.img, 'shim.img')) // 512
        except OSError: n = 0
        return (0x7f000000, n) if 0 < n <= 30720 else (0x7e000000, 65536)

    def _launch(self, resume=False, record=False):
        """Sobe renderizador e QEMU; devolve os caminhos dos sockets seriais."""
        B = BIN + '/'; R = self.run + '/'
        gls, ser, ser2, ser1, ser4 = R + 'gl.sock', R + 'ser.sock', R + 'ser2.sock', R + 'ser1.sock', R + 'ser4.sock'
        env = dict(os.environ, GLHOST_SOCK=gls, OMAP5_GLSOCK=gls, GLHOST_SHIDX=B + 'shader_index.txt',
                   GLHOST_GLSLDIR=B + 'glsl', GLHOST_MAPCACHE=mapsvc.CACHE, GLHOST_CTL=self.ctl, GLHOST_FRAME=self.frame_path,
                   OMAP5_SETBITS=SETBITS)
        if self.env.get('show_window'): env['GLHOST_SHOW'] = '1'
        S = self.snap_dir + '/'
        if resume: env['GLHOST_REPLAY'] = S + 'gl.rec'
        if record:
            os.makedirs(self.snap_dir, exist_ok=True); env['GLHOST_RECORD'] = S + 'gl.rec.tmp'
        self.step = 'Iniciando renderizador'; self.pct = 3
        self._spawn('gl', [B + 'glhost'], env=env, stdout=self._log('renderer.log'), stderr=subprocess.STDOUT, cwd=B)
        I = self.img + '/'
        args = [QEMU_ARM, '-M', 'omap5-uevm', '-m', '2048', '-cpu', os.environ.get('IDEMU_CPU', CPU), '-display', 'none',
                '-smp', str(SMP), '-accel', 'tcg,thread=multi' if SMP > 1 else 'tcg',
                '-serial', 'unix:%s,server,nowait' % ser, '-serial', 'unix:%s,server,nowait' % ser2,
                '-serial', 'unix:%s,server,nowait' % ser1, '-serial', 'unix:%s,server,nowait' % ser4, '-monitor', 'none',
                '-qmp', 'unix:%sqmp.sock,server,nowait' % R]
        if resume:
            args += ['-S', '-incoming', 'file:%svm.bin' % S]
        else:
            for _ in range(100):
                if os.path.exists(gls): break
                time.sleep(0.05)
            args += ['-device', 'loader,file=%sboot.ifs,addr=0x80100000' % I,
                     '-device', 'loader,file=%s,addr=0xbff00000' % os.environ.get('IDEMU_STUB', os.path.join(HERE, 'data', 'stub.bin')),
                     '-device', 'loader,addr=0xbff00000,cpu-num=0',
                     '-device', 'loader,file=%ssda.img,addr=0x60000000' % I,
                     '-device', 'loader,file=%ssdb.img,addr=0x01000000' % I,
                     '-device', 'loader,file=%sshim.img,addr=%#x' % (I, self._shim_addr()[0])]
        args += shlex.split(os.environ.get('IDEMU_QEMU_EXTRA', ''))
        self.step = 'Iniciando QEMU'; self.pct = 5
        self._spawn('q', args, env=env, stdout=self._log('qemu.log'), stderr=subprocess.STDOUT)
        self.ser4 = ser4
        self.qmp = Qmp(R + 'qmp.sock')
        return ser, ser2, ser1

    def _boot(self):
        try:
            if self.fast_boot_enabled() and not self.want_cold and self.snapshot_valid():
                try:
                    self._boot_resume()
                    if self.state == 'error' and not self.stop_ev.is_set(): self._kill_children()      # caiu depois do boot rápido: não deixa QEMU/renderizador/portas para trás
                    return
                except Exception as e:
                    if self.stop_ev.is_set(): return
                    self.con.append('[idemu] boot rápido falhou (%s: %s); fazendo boot completo' % (type(e).__name__, e))
                    self.drop_snapshot(); self._kill_children()
                    self._reset_run()
            self._boot_cold()
            if self.state == 'error' and not self.stop_ev.is_set(): self._kill_children()      # renderizador ou QEMU caiu: não deixa o resto (portas CAN/GPS, sshd, V850) para trás
        except BootStopped: pass
        except Exception as e:
            if not self.stop_ev.is_set():
                self.state = 'error'; self.err = '%s: %s' % (type(e).__name__, e)
                self._kill_children()
            self.stop_ev.set()

    def _reset_run(self):
        import shutil
        shutil.rmtree(self.run, ignore_errors=True); os.makedirs(self.ctl); self._fm = None; self._lastseq = None
        self.t0 = time.time(); self.marks = {}

    def _boot_resume(self):
        """Volta de um snapshot: em vez de reiniciar o sistema, restaura a RAM/CPU (QEMU), o estado GL (replay no glhost) e o V850 virtual."""
        self.boot_kind = 'fast'; self.step = 'Restaurando o sistema salvo'; self.pct = 20
        ser, ser2, ser1 = self._launch(resume=True)
        threading.Thread(target=self._profile, daemon=True).start()
        end = time.time() + 120
        while self.qmp.cmd('query-status')['status'] == 'inmigrate':
            if time.time() > end or self._dead(): raise RuntimeError('o QEMU não terminou de carregar o snapshot')
            time.sleep(0.02)
        self._mark('vm_loaded'); self.pct = 50
        while not os.path.exists(os.path.join(self.run, 'gl.sock')):
            if time.time() > end or self._dead(): raise RuntimeError('o renderizador não restaurou o estado GL')
            time.sleep(0.02)
        self._mark('gl_loaded'); self.pct = 70
        with open(os.path.join(self.snap_dir, 'host.json')) as f: host = json.load(f)
        self._start_services(ser2, ser1, host)
        s = _unix_connect(ser, 30); s.setblocking(False)
        self.cons = s; self.conlog = open(os.path.join(self.logd, 'console.log'), 'wb'); self._scan = None
        self.qmp.cmd('cont'); self._mark('resumed'); self.pct = 85
        self.step = 'Verificando o sistema'
        if not self._guest_alive(15): raise RuntimeError('o guest não respondeu depois de restaurado')
        if self.stop_ev.is_set(): return          # parado durante a verificação: não volta a marcar "em execução"
        self.state = 'running'; self.pct = 100; self.step = 'Em execução'; self._mark('running')
        while not self.stop_ev.is_set() and not self._dead():
            self._drain(1.0)

    def _guest_alive(self, timeout):
        """Pergunta ao shell do guest (UART2): prova que o sistema restaurado continua rodando."""
        tag = b'IDEMU_ALIVE_%d' % int(time.time())
        c = _unix_connect(os.path.join(self.run, 'shell.sock'), 5); c.settimeout(0.5); buf = b''; end = time.time() + timeout; last = 0
        try:
            while time.time() < end:
                if time.time() - last > 2:
                    # (o eco do tty pode vir com o comando: só vale a saída, com o texto montado pelo shell)
                    c.sendall(b'echo ' + tag[:6] + b'""' + tag[6:] + b'\n'); last = time.time()
                try: buf += c.recv(4096)
                except socket.timeout: pass
                if tag in buf: return True
        finally:
            c.close()
        return False

    def _boot_cold(self):
        record = self.fast_boot_enabled()
        self.boot_kind = 'cold'
        self._boot_key = self.snapshot_key() if record else None    # chave das imagens que este boot usa: um shim refeito durante o boot (recodificação) não pode herdar o snapshot
        ser, ser2, ser1 = self._launch(record=record)
        threading.Thread(target=self._profile, daemon=True).start()
        self._start_services(ser2, ser1)
        s = _unix_connect(ser, 30); s.setblocking(False)
        self.cons = s; self.conlog = open(os.path.join(self.logd, 'console.log'), 'wb')
        self.step = 'Aguardando o QNX (console)'; self.pct = 8
        self._mark('console')
        last = 0; end = time.time() + 900
        while time.time() < end:
            if self._dead(): return
            if time.time() - last > 0.5: self.cons.send(b'\n'); last = time.time()
            if b'#' in self._drain(0.05): break
        self._mark('prompt')
        # cada passo espera pelo próprio fim (marcador no eco do shell), sem pausas fixas
        seq = [('export PATH=/bin:/boot/bin LD_LIBRARY_PATH=/boot/lib:/lib', 10, 'Preparando discos', 12),
               ('devb-ram disk name=sda ram address=0x60000000,capacity=983040,nodinit blk cache=32m', 10, None, 14),
               ('devb-ram disk name=sdb ram address=0x01000000,capacity=2064384,nodinit blk cache=32m', 10, None, 16),
               ('devb-ram disk name=sdc ram address=%#x,capacity=%d,nodinit blk cache=1m' % self._shim_addr(), 10, None, 18),
               ('waitfor /dev/sda0t77 20; waitfor /dev/sdb0 20; waitfor /dev/sdc0t77 20', 60, None, 20),
               ('mount -t qnx4 /dev/sda0t77 /fs/sda0', 30, 'Montando sistema de arquivos', 22),
               ('mount -t qnx6 -r /dev/sdb0 /fs/sdb0', 30, None, 24),
               ('mount -t qnx4 /dev/sdc0t77 /fs/shim', 30, None, 26),
               ('R=/fs/sda0/repository/istep', 10, None, 27),
               ('mkdir -p $R/var/opt/hmi/data/rw $R/var/opt/sys $R/var/dump', 30, None, 28),
               ('ln -sP $R/bin /bin; ln -sP $R/lib /lib; ln -sP $R/etc /etc; ln -sP $R/opt /opt; ln -sP $R/var /var', 30, None, 29),
               ('ln -sP /opt/hmi/ID5/bin /opt/hmi/bin; ln -sP /opt/hmi/ID5/lib /opt/hmi/lib; ln -sP /opt/hmi/ID5/data /opt/hmi/data; ln -sP /fs/sdb0/ro /opt/hmi/ID5/data/ro', 30, None, 29),
               ('HMI_DELAY=%s IDEMU_HMI_ON="%s" IDEMU_TCPDUMP=%s IDEMU_SB_VERBOSE=%s IDEMU_NO_HMI=%s ksh /fs/shim/boot.sh' % (os.environ.get('IDEMU_HMI_DELAY', '0'), os.environ.get('IDEMU_HMI_ON', 'on -R 1' if SMP > 1 else ''), os.environ.get('IDEMU_TCPDUMP', ''), os.environ.get('IDEMU_SB_VERBOSE', ''), os.environ.get('IDEMU_NO_HMI', '')), 300, 'Iniciando serviços do sistema', 30)]
        stage_pct = {'services': 35, 'hmi': 48, 'up': 55}
        hmi_t = [None]; hmi_seq = [0]; last_fs = [0]; last_chg = [time.time()]
        def scan(out):
            for k, v in stage_pct.items():
                if 'IDEMU_STAGE ' + k in out:
                    self.pct = max(self.pct, v); self._mark('stage_' + k)
                    self.step = {'services': 'Iniciando serviços do sistema', 'hmi': 'Iniciando o HMI (iDrive)', 'up': 'Carregando a interface gráfica'}[k]
                    if k == 'up': hmi_t[0] = time.time(); hmi_seq[0] = self.frame_seq()
        self._scan = scan
        for c, w, st, p in seq:
            if st: self.step = st
            self.pct = p
            self._sh(c, w)
            if self._dead(): return
        ready = False
        while not self.stop_ev.is_set() and not self._dead():
            out = self._drain(0.25).decode('latin1', 'replace')
            scan(out)
            fs = self.frame_seq()
            if fs != last_fs[0]: last_fs[0] = fs; last_chg[0] = time.time()
            # pronto = a tela inicial já foi desenhada (>= 5 quadros novos) e a imagem estabilizou (tela estática não gera quadros)
            settled = fs >= hmi_seq[0] + 5 and time.time() - last_chg[0] > 3
            if not ready and hmi_t[0] and (fs > hmi_seq[0] + 12 or settled or (fs > hmi_seq[0] and time.time() - hmi_t[0] > 100)):
                ready = True; self._mark('ready')
                if record:
                    self.step = 'Salvando para o próximo boot ser rápido'; self.pct = 92
                    try:
                        self._save_snapshot()
                    except Exception as e:
                        self.con.append('[idemu] snapshot não criado: %s: %s' % (type(e).__name__, e)); self.drop_snapshot()
                if self.stop_ev.is_set(): return                  # parado durante o snapshot: não volta para "em execução"
                self.state = 'running'; self.pct = 100; self.step = 'Em execução'; self._mark('running')
            elif not ready and hmi_t[0]:
                self.pct = min(90, 55 + int((time.time() - hmi_t[0]) / 30.0 * 35))

    def _save_snapshot(self):
        """Salva o sistema já pronto: RAM+CPU (migração do QEMU para arquivo), gravação GL do glhost e estado do V850 virtual."""
        # só salva com o HMI quieto (terminou de subir e de animar a tela inicial): todo boot rápido vai partir exatamente deste instante
        end = time.time() + 30; quiet = None; seq = self.frame_seq(); chg = time.time()
        while time.time() < end and not self.stop_ev.is_set() and not self._dead():
            self._drain(0.25)
            fs = self.frame_seq()
            if fs != seq: seq = fs; chg = time.time()
            if self.cpu_pct < 50 and time.time() - chg > 2:
                quiet = quiet or time.time()
                if time.time() - quiet > 3: break
            else:
                quiet = None
        self._mark('settled')
        S = self.snap_dir + '/'
        v = getattr(self, 'v850', None)
        if v: v.bridge.hold(True)
        try:
            self._drain(0.4)                                   # o que já foi escrito na UART chega ao guest; depois disso, nada a caminho
            self.qmp.cmd('stop')
            time.sleep(0.05)                                   # o que o guest já escreveu chega ao leitor do V850
            done = os.path.join(self.ctl, 'glrec.done')
            open(os.path.join(self.ctl, 'glrec.stop'), 'w').close()
            for _ in range(2000):
                if os.path.exists(done): break
                time.sleep(0.005)
            else:
                raise RuntimeError('o renderizador não encerrou a gravação')
            host = {'v850': v.export_state() if v else None}
            self.qmp.cmd('migrate-set-parameters', **{'max-bandwidth': 1 << 40})
            self.qmp.cmd('migrate', uri='file:%svm.bin.tmp' % S)
            while True:
                r = self.qmp.cmd('query-migrate')
                if r.get('status') == 'completed': break
                if r.get('status') in ('failed', 'cancelled'): raise RuntimeError('migração: %s' % r.get('error-desc'))
                time.sleep(0.02)
            with open(S + 'host.json', 'w') as f: json.dump(host, f)
            os.replace(S + 'vm.bin.tmp', S + 'vm.bin'); os.replace(S + 'gl.rec.tmp', S + 'gl.rec')
            with open(S + 'key.json.tmp', 'w') as f: json.dump({'key': getattr(self, '_boot_key', None) or self.snapshot_key(), 'created': time.time()}, f)
            os.replace(S + 'key.json.tmp', S + 'key.json')          # por último: só vale se tudo acima foi gravado
            self._mark('snapshot')
        finally:
            try:
                self.qmp.cmd('cont')
            finally:
                if v: v.bridge.hold(False)

    def _dead(self):
        if self.stop_ev.is_set(): return True
        for p, n in ((self.gl, 'renderizador'), (self.q, 'QEMU')):
            if p is not None and p.poll() is not None:
                self.state = 'error'; self.err = '%s encerrou (código %s)' % (n, p.returncode); return True
        return False

    def _drain(self, t, early=False):
        end = time.time() + t; out = b''
        while True:
            left = end - time.time()
            if left <= 0: break
            r, _, _ = select.select([self.cons], [], [], min(left, 0.2))
            if r:
                try: b = self.cons.recv(65536)
                except BlockingIOError: continue
                if not b: break
                out += b; self.conlog.write(b); self.conlog.flush()
                for ln in b.decode('latin1', 'replace').splitlines():
                    if ln.strip(): self.con.append(ln)
                if early: break
        return out

    def _profile(self):
        """Amostra o uso de CPU do QEMU (logs/boot-profile.csv: t, cpu%, quadros, estado): mostra se o boot está limitado por CPU ou por esperas."""
        last_c = last_t = None
        try: f = open(os.path.join(self.logd, 'boot-profile.csv'), 'w'); f.write('t_s,cpu_pct,frame_seq,step\n')
        except OSError: return
        while not self.stop_ev.is_set() and self.q is not None and self.q.poll() is None:
            try:
                o = subprocess.run(['ps', '-o', 'time=', '-p', str(self.q.pid)], capture_output=True, text=True, timeout=3).stdout.strip()
                m, sec = o.split(':'); c = int(m) * 60 + float(sec)
            except Exception:
                time.sleep(1); continue
            now = time.time()
            if last_c is not None:
                self.cpu_pct = 100 * (c - last_c) / max(now - last_t, 1e-3)
                f.write('%.1f,%.0f,%d,%s\n' % (now - self.t0, self.cpu_pct, self.frame_seq(), self.step)); f.flush()
            last_c, last_t = c, now
            time.sleep(1)

    def _mark(self, name):
        """Registra o instante de uma fase do boot (logs/boot-timing.json) — base para medir o tempo de boot."""
        if name in self.marks: return
        t = round(time.time() - self.t0, 1)
        self.marks[name] = t
        try:
            json.dump(self.marks, open(os.path.join(self.logd, 'boot-timing.json'), 'w'), indent=1)
        except OSError: pass

    def _sh(self, c, timeout=60):
        """Executa no console do guest e espera o fim do comando (marcador com o código de saída no eco)."""
        import re
        self._seqn = getattr(self, '_seqn', 0) + 1
        tag = 'IDEMU_OK%d' % self._seqn
        self.cons.send(('%s; echo %s_$?\n' % (c, tag)).encode())
        pat = re.compile(tag + r'_(\d+)'); end = time.time() + timeout; buf = ''
        while time.time() < end and not self._dead():
            buf += self._drain(0.02, True).decode('latin1', 'replace')
            if getattr(self, '_scan', None): self._scan(buf)
            m = pat.search(buf)
            if m: return buf
        return buf

    def _cmd(self, c, w=1.0):
        self.cons.send((c + '\n').encode()); return self._drain(w)

    def _start_services(self, ser2, ser1, host=None):
        self.mux = ShellMux(ser2, os.path.join(self.run, 'shell.sock')); self.mux.start()
        try:
            from . import v850
            if os.environ.get('IDEMU_V850_EXTERNAL'): raise RuntimeError('V850 externo (modo de desenvolvimento): python3 -m idemu.v850')
            self.v850 = v850.V850Link(self.ser4, os.path.join(self.logd, 'v850.log'))
            if host and host.get('v850'): self.v850.import_state(host['v850'])
            self.v850.start()
        except Exception as e:
            self.con.append('[idemu] V850: %s' % e)
        net = self.env.get('net', {})
        try:
            from . import canbus, gps, sshbridge
        except Exception as e:
            self.con.append('[idemu] módulos CAN/GPS/SSH indisponíveis: %s' % e); return
        try:
            self.can = canbus.CanBus(tcp_port=net.get('can_port'), rec_dir=os.path.join(self.env_dir, 'recordings')); self.can.start()
            self.gps = gps.GpsSim(can=self.can, tcp_port=net.get('gps_port')); self.gps.start()
            self.map = mapsvc.MapService(self.ctl, self.gps, catalog.load_settings()); self.map.start()
            if getattr(self, 'v850', None): self.v850.bridge.car.map = self.map
            if getattr(self, 'v850', None): self.v850.bridge.car.gps = self.gps; self.v850.bridge.car.attach_can(self.can)      # dados do carro -> HMI (MOST, ponte do canal 25)
            # Canal de arquivos CAN/GPS no guest (/var/idemu/{can,gps}, UART1): ninguém no guest o consome desde que os dados chegam ao HMI pelo MOST
            # (idemu/most.py) e, ligado, ele derruba o `most` (ver docs/V850.md) -> só com IDEMU_DATA_CHANNEL=1.
            if os.environ.get('IDEMU_DATA_CHANNEL'): self.data = DataChannel(ser1, self.can, self.gps, self); self.data.start()
        except Exception as e:
            self.con.append('[idemu] CAN/GPS: %s' % e)
        self._start_ssh()
        if self.stop_ev.is_set(): self._kill_children()       # parado enquanto os serviços subiam

    def _start_ssh(self):
        """sshd sem root ligado ao shell.sock (console do guest)."""
        try:
            from . import sshbridge
            self.ssh = sshbridge.SshBridge(self.env_dir, self.env.get('net', {}).get('ssh_port', 2222), os.path.join(self.run, 'shell.sock'))
            ok, msg = self.ssh.start(); self.con.append('[idemu] ssh: %s' % msg)
        except Exception as e:
            self.con.append('[idemu] SSH: %s' % e)

    def _spawn(self, attr, *a, **kw):
        """Popen que não deixa processo órfão: com o ambiente já parado, não inicia; o processo novo fica em self.<attr> antes que stop() possa olhar."""
        with self._life:
            if self.stop_ev.is_set(): raise BootStopped()
            p = subprocess.Popen(*a, **kw); setattr(self, attr, p)
            return p

    def stop(self):
        with self._life: self.stop_ev.set()
        self._kill_children()
        self.state = 'stopped'; self.pct = 0; self.step = ''

    def _kill_children(self):
        for o in (getattr(self, 'v850', None), getattr(self, 'data', None), getattr(self, 'map', None), self.ssh, self.gps, self.can, self.mux):
            try:
                if o:
                    (o.close if hasattr(o, 'close') else o.stop)()
            except Exception: pass
        self.v850 = self.data = self.map = None; self.ssh = self.gps = self.can = self.mux = None
        if self.qmp: self.qmp.close(); self.qmp = None
        for a in ('cons', 'conlog', '_insock'):              # console, log do console e socket de entrada: um a menos a cada parada/partida
            o = getattr(self, a, None)
            if o is not None:
                try: o.close()
                except Exception: pass
                setattr(self, a, None)
        for p in (self.q, self.gl):
            try:
                if p: p.terminate()
            except Exception: pass
        for p in (self.q, self.gl):
            try:
                if p: p.wait(5)
            except Exception:
                try: p.kill()
                except Exception: pass
        self.q = self.gl = None; self._fm = None

    # ---------- status ----------
    def status(self):
        net = self.env.get('net', {})
        return {'state': self.state, 'env': self.id, 'uptime_s': round(time.time() - self.t0, 1) if self.t0 and self.state != 'stopped' else 0,
                'boot_step': self.step, 'boot_pct': self.pct,
                'ports': {'ssh': net.get('ssh_port'), 'can': net.get('can_port'), 'gps': net.get('gps_port')},
                'frame_seq': self.frame_seq(), 'fps': self._fps(), 'error': self.err, 'boot_kind': self.boot_kind, 'marks': self.marks,
                'touchpad': self.has_touchpad()}

    def has_touchpad(self):
        """iDrive 5/6 with the iDrive Touch Controller coded (ZBE_TOUCH): the web UI shows its touchpad only then."""
        if getattr(self, 'kind', None): return False
        if getattr(self, '_touchpad', None) is None:
            from . import codegen
            try: self._touchpad = codegen.has_touch_controller(self.env)
            except Exception: self._touchpad = False
        return self._touchpad

    def _fps(self):
        now = time.time(); ft = self.fps_t
        if not isinstance(ft, collections.deque): ft = self.fps_t = collections.deque(ft, maxlen=400)
        while ft and now - ft[0] >= 3: ft.popleft()
        return round(len(ft) / 3.0, 1)

    # ---------- quadro de vídeo ----------
    def _map(self):
        # o renderizador pode recriar ou aumentar o arquivo (superfície nova): mapeia de novo quando o inode ou o tamanho mudam, em vez de ler um mapeamento velho
        try: st = os.stat(self.frame_path); key = (st.st_ino, st.st_size)
        except OSError: return self._fm
        if self._fm is None or getattr(self, '_fm_key', None) != key:
            try:
                with open(self.frame_path, 'rb') as f: fm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            except Exception:
                return self._fm if self._fm is not None and len(self._fm) <= st.st_size else None
            old, self._fm, self._fm_key = self._fm, fm, key
            if old is not None:
                try: old.close()
                except Exception: pass
        return self._fm

    def frame_seq(self):
        m = self._map()
        if not m or len(m) < 32: return 0
        magic, seq, w, h = struct.unpack_from('<IIII', m, 0)
        if magic != 0x52464449: return 0
        last = getattr(self, '_lastseq', None)
        if seq != last:
            self._lastseq = seq; now = time.time()
            if last is not None and seq > last: self.fps_t.extend([now] * min(seq - last, 60))
        return seq

    def frame_bytes(self):
        """(seq, largura, altura, bytes RGB) do quadro atual. O renderizador escreve por cima: recopia se o quadro mudou durante a cópia."""
        m = self._map()
        if not m or len(m) < 32: return None
        for _ in range(6):
            magic, seq, w, h, busy = struct.unpack_from('<IIIII', m, 0)       # busy = quadro em escrita (glhost novo); 0 nos binários antigos
            if magic != 0x52464449 or not seq or len(m) < 32 + w * h * 3: return None
            if busy and busy != seq: time.sleep(0.002); continue
            raw = bytes(m[32:32 + w * h * 3])
            if struct.unpack_from('<II', m, 4) == (seq, w) and struct.unpack_from('<I', m, 16)[0] == busy: break    # nada recomeçou durante a cópia
        return seq, w, h, raw

    def screen_png(self):
        m = self._map(); seq = self.frame_seq()
        if not m or not seq: return None, 0
        if self._png[0] == seq: return self._png[1], seq
        fr = self.frame_bytes()
        if not fr: return None, 0
        seq, w, h, raw = fr
        rows = b''.join(b'\0' + raw[y * w * 3:(y + 1) * w * 3] for y in range(h))
        def ch(t, d): c = struct.pack('>I', len(d)) + t + d; return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
        png = b'\x89PNG\r\n\x1a\n' + ch(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + ch(b'IDAT', zlib.compress(rows, 1)) + ch(b'IEND', b'')
        self._png = (seq, png)
        return png, seq

    # ---------- entrada ----------
    def send_cmd(self, line):
        with self._cmd_lock:
            if getattr(self, '_insock', None) is None:
                self._insock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            self._insock.sendto(line.encode(), os.path.join(self.ctl, 'input.sock'))

    def key(self, code, val): self.send_cmd('1 %d %d' % (code, val))
    def touch(self, x, y, down, move=False):
        """Toque na tela do CID (iDrive 5/6): x, y na resolução do display. O guest monta um CTouchData (estado 1 toca, 2 move, 3 solta)."""
        st = 2 if move else (1 if down else 3)
        self.send_cmd('40 %d %d %d' % (st, (int(x) & 0xffff) | ((int(y) & 0xffff) << 16), int(time.monotonic() * 1000) & 0x7fffffff))
    def touchpad(self, x, y, down, move=False, x2=None, y2=None):
        """iDrive Touch Controller (o touchpad na tampa do controlador, iDrive 5/6): x, y de 0 a 1 a partir do canto superior esquerdo; x2, y2 = um
        segundo dedo. O shim entrega um CTouchData de origem 3 (evento 41; o segundo dedo vai antes no evento 42), como o CTouchPadService faz com o
        CccsAbsoluteCoordinates do controlador (MOST 0xE5.01 0xC44, dois dedos): coordenadas 0..511, ids 0 e 1. Só a atividade que liga o
        touchpad o usa (no CarPlay vira CarPlayTouchPadInput, docs/TOUCH_CONTROLLER.md)."""
        st = 2 if move else (1 if down else 3)
        def xy(a, b):
            px, py = (max(0, min(511, int(round(float(v) * 511)))) for v in (a, b))
            return px | (py << 16)
        two = x2 is not None and y2 is not None
        hw = getattr(self, 'hwr', None)                       # handwriting in the HMI's spellers (idemu/hwr.py)
        if hw is None and getattr(getattr(self, 'v850', None), 'bridge', None) is not None:
            from . import hwr
            hw = self.hwr = hwr.Handwriting(self.v850.bridge, lambda t: self.con.append('[idemu] ' + t))
        if hw is not None and not two: hw.touch(float(x), float(y), st)
        if two: self.send_cmd('42 %d %d 0' % (st, xy(x2, y2)))
        self.send_cmd('41 %d %d %d' % (st | (0x100 if two else 0), xy(x, y), int(time.monotonic() * 1000) & 0x7fffffff))
    def rotor(self, delta):
        if delta: self.send_cmd('2 %d %d' % (14 if delta < 0 else 13, abs(int(delta))))

class DataChannel:
    """Entrega estado CAN/GPS ao guest pela UART1: linhas 'C ID HEX' e 'G $NMEA' (agente do guest em /fs/shim)."""
    def __init__(self, uart_sock, can, gps, rt):
        self.uart_sock, self.can, self.gps, self.rt = uart_sock, can, gps, rt
        self.last = {}; self.dirty = {}; self.stop_ev = threading.Event(); self.lock = threading.Lock(); self.sock = None
    def start(self):
        if self.can: self.can.on_frame(self._frame)
        if self.gps: self.gps.on_nmea(self._nmea)
        threading.Thread(target=self._run, daemon=True).start()
    def _frame(self, ts, can_id, data, ext, name, direction):
        with self.lock: self.dirty['C %X %s' % (can_id, data.hex())] = can_id
    def _nmea(self, line):
        with self.lock: self.dirty['G ' + line.strip()] = 'g' + line.strip()[:6]
    def _run(self):
        try: self.sock = _unix_connect(self.uart_sock, 90)
        except Exception: return
        while not self.stop_ev.is_set():
            time.sleep(0.25)
            if self.rt.state != 'running': 
                with self.lock: self.dirty.clear()
                continue
            with self.lock:
                items = {}
                for k, v in self.dirty.items(): items[v] = k      # só o último de cada ID
                self.dirty.clear()
            if items:
                try: self.sock.sendall(('\n'.join(items.values()) + '\n').encode())
                except OSError: return
    def close(self): self.stop_ev.set()
