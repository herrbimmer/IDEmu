"""Fake iPhone for the HMI's CarPlay screens (iDrive 5/6, NBT Evo): the switch "Connect fake iPhone" in the CarPlay tab.

Plays over IDEmu's virtual MOST bridge what the head unit's phone side would send (docs/CARPLAY.md): the
Bluetooth device list with a CarPlay phone, AuxIn DeviceInfo2 "connected", CarPlayModesChanged (the phone takes the screen) and
VideoReady. There is no phone picture: the host draws a placeholder in the CarPlay video layer. A real iPhone cannot connect directly:
it checks the accessory's MFi authentication chip, which the emulated hardware does not have; a CarPlay
dongle, which has the chip, could probably bridge one in."""
import os, socket, threading, time

AUXIN, CP = 0x24, 0x70          # AuxiliaryInput, instance NBT_CarPlay
BT = 0x54
F_VIDEOREADY, F_DEVINFO2, F_MODESCHANGED = 0x136, 0xcc8, 0xcd2
F_BTENABLE, F_SVC_STATE, F_FV, F_CPSTATUS = 0x200, 0xc0d, 0xc10, 0xc35
NAME, MAC = 'iPhone', 'A1:B2:C3:D4:E5:F6'
WAIT_S = 180

# What the HMI needs before it offers CarPlay (docs/CARPLAY.md); in the car these come from its coding and activation. "conn" puts
# /fs/shim/carplay.on in the shim (idemu/builder.py), which makes src/shim/hook.c mark CarPlay as activated (no SWT server).
VARIANTS = {'0x5153': 1, '0x4e59': 1}         # CarPlay entry in the main menu, Bluetooth coded
CODING = {'CARPLAY_SWT': 1}


def setup_missing(env):
    """What the environment still lacks for CarPlay ([] when ready): read from the env the head unit booted with."""
    out = []
    if not env.get('conn'): out.append('conn')
    vs = {k.lower(): v for k, v in (env.get('variants') or {}).items()}
    out += ['variant ' + k for k, v in VARIANTS.items() if not vs.get(k)]
    extra = (env.get('coding') or {}).get('extra') or {}
    out += [k for k, v in CODING.items() if extra.get(k) != v]
    return out


def setup_env(env):
    """Adds conn and the variants to env (the coding goes through the coding flash, which rebuilds the shim and restarts the head unit)."""
    env['conn'] = True
    vs = dict(env.get('variants') or {}); vs.update(VARIANTS); env['variants'] = vs
    return env


def mstr(s):
    """MOST string: 0x01 (ISO 8859) + text + NUL"""
    return b'\x01' + s.encode('latin-1') + b'\x00'


def fv_record(name, mac, apps, index=1):
    """BTDFunctionalityViewer record: name | BT address[6] | 3 bytes | trusted u8 | apps u32 BE | index u8."""
    return mstr(name) + bytes.fromhex(mac.replace(':', '')) + b'\0\0\0' + b'\x01' + apps.to_bytes(4, 'big') + bytes([index])


def modes(screen_owner):
    """CarPlayModesChanged (27 bytes); resource 1 = main screen, owner 1 = the phone, 2 = the car."""
    return (bytes([0, 1, 1, screen_owner]) + bytes(27))[:27]


