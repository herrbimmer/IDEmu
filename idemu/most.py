"""Servidor MOST falso (lado do host) para o `most` do SWFL.

No hardware, o `most` da head unit roda em modo *client* (`--devmode=client --SIPCProtocol=tcp`) e depende de dois canais com o
processador MOST (J5): o papel DSI `MOSTSubSystemServer.DSYSMOSTServer` (registro, registry, mensagens) e uma conexão SIPC por TCP
(porta 5555, endereço em $IPC_IP_ADDRESS) com os telegramas MOST.  No IDEmu o guest escuta em 127.0.0.1:5555 (SIPC) e :5556 (DSI)
dentro de `ioipc-idemu.so` e tunela os bytes pela UART do V850; as classes daqui são a outra ponta de cada conexão.
"""
import threading
import time


class _Peer(object):
    name = 'peer'

    def __init__(self, link):
        self.link = link
        self.conns = {}                                  # conn -> bytearray (recepção)
        self.stats = {'connections': 0, 'bytes_from_guest': 0, 'bytes_to_guest': 0}
        self.recent = []

    @property
    def connected(self):
        return bool(self.conns)

    def on_open(self, conn):
        self.conns[conn] = bytearray()
        self.stats['connections'] += 1
        self.link.log('%s[%d]: conectou' % (self.name, conn))

    def on_close(self, conn):
        self.conns.pop(conn, None)
        self.link.log('%s[%d]: desconectou' % (self.name, conn))

    def on_data(self, conn, data):
        self.stats['bytes_from_guest'] += len(data)
        self.link.log('%s[%d] <- %d bytes: %s' % (self.name, conn, len(data), bytes(data[:128]).hex()))
        self.recent.append((round(time.time() - self.link.t0, 2), 'rx', bytes(data[:48]).hex()))
        del self.recent[:-40]

    def send(self, data, conn=None):
        conn = next(iter(self.conns), None) if conn is None else conn
        if conn is None:
            return
        self.stats['bytes_to_guest'] += len(data)
        self.link.log('%s[%d] -> %d bytes: %s' % (self.name, conn, len(data), bytes(data[:128]).hex()))
        self.link.conn_write(conn, data)

    def snapshot(self):
        d = dict(self.stats)
        d['connected'] = self.connected
        d['recent'] = list(self.recent[-12:])
        return d


class MostSipc(_Peer):
    """Telegramas MOST (`most` -> J5) em [len:4 LE][MessageType][padding até múltiplo de 4]."""
    name = 'SIPC'


class MostDsi(_Peer):
    """Papel DSI `MOSTSubSystemServer.DSYSMOSTServer` (versão 4.5): registrado no servicebroker do guest como interface TCP
    apontando para 127.0.0.1:5556, que o guest tunela até aqui.  O protocolo (MoCCA DSI sobre TCP) ainda está em estudo."""
    name = 'DSI'
    ROLE, PORT, VERSION = 'MOSTSubSystemServer.DSYSMOSTServer', 5556, (4, 5)

    def register(self, ip=0x7f000001):
        self.link.log('DSI: registrando %s v%d.%d (porta %d)' % (self.ROLE, self.VERSION[0], self.VERSION[1], self.PORT))
        self.link.sb_register(self.ROLE, self.PORT, self.VERSION[0], self.VERSION[1], ip)


