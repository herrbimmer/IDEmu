"""CarPlay tab, "Connect fake iPhone" (idemu/carplay.py): the MOST messages that make the HMI show its CarPlay screens, in order, and
the reverse when the switch is turned off."""
import os, socket, sys, tempfile, threading, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from idemu import carplay as cp


class FakeBridge(object):
    """Records pushes; the HMI 'subscribes' to every property as soon as it is registered."""
    def __init__(self, subscribe=True):
        self.subs, self.pushed, self.registered = {}, [], []
        self.subscribe = subscribe
    def register_devices(self, devs):
        self.registered += devs
        if self.subscribe:
            self.subs[(cp.BT, 0)] = {cp.F_FV: 1}
            self.subs[(cp.AUXIN, cp.CP)] = {cp.F_DEVINFO2: 1, cp.F_MODESCHANGED: 1, cp.F_VIDEOREADY: 1}
    def push(self, fblock, fkt, data, inst=1, op=None):
        self.pushed.append((fblock, inst, fkt, data)); return 1


def wait_state(f, states, timeout=15):
    t0 = time.time()
    while f.state not in states:
        if time.time() - t0 > timeout: raise AssertionError('state stayed %s' % f.state)
        time.sleep(0.05)


class FakeIPhoneTest(unittest.TestCase):
    def setUp(self):
        self.ctl = tempfile.mkdtemp()
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM); self.sock.bind(os.path.join(self.ctl, 'input.sock')); self.sock.settimeout(2)
        self._sleep = cp.FakeIPhone._sleep
        cp.FakeIPhone._sleep = lambda self, g, s: self._live(g)          # no 2 s pauses in tests

    def tearDown(self):
        cp.FakeIPhone._sleep = self._sleep
        self.sock.close()

    def test_connect_then_disconnect(self):
        b = FakeBridge(); f = cp.FakeIPhone(b, self.ctl)
        self.assertEqual(f.status()['state'], 'off')
        self.assertEqual(f.set(True)['state'], 'connecting')
        wait_state(f, ('connected', 'error'))
        self.assertEqual(f.state, 'connected', f.error)
        self.assertEqual(b.registered, [(cp.AUXIN, cp.CP), (cp.BT, 0)])
        fkts = [p[2] for p in b.pushed]
        self.assertEqual(fkts, [cp.F_BTENABLE, cp.F_SVC_STATE, cp.F_FV, cp.F_CPSTATUS, cp.F_DEVINFO2, cp.F_MODESCHANGED, cp.F_VIDEOREADY])
        self.assertEqual(b.pushed[5][3][:4], bytes([0, 1, 1, 1]))          # the phone owns the screen
        self.assertEqual(b.pushed[6][3][2], 1)                               # video ready
        self.assertIn(b'V t Apple CarPlay - iPhone|', self.sock.recv(512))

        b.pushed.clear()
        f.set(False); wait_state(f, ('off', 'error'))
        self.assertEqual(f.state, 'off', f.error)
        pushed = {p[2]: p[3] for p in b.pushed}
        self.assertEqual(pushed[cp.F_MODESCHANGED][:4], bytes([0, 1, 1, 2]))  # the car takes the screen back
        self.assertEqual(pushed[cp.F_VIDEOREADY], bytes(8))
        self.assertEqual(pushed[cp.F_DEVINFO2][3], 0)                          # not connected
        self.assertTrue(pushed[cp.F_FV].endswith(bytes(4) + b'\x01'))          # no application connected

    def test_show_keys(self):
        b = FakeBridge(); f = cp.FakeIPhone(b, self.ctl)
        self.assertFalse(f.status()['show_keys'])                            # the key list is off by default
        self.assertTrue(f.show_keys(True)['show_keys'])
        self.assertFalse(f.show_keys(False)['show_keys'])
        self.assertFalse(b.carplay_keys)
        self.assertEqual(self.sock.recv(512), b'V k')                        # off clears what is listed
        self.assertTrue(f.show_keys(True)['show_keys'])

    def test_most_keylog_follows_show_keys(self):
        from idemu import most
        br = most.MostBridge.__new__(most.MostBridge); br.ctl = self.ctl
        self.assertFalse(br.carplay_keys)                                    # off by default
        br.carplay_keys = True
        br.carplay_keylog('#1  01 00 00 00 00 00 00 00  rot +1')
        self.assertEqual(self.sock.recv(512), b'V k #1  01 00 00 00 00 00 00 00  rot +1')
        br.carplay_keys = False
        br.carplay_keylog('#2  hidden')
        self.sock.settimeout(0.3)
        self.assertRaises(socket.timeout, self.sock.recv, 512)

    def test_setup_missing_and_setup_env(self):
        bmw = {'id': 'f07', 'coding': {'extra': {}}}                       # a BMW environment as created: no CarPlay
        self.assertEqual(cp.setup_missing(bmw), ['conn', 'variant 0x5153', 'variant 0x4e59', 'CARPLAY_SWT'])
        cp.setup_env(bmw)
        self.assertEqual(cp.setup_missing(bmw), ['CARPLAY_SWT'])            # the coding comes from the coding flash
        bmw['coding']['extra']['CARPLAY_SWT'] = 1
        self.assertEqual(cp.setup_missing(bmw), [])
        mini = {'conn': True, 'variants': {'0x5153': 1, '0x4E59': 1, '0x1': 0}, 'coding': {'extra': {'CARPLAY_SWT': 1}}}
        self.assertEqual(cp.setup_missing(mini), [])
        cp.setup_env(mini)
        self.assertEqual(mini['variants']['0x1'], 0)                         # other variants are kept

    def test_repeated_on_is_ignored(self):
        b = FakeBridge(subscribe=False); f = cp.FakeIPhone(b, self.ctl)
        f.set(True); f.set(True)
        self.assertEqual(f.gen, 1)
        f.set(False); wait_state(f, ('off',))                                # turning off while waiting cancels the connect

    def test_hmi_never_subscribes(self):
        b = FakeBridge(subscribe=False); f = cp.FakeIPhone(b, self.ctl)
        old = cp.WAIT_S; cp.WAIT_S = 0.2
        try:
            f.set(True); wait_state(f, ('error',))
        finally: cp.WAIT_S = old
        self.assertIn('Bluetooth device list', f.error)
        self.assertEqual(b.pushed, [])


if __name__ == '__main__':
    unittest.main()