class FakeIPhone(object):
    """One per running environment. state: off | connecting | connected | disconnecting | error."""

    def __init__(self, bridge, ctl):
        self.bridge, self.ctl = bridge, ctl
        self.state, self.step, self.error = 'off', '', None
        self.lock = threading.Lock()
        self.gen = 0                # a newer request cancels the thread of the older one

    def status(self):
        return {'state': self.state, 'step': self.step, 'error': self.error, 'name': NAME,
                'show_keys': bool(getattr(self.bridge, 'carplay_keys', False))}

    def show_keys(self, on):
        """'Show keystrokes': the list of key codes the HMI sends to CarPlay, drawn over the CarPlay video (idemu/most.py carplay_keylog,
        src/glhost/map.c vid_keys_draw). Off also clears what is listed ("V k" alone)."""
        self.bridge.carplay_keys = bool(on)
        if not on: self._send('V k')
        return self.status()

    def set(self, on):
        with self.lock:
            if on and self.state in ('connecting', 'connected'): return self.status()
            if not on and self.state in ('off', 'disconnecting'): return self.status()
            self.gen += 1; g = self.gen
            self.state, self.step, self.error = ('connecting' if on else 'disconnecting'), '', None
        threading.Thread(target=self._run, args=(g, on), name='fake-iphone', daemon=True).start()
        return self.status()

    # ---- internals ----
    def _live(self, g):
        return g == self.gen

    def _push(self, fblock, inst, fkt, data):
        self.bridge.push(fblock, fkt, bytes(data), inst)

    def _subscribed(self, fblock, inst, fkt):
        return fkt in self.bridge.subs.get((fblock, inst), {})

    def _wait(self, g, fblock, inst, fkt, what):
        self.step = what
        t0 = time.time()
        while not self._subscribed(fblock, inst, fkt):
            if not self._live(g): return False
            if time.time() - t0 > WAIT_S: raise RuntimeError('the HMI never subscribed to %s' % what)
            time.sleep(0.5)
        return self._live(g)

    def _sleep(self, g, s):
        t0 = time.time()
        while time.time() - t0 < s:
            if not self._live(g): return False
            time.sleep(0.1)
        return True

    def _send(self, cmd):
        """An input command for glhost (<ctl>/input.sock); nothing happens when it is not running."""
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try: s.sendto(cmd.encode(), os.path.join(self.ctl, 'input.sock'))
        except OSError: pass
        finally: s.close()

    def _label(self, title, sub):
        """Text of the placeholder in the CarPlay video area (src/glhost/map.c, input command "V t title|sub")."""
        self._send('V t %s|%s' % (title, sub))

    def _run(self, g, on):
        try:
            if on: self._connect(g)
            else: self._disconnect()
            if self._live(g): self.state, self.step = ('connected' if on else 'off'), ''
        except Exception as e:
            if self._live(g): self.state, self.step, self.error = 'error', '', str(e)

    def _connect(self, g):
        self._label('Apple CarPlay - %s' % NAME, 'emulated connection: no video from a phone')
        self.bridge.register_devices([(AUXIN, CP), (BT, 0)])
        if not self._wait(g, BT, 0, F_FV, 'Bluetooth device list'): return
        self.step = 'Bluetooth pairing'
        self._push(BT, 0, F_BTENABLE, b'\x01')
        self._push(BT, 0, F_SVC_STATE, b'\x00\x41')                         # service activation: includes CarPlay (0x40)
        self._push(BT, 0, F_FV, b'\0\0' + fv_record(NAME, MAC, 0x70000005))   # Carplay + Phone1 connected
        self._push(BT, 0, F_CPSTATUS, b'\x04')                              # BTCarPlayStatus: Success
        if not self._wait(g, AUXIN, CP, F_DEVINFO2, 'AuxIn DeviceInfo2'): return
        self._push(AUXIN, CP, F_DEVINFO2, b'\0\0' + bytes([1, 2, 1, 1]) + mstr(NAME) + mstr('IDEMU0001'))   # state 2 = connected
        if not self._wait(g, AUXIN, CP, F_MODESCHANGED, 'CarPlay ModesChanged'): return
        if not self._sleep(g, 2): return
        self._push(AUXIN, CP, F_MODESCHANGED, modes(1))                    # the phone takes the screen
        if not self._wait(g, AUXIN, CP, F_VIDEOREADY, 'AuxIn VideoReady'): return
        if not self._sleep(g, 2): return
        self._push(AUXIN, CP, F_VIDEOREADY, bytes([0, 0, 1, 0, 0, 0, 0, 0]))   # video signal stable

    def _disconnect(self):
        """The connect steps in reverse: the car takes the screen back, video off, CarPlay device gone, phone no longer connected."""
        self.step = 'disconnecting'
        self._push(AUXIN, CP, F_MODESCHANGED, modes(2))
        self._push(AUXIN, CP, F_VIDEOREADY, bytes(8))
        self._push(AUXIN, CP, F_DEVINFO2, b'\0\0' + bytes([1, 0, 1, 1]) + mstr(NAME) + mstr('IDEMU0001'))   # state 0 = not connected
        self._push(BT, 0, F_FV, b'\0\0' + fv_record(NAME, MAC, 0))          # still paired, nothing connected
        self._push(BT, 0, F_CPSTATUS, b'\x00')
        self._label('Apple CarPlay', 'no iPhone connected')