class MostBridge(object):
    """Canal 25 do io-ipc: a ponte DSI do `most` (CDSYSMOSTServerDSIIPCBridgeStub) com o V850.

    Mensagem = cabeçalho de 20 bytes + payload (CHBByteStream: inteiros little-endian sem alinhamento):
        [0]   u8   1
        [2]   u16  chave da interface (0x04f1, a mesma que o `most` envia no "hello")
        [4]   u8   versão maior (4)     [5] u8 versão menor (5)
        [6]   u16  id da mensagem: requisição 1..0x13; assinatura/atualização = 0x8000|n e 0xC000|n (UpdateId 0x8000000n / 0xC000000n)
        [8]   u16  tamanho total (cabeçalho + payload)
        [0x10] u16 chave do cliente (o `most` guarda o valor recebido e o devolve nas respostas)
    Requisições (V850 -> `most`): 2/6/7 registrar dispositivos/controladores (id do cliente u32 + vetor), 4 `requestProcessMessage`,
    5 `registerMOSTClient` (sem payload), 8 `requestChangeInstID` (u32,u16,u8), 9 `requestCleanUp`...
    """
    KEY, VER = 0x04f1, (4, 5)

    def __init__(self, link):
        self.link = link
        self.hello = None
        self.msgs = []
        self.stats = {'rx': 0, 'tx': 0}
        self.subs = {}          # (FBlock, instância) -> {FktID: dispositivo ouvinte}
        self.counts = {}
        self.seen = {}          # (FBlock, instância, FktID) -> última mensagem Set/SetGet/Get do HMI (o que o HMI manda a Kombi, HUD etc.): {'op','data','t','n'}
        self.device_id = 0x2002
        self._acked = {}
        self._hold = False
        self.car = MostCar(self)

    @staticmethod
    def parse(p):
        if len(p) < 20:
            return None
        import struct
        return {'b0': p[0], 'key': struct.unpack_from('<H', p, 2)[0], 'ver': (p[4], p[5]), 'id': struct.unpack_from('<H', p, 6)[0],
                'len': struct.unpack_from('<H', p, 8)[0], 'cf': struct.unpack_from('<H', p, 0x10)[0], 'payload': bytes(p[20:])}

    def on_message(self, payload):
        h = self.parse(payload)
        self.stats['rx'] += 1
        if h is None:
            self.link.log('ponte25: mensagem curta %s' % bytes(payload).hex())
            return
        if self.hello is None:
            self.hello = h
            if getattr(self.link, 'bridge_auto', True):
                self.start()
        if h['id'] == 0x8000 and len(h['payload']) >= 6:
            self.on_client_registered(*_st.unpack_from('<IH', h['payload']))
            return
        self.msgs.append(h)
        del self.msgs[:-60]
        # 29 = id do cliente (4) + cabeçalho da MessageType (25), sem dados. Com o mínimo antigo (33) os telegramas com menos de 4 bytes de dados (o Set do modo do mapa,
        # MapControl 0x222, leva 1 byte; os Get, 0 ou 1) iam só para o log e nunca eram respondidos: a tile Navegação da tela inicial ficava preta (docs/V850.md, "Mapa")
        if h['id'] == 0x8001 and len(h['payload']) >= 29:
            try:
                self.on_most(MostMessage.parse(h['payload'], 4))
            except Exception as e:          # um telegrama estranho nunca derruba o enlace
                self.link.log('ponte25: telegrama ilegível: %r' % (e,))
            return
        self.link.log('ponte25 <- id=%#x len=%d cf=%#x payload=%s' % (h['id'], h['len'], h['cf'], h['payload'][:64].hex()))

    # --- snapshot (boot rápido) ---------------------------------------------------------------------------------
    def hold(self, on):
        """Pausa/retoma o envio ao guest (na pausa os quadros esperam na fila): nada pode estar a caminho quando o QEMU salva o estado."""
        self._hold = on
        cv = getattr(self, '_cv', None)
        if cv is not None:
            with cv:
                cv.notify_all()

    def export_state(self):
        q = getattr(self, '_pending', None) or {}
        with getattr(self, '_cv', threading.Condition()):
            frames = [f.hex() for f in q.values()]
        return {'hello': self.hello is not None, 'client': self.CLIENT, 'device_id': self.device_id, 'subs': [[k[0], k[1], {'%x' % f: d for f, d in v.items()}] for k, v in self.subs.items()],
                'acked': [list(k) for k in self._acked], 'sent': [[k[0], k[1], k[2], v.hex()] for k, v in self.car._sent.items()], 'avg_speed': self.car.avg_speed, 'avg_cons': self.car.avg_cons,
                'trip': [self.car.trip_start, self.car.trip_odo], 'pending': frames}

    def import_state(self, d):
        self.hello = {} if d['hello'] else None      # já registrado: o `most` não vai repetir o "hello"
        self.CLIENT, self.device_id = d['client'], d['device_id']
        self.subs = {(a, b): {int(f, 16): dev for f, dev in v.items()} for a, b, v in d['subs']}
        self.car._sent = {(a, b, c): bytes.fromhex(v) for a, b, c, v in d['sent']}
        self._acked = {tuple(k): time.time() for k in d.get('acked', ())}
        self.car.avg_speed, self.car.avg_cons = d['avg_speed'], d['avg_cons']
        self.car.trip_start, self.car.trip_odo = d.get('trip') or (None, None)
        for f in d.get('pending', ()):
            self._enqueue(bytes.fromhex(f))

    # --- dispositivos MOST do V850 ----------------------------------------------------------------------------
    CLIENT = 2
    @staticmethod
    def hmi_devices():
        """(FBlock, instância) de todos os dispositivos MOST que o HMI sabe usar (idemu/data/hmi_most_map.json, extraído do HmiMain3D do SWFL
        007_051_002 por tools/hmi_most_map.py: FactoryInstID de cada grupo CPxy*)."""
        import json, os
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'hmi_most_map.json')) as f:
            m = json.load(f)
        return sorted({(d['fblock'], d['inst']) for d in m['devices'] if d['inst'] is not None})
    DEVCTRL = 0x0200
    # dispositivos do carro (FBlock, instância): Kombi (0xE0/0), Vehicle (0x05/0); `IDEMU_MOST_DEVICES=all` registra os 171 do HMI (satura a CPU do guest)
    # + blocos que o HMI assina e para os quais ha Status neutro validado (idemu/data/hmi_property_defaults.json); registrados no boot porque o HMI cria os CDevCar* na inicializacao
    CORE_DEVICES = ((0xE0, 0), (0x05, 0), (0xD1, 2), (0xD1, 4), (0xD1, 16), (0xD1, 17), (0xE5, 1), (0xE5, 3), (0xE5, 15), (0xC0, 3), (0x03, 0), (0x71, 0),
                    (0x15, 2), (0x15, 3), (0x15, 12), (0xE1, 0))
    # navegação (com NAVI_VARIANTE != keine_navi): Navigation (posição/GPS bruto) e NavigationInfo (posição+rumo+velocidade). IDEMU_NAV_DEVICES=0 não os registra no boot
    NAV_DEVICES = ((0x52, 0), (0xCD, 1), (0xCD, 3), (0xDA, 1))
    # telefone: Bluetooth (0x54/0), Telephone (0x50/1..4) e GeneralPhoneBook (0x51/0). No carro quem os serve é o processo Connectivity (/opt/conn, fora do disco do IDEmu).
    # Só têm efeito com PHONE_TYPE=internal_phone na codificação (sem ela o CDevCarBluetooth ignora o MOST e o HMI não assina nada). IDEMU_PHONE_DEVICES=0 não os registra
    PHONE_DEVICES = ((0x54, 0), (0x50, 1), (0x50, 2), (0x50, 3), (0x50, 4), (0x51, 0))

    def register_devices(self, devs):
        keys = [(fb << 8) | inst for fb, inst in devs]
        for i in range(0, len(keys), 40):
            ch = keys[i:i + 40]
            self.send(2, _st.pack('<IHI', self.CLIENT, 0, len(ch)) + b''.join(_st.pack('<H', k) for k in ch))

    def start(self):
        """Chamado no "hello" do `most`: registra o V850 como cliente MOST; o resto segue na resposta (id 0x8000)."""
        self.send(5)

    def on_client_registered(self, client_id, device_id):
        self.CLIENT = client_id
        self.device_id = device_id
        self.link.log('ponte25: cliente MOST %d, dispositivo %#06x' % (client_id, device_id))
        self.send(3, _st.pack('<IHI', client_id, 0, 1) + _st.pack('<H', self.DEVCTRL))
        import os
        sel = os.environ.get('IDEMU_MOST_DEVICES', 'core')
        devs = self.hmi_devices() if sel == 'all' else self.CORE_DEVICES + (self.NAV_DEVICES if os.environ.get('IDEMU_NAV_DEVICES', '1') != '0' else ()) + \
            (self.PHONE_DEVICES if os.environ.get('IDEMU_PHONE_DEVICES', '1') != '0' else ()) if sel == 'core' else ()
        self.register_devices(devs)

    # HMI -> CarPlay (AuxiliaryInput 0x24, instance 0x70): every CarPlayControllerInput (0xCD3) and CarPlayTouchInput (0xCD5, touch on
    # the screen) is listed on the CarPlay video (glhost, "V k <text>" on <ctl>/input.sock): raw bytes + decoded ("Show keystrokes").
    CARPLAY_KEYS = (0xcd3, 0xcd5)
    ctl = None
    _cpsock = None

    def carplay_forward(self, m):
        if m.func == 0xcd3: self.carplay_keylog(self.carplay_key_text(bytes(m.data), self._next_key()))
        if m.func == 0xcd5: self.carplay_keylog(self.carplay_touch_text(bytes(m.data), self._next_key()))

    CTRL_FIELDS = ('press', 'back', 'up', 'down', 'left', 'right', 'voice')
    _keyn = 0

    @classmethod
    def carplay_key_text(cls, d, n=0):
        """'#n  01 00 00 00 00 00 00 00  rot +1 press' (bytes: rotation 1..126 clockwise / 128.. counter-clockwise, then the 7 keys)"""
        hx = ' '.join('%02x' % b for b in d[:8])
        if len(d) < 8: return '#%d  %s  (short: %d bytes)' % (n, hx, len(d))
        r = 0 if d[0] == 0 else d[0] if d[0] < 128 else -(d[0] - 127)
        on = (['rot %+d' % r] if r else []) + [k for k, v in zip(cls.CTRL_FIELDS, d[1:8]) if v]
        return '#%d  %s  %s' % (n, hx, ' '.join(on) or 'released')

    TOUCH_STATES = ('down', 'move', 'up')

    @classmethod
    def carplay_touch_text(cls, d, n=0):
        """'#n  touch 00 01 00c8 0064 1e 00  200,100 down': CarPlayTouchInput = u8 type (0 = screen), u8 count, then per finger u16 x,
        u16 y (display pixels), u8 z, u8 state (0 down, 1 move, 2 up) (CCarPlayActivity::handleTouchInput, "On screen: touch= type= ...")"""
        if len(d) < 2: return '#%d  touch %s  (short)' % (n, ' '.join('%02x' % b for b in d))
        hx, out, i = '%02x %02x' % (d[0], d[1]), [], 2
        for _ in range(d[1]):
            r = d[i:i + 6]; i += 6
            if len(r) < 6: out.append('(short)'); break
            x, y = r[0] << 8 | r[1], r[2] << 8 | r[3]
            hx += ' %04x %04x %02x %02x' % (x, y, r[4], r[5])
            out.append('%d,%d %s' % (x, y, cls.TOUCH_STATES[r[5]] if r[5] < 3 else 'state %d' % r[5]))
        return '#%d  touch %s  %s' % (n, hx, '; '.join(out) or 'no fingers')

    def _next_key(self):
        self._keyn += 1
        return self._keyn

    carplay_keys = False     # "Show keystrokes" in the CarPlay tab (idemu/carplay.py); off by default: nothing listed

    def carplay_keylog(self, text):
        import os, socket
        if not self.carplay_keys or not self.ctl: return
        try:
            if self._cpsock is None: self._cpsock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            self._cpsock.sendto(('V k ' + text).encode()[:120], os.path.join(self.ctl, 'input.sock'))
        except OSError:
            pass                    # glhost not running

    RETRY_ACK_S = 30.0       # intervalo mínimo entre acks de Notification de uma propriedade sem valor conhecido

    def on_most(self, m):
        """Telegrama do HMI/MSS para um dos FBlocks que registramos."""
        k = (m.fblock, m.inst, m.func, m.op)
        self.counts[k] = self.counts.get(k, 0) + 1
        if m.func != 1:
            import time as _t
            sk = (m.fblock, m.inst, m.func); old = self.seen.get(sk)
            self.seen[sk] = {'op': m.op, 'data': bytes(m.data), 't': _t.time(), 'n': (old['n'] if old else 0) + 1}
            if (m.fblock, m.inst) == (0x24, 0x70) and m.func in self.CARPLAY_KEYS: self.carplay_forward(m)
        if m.func == 1 and m.op == MostMessage.OP_SET and len(m.data) == 5 and m.data[0] == 1:      # FktID 0x001 = Notification
            fkt = _st.unpack('>H', m.data[3:5])[0]
            self.subs.setdefault((m.fblock, m.inst), {})[fkt] = _st.unpack('>H', m.data[1:3])[0]     # fkt -> dispositivo ouvinte
            data = self.car.status_for(m.fblock, m.inst, fkt) if self.car is not None else None        # valor inicial da propriedade assinada
            # O HMI repete a assinatura ("notification retry") até receber um Status. Para as propriedades sem valor conhecido (~50, ~30 repetições/s no total), responder a cada repetição
            # saturava o canal 25: o guest descartava mensagens ("rx: fila cheia") com o `most` sob pressão. Elas recebem o ack só de vez em quando; repetir não adianta nada.
            now, key = time.time(), (m.fblock, m.inst, fkt)
            if data is not None or now - self._acked.get(key, 0) >= self.RETRY_ACK_S:
                self._acked[key] = now
                self.send_most(MostMessage(m.src, m.dst, m.fblock, m.inst, 1, MostMessage.OP_STATUS, m.data))
            if data is not None:
                self.publish(m.fblock, fkt, data, m.inst)
                self.car._sent[(m.fblock, m.inst, fkt)] = data
        elif m.fblock == 0xDA and self.car is not None and self.car.map_set(m.inst, m.func, m.op, m.data):
            self.link.log('ponte25 mapa <- %03x op=%d %s' % (m.func, m.op, m.data.hex()))
            data = self.car.status_for(m.fblock, m.inst, m.func)
            if data is not None:
                self.send_most(MostMessage(m.src, m.dst, m.fblock, m.inst, m.func, MostMessage.OP_STATUS, data))
                self.publish(m.fblock, m.func, data, m.inst)
                self.car._sent[(m.fblock, m.inst, m.func)] = data
        elif m.fblock == 0xDA and m.op == MostMessage.OP_GET and self.car is not None and self.car.status_for(m.fblock, m.inst, m.func) is not None:
            self.send_most(MostMessage(m.src, m.dst, m.fblock, m.inst, m.func, MostMessage.OP_STATUS, self.car.status_for(m.fblock, m.inst, m.func)))   # Get de MapControl (0x222, 0x21E...)
        elif self.counts[k] <= 2:
            self.link.log('ponte25 MOST <- %r' % (m,))

    def send_most(self, m):
        # Status (inclusive o ack de Notification, função 1) só vale pelo valor mais recente: coalesce na fila de envio em vez de empilhar (ver _enqueue)
        key = (m.fblock, m.inst, m.func, m.data if m.func == 1 else None) if m.op == MostMessage.OP_STATUS else None
        self.send(4, _st.pack('<I', self.CLIENT) + m.pack(), coalesce=key)

    def publish(self, fblock, fkt, data, inst=1):
        """Envia `Status` de uma propriedade a quem a assinou (Notification); devolve o número de ouvintes atendidos."""
        n = 0
        dev = self.subs.get((fblock, inst), {}).get(fkt)
        if dev is not None:
            self.send_most(MostMessage(dev, getattr(self, 'device_id', 0x2002), fblock, inst, fkt, MostMessage.OP_STATUS, data)); n = 1
        return n

    def push(self, fblock, fkt, data, inst=1, op=None):
        """Like publish, but also for a property nobody subscribed to yet: sends to the device that subscribed to any function of the
        same (FBlock, instance), or to the HMI's device. Used to play a device the HMI does not know yet (idemu/carplay.py)."""
        subs = self.subs.get((fblock, inst), {})
        dev = subs.get(fkt) or next(iter(subs.values()), None) or getattr(self, 'hmi_dev', None)
        if dev is None:
            for v in self.subs.values():
                if v: dev = next(iter(v.values())); break
        if dev is None: return 0
        self.send_most(MostMessage(dev, getattr(self, 'device_id', 0x2002), fblock, inst, fkt, MostMessage.OP_STATUS if op is None else op, data))
        return 1

    def send(self, msgid, payload=b'', cf=0xffff, b0=1, coalesce=None):
        import struct
        hdr = bytearray(20)
        hdr[0] = b0
        struct.pack_into('<H', hdr, 2, self.KEY)
        hdr[4], hdr[5] = self.VER
        struct.pack_into('<H', hdr, 6, msgid)
        struct.pack_into('<H', hdr, 8, 20 + len(payload))     # o `most` grava aqui o tamanho TOTAL (cabeçalho + payload)
        struct.pack_into('<H', hdr, 0x10, cf)
        self.stats['tx'] += 1
        self.link.log('ponte25 -> id=%#x len=%d payload=%s' % (msgid, len(payload), bytes(payload)[:64].hex()))
        self._enqueue(bytes(hdr) + bytes(payload), coalesce)

    # Ritmo de envio ao guest: com muitos dispositivos registrados, o HMI assina ~170 propriedades de uma vez e cada uma recebe ack + valor inicial
    # (~350 mensagens em segundos); isso estourava a fila rx25 do io-ipc e o `most` morria (HMI: "ComponentDisconnected" -> SVC_FatalError em cascata).
    RATE = 30.0      # mensagens/s (IDEMU_MOST_RATE; 0 = sem limite). Era 10/s com o relógio do guest 10x adiantado (ver runtime.CPU); o limite segue porque o io-ipc tem fila finita (rx25)
    BURST = 4

    # Sem coalescer, o HMI repetia as assinaturas ("notification retry", ~1,6 s por propriedade) mais rápido do que RATE as atendia: a fila crescia sem limite (chegou a ~30 min de atraso), o HMI
    # recebia valores velhos e, como a resposta atrasava, repetia ainda mais. Agora a fila guarda só o último Status de cada propriedade, na posição do primeiro ainda pendente.
    def _enqueue(self, frame, key=None):
        import collections, os
        if getattr(self, '_pending', None) is None:
            try:
                self._rate = float(os.environ.get('IDEMU_MOST_RATE', self.RATE))
            except ValueError:
                self._rate = self.RATE
            self._pending, self._cv, self._seq = collections.OrderedDict(), threading.Condition(), 0
            if self._rate > 0:
                threading.Thread(target=self._pump, daemon=True, name='most-tx').start()
        if self._rate <= 0:
            self.link.send(25, frame)
            return
        with self._cv:
            if key is None:
                self._seq += 1
                key = ('seq', self._seq)
            self._pending[key] = frame
            self._cv.notify()

    def stop(self):
        """Encerra os threads da ponte (most-car e most-tx) quando o ambiente para."""
        self._closed = True
        self.car.stop()
        cv = getattr(self, '_cv', None)
        if cv is not None:
            with cv:
                cv.notify_all()

    def _pump(self):
        import time
        tokens, last = float(self.BURST), time.time()
        while not getattr(self, '_closed', False):
            with self._cv:
                while (not self._pending or self._hold) and not getattr(self, '_closed', False):
                    self._cv.wait()
                if getattr(self, '_closed', False):
                    return
            while True:
                now = time.time()
                tokens = min(float(self.BURST), tokens + (now - last) * self._rate); last = now
                if tokens >= 1.0:
                    tokens -= 1.0
                    break
                time.sleep((1.0 - tokens) / self._rate)
            with self._cv:                                  # só tira da fila na hora de enviar: um Status mais novo ainda substitui este durante a espera do limitador
                if self._hold or not self._pending:
                    continue
                _, frame = self._pending.popitem(last=False)
            try:
                self.link.send(25, frame)
            except Exception:
                pass

    def snapshot(self):
        return {'hello': bool(self.hello), 'rx': self.stats['rx'], 'tx': self.stats['tx'], 'client': self.CLIENT, 'car': {'speed_avg': round(self.car.avg_speed, 1), 'cons_avg': round(self.car.avg_cons, 1)},
                'tx_pending': len(getattr(self, '_pending', None) or ()),
                'subscriptions': {'%02X%02X' % k: sorted(v) for k, v in self.subs.items()},
                'recent': [{'id': m['id'], 'len': m['len'], 'payload': m['payload'][:24].hex()} for m in self.msgs[-10:]]}


import struct as _st


class MostMessage(object):
    """`DSYSMOSTTypes::MessageType` serializada (CHBByteStream, little-endian, sem alinhamento), como trafega na ponte do canal 25:
        i32 eTransmissionType | i32 variante (0 = TXControl normal) | u16 destino | u16 origem | u8 FBlock | u8 instância |
        u16 função | u8 OpType | u32 (=1) | u32 n | n bytes de dados
    (`informationProcessMessage` traz um u32 antes: id do cliente, 0 = difusão.)"""
    OP_SET, OP_GET, OP_SETGET, OP_STATUS = 0, 1, 2, 0x0C

    def __init__(self, dst, src, fblock, inst, func, op, data=b'', ttype=2, var=0, hlen=1):
        self.dst, self.src, self.fblock, self.inst, self.func, self.op = dst, src, fblock, inst, func, op
        self.data, self.ttype, self.var, self.hlen = bytes(data), ttype, var, hlen

    def pack(self):
        return (_st.pack('<ii', self.ttype, self.var) + _st.pack('<HHBBHBI', self.dst, self.src, self.fblock, self.inst, self.func, self.op, self.hlen)
                + _st.pack('<I', len(self.data)) + self.data)

    @classmethod
    def parse(cls, p, off=0):
        ttype, var = _st.unpack_from('<ii', p, off); o = off + 8
        dst, src, fb, inst, func, op, hlen = _st.unpack_from('<HHBBHBI', p, o); o += 13
        n, = _st.unpack_from('<I', p, o); o += 4
        return cls(dst, src, fb, inst, func, op, p[o:o + n], ttype, var, hlen)

    def __repr__(self):
        return 'MOST %04X->%04X %02X%02X %04X op=%d %s' % (self.src, self.dst, self.fblock, self.inst, self.func, self.op, self.data.hex())


class MostCar(object):
    """Alimenta o HMI com os dados do carro virtual (CAN) publicando `Status` das propriedades MOST que ele assinou.

    Propriedades conhecidas (layout lido do código do HMI, tools/hmi_most_map.py; semântica confirmada na tela):
      Kombi (0xE0, instância 0) 0x509 `CBordcomputerAverage`: u16 A | u12 B | u12 velocidade média (0,1 km/h) | u12 D |
          u12 consumo médio (0,1 l/100 km) | u8 unidade (1 = métrico) | u8 unidade  ->  tile "Meu Veículo" da tela inicial.
      Kombi 0x504/0x512 autonomia e 0x510/0x511 início, tempo e distância da viagem (ver _kombi_status).
    """
    KOMBI = (0xE0, 0)
    VEHICLE = (0x05, 0)
    POWER = (0xD1, 2)              # SystemFunctionPowerMode
    NAV = (0x52, 0)                # Navigation
    NAVINFO = (0xCD, 3)            # NavigationInfo
    BLUETOOTH = (0x54, 0)          # Bluetooth (o Connectivity no carro)

    def __init__(self, bridge):
        self.bridge = bridge
        self.can = None
        self.gps = None
        self.map = None
        self._map_scale = 2
        self._map_vals = {}
        self.avg_speed = 0.0
        self.avg_cons = 0.0
        self.trip_start = None         # início da viagem do computador de bordo (epoch); fixado no primeiro Status com o CAN ligado
        self.trip_odo = None           # hodômetro (km) nesse instante
        self._stop = False
        self._sent = {}

    _DEFAULTS = None

    @classmethod
    def _defaults(cls):
        """Status neutro (zeros) por propriedade: sem ele o HMI repete o pedido de Notification ~1x/s para cada uma (carga no guest)."""
        if cls._DEFAULTS is None:
            import json, os
            try:
                with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'hmi_property_defaults.json')) as f:
                    cls._DEFAULTS = json.load(f)['defaults']
            except Exception:
                cls._DEFAULTS = {}
        return cls._DEFAULTS

    def attach_can(self, can):
        """Liga ao CAN virtual (idemu.canbus.CanBus) e passa a publicar a cada segundo."""
        import threading
        self.can = can
        threading.Thread(target=self._run, daemon=True, name='most-car').start()

    def stop(self):
        self._stop = True

    def _sig(self, name, default=0.0):
        try:
            v = self.can.get_signal(name) if self.can else None
            return default if v is None else float(v)
        except Exception:
            return default


    LATLON_LSB = 180.0 / 2 ** 31        # s32 em 180/2^31 graus (confirmado: HmiMain3D 0x165c288 divide por 2^31/180 para obter graus)

    def _gps(self):
        """(fix, lat, lon, alt_m, rumo_graus, velocidade_kmh, satélites, hdop) do GPS virtual, ou None sem GPS."""
        g = self.gps
        if g is None:
            return None
        try:
            st = g.state()
            return (bool(st['fix']), float(st['lat']), float(st['lon']), float(st['alt']), float(st['heading']), float(st['speed_kmh']), int(st['sats']), float(st['hdop']))
        except Exception:
            return None

    def _nav_status(self, fblock, fkt):
        """Status das propriedades de posição do HMI (Navigation 0x52/0 e NavigationInfo 0xCD/3); layout lido do HmiMain3D (/tmp/layout.py)."""
        import os, time
        if '%x' % fkt in os.environ.get('IDEMU_NAV_SKIP', '').split(','):           # depuração: não envia esta propriedade (IDEMU_NAV_SKIP=20b,440)
            return None
        ov = os.environ.get('IDEMU_NAV_OVERRIDE')                                    # depuração: arquivo JSON {"<fblock hex>:<fkt hex>": "<hex do payload>"} lido a cada Status
        if ov:
            try:
                import json
                with open(ov) as f:
                    h = json.load(f).get('%x:%x' % (fblock, fkt))
                if h is not None:
                    return bytes.fromhex(h)
            except Exception:
                pass
        if fblock == 0x52 and fkt == 0x23c:                  # CNav_StateOfOperation: u8. 2 = totalmente operável (log do HMI: isNaviFullyOperable='true'; abre o menu Navegação e o mapa). IDEMU_NAV_STATE troca o valor
            return bytes((int(os.environ.get('IDEMU_NAV_STATE', '2'), 0) & 0xFF,))
        g = self._gps()
        if g is None:
            return None
        fix, lat, lon, alt, hdg, spd, sats, hdop = g
        ilat = max(-2**31, min(2**31 - 1, int(round(lat / self.LATLON_LSB)))); ilon = max(-2**31, min(2**31 - 1, int(round(lon / self.LATLON_LSB))))   # lon = 180,0 dava 2^31 e quebrava o pack
        alt = max(-0x8000, min(0x7FFF, alt))
        hdg8 = int(round(hdg % 360.0 * 256 / 360)) & 0xFF      # rumo em u8: 360/256 graus (CNaviSplitscreenPositionView, HmiMain3D 0x127a868)
        if fblock == 0x52 and fkt == 0x243:                  # CPos_Position: u16 | s32 lat | s32 lon | u8 | s16
            return _st.pack('>HiiBh', 0, ilat, ilon, hdg8, max(-0x8000, min(0x7FFF, int(round(spd)))))     # mesmos campos de 0x20b, sem o seletor (semântica dos três últimos por analogia, não confirmada)
        if fblock == 0x52 and fkt == 0x440:                  # CGPS_RawData: s32 lat | s32 lon | u8 | u8<=80 usados | u8<=80 visiveis | s16 | u8 | s16 | u16 ano | mes | dia | h | min | s
            t = time.gmtime()
            return _st.pack('>iiBBBhBhHBBBBB', ilat, ilon, 3 if fix else 0, min(80, sats), min(80, sats + 2), int(round(alt)), int(round(hdop * 10)) & 0xFF,
                            int(round(hdg)) & 0x7FFF, t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)
        if fblock == 0xCD and fkt == 0x20b:                  # CPositionHeadingSpeed (handler em 0x23b8468): u8 seletor (0 = todos os campos) | u8 == 0 | u16 ? | s32 lat | s32 lon | u8 rumo | s16 (velocidade? unidade não confirmada)
            return _st.pack('>BBHiiBh', 0, 0, 0, ilat, ilon, hdg8, max(-0x8000, min(0x7FFF, int(round(spd)))))
        if fblock == 0xCD and fkt == 0x202:                  # CGPSPosition (handler em 0x23b8624): u32 lon | u32 lat em milissegundos de arco, deslocados de 2^31; 0xFFFFFFFF = inválido (getter em 0x1602ee0). É o que a tela de posição usa na instância 3
            if not fix:
                return b'\xff' * 8
            return _st.pack('>II', 0x80000000 + int(round(lon * 3600000)), 0x80000000 + int(round(lat * 3600000)))
        if fblock == 0xCD and fkt == 0x203:                  # CGPSPositionExtension (handler em 0x23b6a60): u8 rumo | u16 ? | u16<=0xFFF ? | u16 ?
            return _st.pack('>BHHH', hdg8, 0, 0, 0)
        return None

    # ---- MapControl (0xDA): o HMI pede escala, vista, modo... ao processo de navegação. Quem desenha é src/glhost/map.c (idemu/mapsvc.py); layouts lidos do HmiMain3D.
    MAPCTL = {0x200: bytes(8) + _st.pack('>II', 1440, 540), 0x201: b'\x01', 0x221: b'\x00', 0x222: b'\x00', 0xc21: b'\x01', 0xcd2: bytes(8) + _st.pack('>II', 1440, 540), 0x813: b'\x00'}
    MAP_EDITABLE = (0x200, 0x201, 0x220, 0x221, 0x222, 0xc21, 0xcd2)

    def map_set(self, inst, fkt, op, data):
        """Set/SetGet do HMI numa propriedade de MapControl. Devolve True se a função é conhecida."""
        if inst != 1 or op not in (MostMessage.OP_SET, 2) or fkt not in self.MAP_EDITABLE:
            return False
        if fkt == 0x220 and len(data) >= 1:
            self._map_scale = data[0]
            if self.map is not None:
                from . import mapsvc
                self.map.set(zoom=mapsvc.ZOOMS[min(data[0], len(mapsvc.ZOOMS) - 1)])
        elif fkt == 0x221 and data and self.map is not None:
            self.map.set(headup=data[0] != 0)
        self._map_vals[fkt] = bytes(data)
        return True

    def _map_status(self, fkt):
        from . import mapsvc
        if fkt in self._map_vals:
            return self._map_vals[fkt]
        if fkt == 0x21f:      # CMC_AvailableScales: u16 posição=0 | u8 0, depois (u16 id | u8 ? | u32 valor)..., terminado por id 0xFFFF
            b = _st.pack('>HB', 0, 0)
            for i, m in enumerate(mapsvc.SCALES_M):
                b += _st.pack('>HBI', i, 0, m)
            return b + _st.pack('>HBI', 0xFFFF, 0, 0)
        if fkt == 0x220:      # CMC_MapScale: u8 | u32
            i = self._map_scale
            return _st.pack('>BI', i, mapsvc.SCALES_M[min(i, len(mapsvc.SCALES_M) - 1)])
        if fkt == 0x21e:      # CMC_MapScaleLengthInPixel: u8 | u32
            return _st.pack('>BI', self._map_scale, 100)
        return self.MAPCTL.get(fkt)

    def range_km(self):
        """Autonomia (km) = combustível do CAN / consumo médio. Sem média ainda (logo após ligar), usa o consumo instantâneo; piso de 4 l/100 km como o painel (idemu/cluster.py)."""
        cons = self.avg_cons if self.avg_cons >= 0.1 else self._sig('fuel_consumption', 7.5)
        return int(max(0.0, self._sig('fuel_level')) / max(4.0, cons or 7.5) * 100.0)

    def _trip(self):
        """(início epoch, hodômetro no início) da viagem; fixado na primeira consulta com o CAN ligado (cada boot do ambiente é uma viagem nova)."""
        import time
        if self.trip_start is None and self.can is not None:
            self.trip_start, self.trip_odo = time.time(), self._sig('odometer')
        return self.trip_start, self.trip_odo

    def _kombi_status(self, fkt):
        """Computador de bordo do Kombi (0xE0/0). Layouts lidos dos tratadores `Status` (vtable[8]) e dos getters chamados por CDevCarOnBoardComputer (0xfea29c)
        e CDevCarTripComputer (0xfec880, 0xfecac4) no HmiMain3D 2720 (docs/V850.md, "Autonomia e computador de viagem")."""
        import os, time
        if '%x' % fkt in os.environ.get('IDEMU_KOMBI_SKIP', '').split(','):        # depuração: deixa esta propriedade no padrão de zeros (IDEMU_KOMBI_SKIP=510,511)
            return None
        if fkt == 0x509:      # CBordcomputerAverage: u16 | u16 B | u16 C | u16 D | u16 E (<= 0xFFF) | u8<=3 | u8<=7. B/D = velocidade/consumo médios do computador de bordo,
                              # C/E = os da viagem (tile "Meu Veículo"), em 0,1 km/h e 0,1 l/100 km
            spd = max(0, min(4095, int(round(self.avg_speed * 10))))
            con = max(0, min(4095, int(round(self.avg_cons * 10))))
            return _st.pack('>HHHHHBB', 0, spd, spd, con, con, 1, 1)
        if fkt == 0x504:      # CKombiExternalDisplay: u16 | u16<=0xFFF autonomia (km) | u16<=0xFFF | u8<=3. É desta que vem a autonomia mostrada no "Computador de bordo"
                              # (CDevCarOnBoardComputer 0xfea520: <= 0xFA0 válida, 0xFFD inválida); o padrão de zeros mostrava "0 km". O 3º campo (<= 0x1A0) e o u8 (0/1) são lidos
                              # por outro dispositivo (0xf35608, semântica desconhecida) e continuam 0 como no padrão
            return _st.pack('>HHHB', 0, max(0, min(0xFA0, self.range_km())), 0, 0)
        if fkt == 0x512:      # CRangeTankStatus: u16 | u8<=3 | u8 | u8 | u8 | u8<=3 estado | u16<=0xFFF autonomia (km). O HMI só lê os dois últimos: estado 0/1 (2 e 3 descartam o
                              # Status inteiro) e autonomia (0xFFF = inválida, mantém a anterior). Os bytes 3..5 não são lidos por ninguém; vai o tanque em litros no 3º por completude
            tank = max(0, min(255, int(round(self._sig('fuel_level')))))
            return _st.pack('>HBBBBBH', 0, 0, tank, 0, 0, 0, max(0, min(0xFFE, self.range_km())))
        if fkt in (0x510, 0x511):
            t0, odo0 = self._trip()
            if t0 is None:
                return None
            if fkt == 0x510:  # CBordcomputerTravelStart: u16 | u16 ano (<= 3000) | u8 dia (<= 31) | u8 hora (<= 23) | u8 minuto (<= 59) | u8 mês (<= 12); fora disso = inválido
                t = time.localtime(t0)
                return _st.pack('>HHBBBB', 0, t.tm_year, t.tm_mday, t.tm_hour, t.tm_min, t.tm_mon)
            # CBordcomputerTravelData: u16 | u16 horas de viagem (< 2400) | u8 minutos (<= 59) | u16 distância (km, <= 0xFFFC) | s16 (não lido)
            el = max(0, int(time.time() - t0))
            dist = max(0, min(0xFFFC, int(self._sig('odometer') - odo0)))
            return _st.pack('>HHBHh', 0, min(2399, el // 3600), el // 60 % 60, dist, 0)
        return None

    def status_for(self, fblock, inst, fkt):
        """Bytes do Status de uma propriedade (ou None se ainda não sabemos montar)."""
        if (fblock, inst) in (self.NAV, self.NAVINFO):
            return self._nav_status(fblock, fkt)
        if (fblock, inst) == (0xDA, 1):
            return self._map_status(fkt)
        if (fblock, inst) == self.KOMBI and fkt in (0x504, 0x509, 0x510, 0x511, 0x512):
            data = self._kombi_status(fkt)
            if data is not None:
                return data
        if (fblock, inst) == self.VEHICLE:
            # Tamanhos confirmados no HMI (/tmp/sizes.json); a SEMÂNTICA dos bytes ainda não foi confirmada na tela.
            if fkt == 0x621:                       # CCarSpeed2: u16 em 0,01 km/h (hipótese)
                return _st.pack('>H', max(0, min(0xFFFF, int(round(self._sig('vehicle_speed') * 100)))))
            if fkt == 0x228:                       # CGearBox: u8 posição (P/R/N/D como no sinal CAN)
                return _st.pack('>B', int(self._sig('gear_position')) & 0xFF)
            if fkt == 0x22c:                       # CReverseGear: u8 0/1
                return _st.pack('>B', 1 if int(self._sig('gear_position')) == 1 else 0)
            if fkt == 0xcc2:                       # CGearIndicator: u8
                return _st.pack('>B', int(self._sig('gear_position')) & 0xFF)
            if fkt == 0x21f:                       # CTerminalStatus: 3 x u8 <= 15. O 1o byte e o estado do terminal que o CDevCarClamp converte (6,7 = desligado; 8,9 = KL R; 10,12 = KL 15; 13 = motor/KL 50;
                                                   # qualquer outro valor deixa o clamp em "desligado" e os itens de "Meu Veiculo" ficam cinzas). Verificado na tela: 12 habilita os 5 itens.
                ts = int(self._sig('terminal_state', 69))
                first = 6 if ts == 0 else 8 if ts <= 65 else 13 if ts >= 85 else 12
                return _st.pack('>BBB', first, 1 if ts >= 69 else 0, 1 if ts >= 85 else 0)
            if fkt == 0x224:                       # CIgnitionKey: u16 | u8<=15 | u8<=15 | u8<=3 | u8<=3 (6 bytes); semantica por hipotese (chave presente)
                k = 1 if self._sig('key_present', 1) else 0
                return _st.pack('>HBBBB', k, k, k, k, k)
            if fkt == 0xc01:                       # CTyresStatus: u8 | u8<=15 | u8 | u8 | u8. CDevCarTpmStatusImpl so considera o RDC ativo se o 3o byte (b2) & 0xfc for um dos codigos
                                                   # 0x20/0x60/0x80/0xa0/0xa8/0xb0/0xb8/0xe0/0xe8 e o 4o (b3) != 0xff (senao o painel mostra "Controle da pressao dos pneus inoperante").
                return bytes((0, 0, 0xa0, 0, 0))   # semantica de 0xa0 por hipotese (RDC ativo); o temporizador de 'sem dados' do TPM e neutralizado no guest (src/shim/hook.c)
            if fkt == 0xc02:                       # CTyrePressure: 4 x u16 (FL, FR, RL, RR) em kPa (hipótese)
                v = [max(0, min(0xFFFF, int(round(self._sig(n) * 100)))) for n in
                     ('tire_pressure_fl', 'tire_pressure_fr', 'tire_pressure_rl', 'tire_pressure_rr')]
                return _st.pack('>HHHH', *v)
        if (fblock, inst) == self.POWER and fkt == 0xc10:   # CSyncMarker: 4 bytes; bit 4 do 4o byte = "chave no carro" (CDevApplicationAvailability::onSyncMarkerStatus -> bKeyInCar)
            return bytes((0, 0, 0, 0x10 if self._sig('key_present', 1) else 0))
        if (fblock, inst) == self.POWER and fkt in (0x430, 0x434):
            # 0x430 = estado de energia (u8<=16: 3 = PM_fullon_useron) e CPowerStateDetailed (u8: 0x64 -> PMD_Entertainmentmode_useron, logo 0x63 = PMD_Fullon_useron). Sem isso o HMI acha PM_alloff /
            # PMD_Sleepmode_Alloff (log "CDevCarPowerMode::onPxyPowerState ... PM_alloff") e os estados de menu que exigem terminal ligado ficam cinzas.
            on = int(self._sig('terminal_state', 69)) != 0
            return bytes((3 if on else 0,)) if fkt == 0x430 else bytes((0x63 if on else 0,))
        if (fblock, inst) == self.BLUETOOTH:
            # Layouts dos decodificadores (vtable[6] de CPxyBluetooth::C…): 0x200 CBluetoothEnable = u8 bool (log "Bluetooth enabled"); 0xC0B CBTServiceUnavailable e
            # 0xC0D CBluetoothServiceActivationState = 2 x u8 (log "All available" / "New bits: 0x0000"). Com isso aparecem "Últimas chamadas" e "Discar número" em
            # Comunicação e abrem as telas de telefone e de pareamento. Não há rádio Bluetooth: nenhum telefone conecta de verdade.
            return {0x200: b'\x01', 0xC0B: b'\x00\x00', 0xC0D: b'\x00\x00'}.get(fkt)
        d = self._defaults().get('%02x:%d:%03x' % (fblock, inst, fkt))
        return bytes.fromhex(d) if d else None

    def _run(self):
        import time
        while not self._stop:
            a = 0.05           # média móvel (constante de ~5 s a 4 Hz)
            self.avg_speed += a * (self._sig('vehicle_speed') - self.avg_speed)
            self.avg_cons += a * (self._sig('fuel_consumption') - self.avg_cons)
            try:
                self.publish_all()       # só manda o que mudou; o limite de 30 msg/s da ponte continua valendo
            except Exception as e:       # um valor fora da faixa não pode matar o thread: velocidade, marcha e autonomia parariam sem aviso
                try: self.bridge.link.log('most-car: %r' % (e,))
                except Exception: pass
            time.sleep(0.25)             # 4 Hz: velocidade e marcha acompanham o CAN virtual sem o atraso de até 1 s

    def publish_all(self):
        """Envia o Status das propriedades assinadas, mas só as que mudaram desde o último envio (o valor inicial vai na própria assinatura)."""
        n = 0
        for (fb, inst), fkts in list(self.bridge.subs.items()):
            for fkt in list(fkts):
                data = self.status_for(fb, inst, fkt)
                if data is not None and self._sent.get((fb, inst, fkt)) != data:
                    self._sent[(fb, inst, fkt)] = data
                    n += self.bridge.publish(fb, fkt, data, inst)
        return n
